import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, TypeVar, TypedDict, Optional

import anyio
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
)
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import START, StateGraph, END
from pydantic import BaseModel, Field

from code_agent.checkpointing import (
    generate_thread_id,
    get_checkpoint_db_path,
)
from code_agent.planning import Task, Tasks, load_tasks, save_tasks

T = TypeVar("T", bound=BaseModel)

@dataclass
class ProjectConfig:
    project_path: Path

    @property
    def state_path(self) -> str:
        return f"state/planner_{self.project_path.name}"

    @property
    def tasks_path(self) -> str:
        return str(self.project_path / "tasks.json")

    @property
    def tasks_dir(self) -> str:
        return str(self.project_path / "tasks")

def _print_message(message):
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                print(block.text)

class IdeationState(BaseModel):
    message_to_user: str = Field(description="The message to display to the user (question or proposal).")
    is_question: bool = Field(description="True if you are asking the user a clarification question.")
    ready_to_generate_spec: bool = Field(description="True if you have enough info to generate the spec.")
    spec_content: Optional[str] = Field(default=None, description="The full Markdown content of the spec. Only set this when generating the spec.")
    spec_filename: Optional[str] = Field(default=None, description="The filename for the spec (e.g. 'foo.md'). Only set this when generating the spec.")

class PlannerState(TypedDict):
    config: ProjectConfig
    tasks: Tasks
    current_task: Optional[Task]
    spec_content: Optional[str]

async def select_task_node(state: PlannerState) -> dict:
    config = state["config"]
    tasks = load_tasks(config.tasks_path)

    ideas = [t for t in tasks.ideas if t.status == "idea"]

    print("\nAvailable Ideas:")
    if ideas:
        for idx, task in enumerate(ideas):
            print(f"{idx + 1}. {task.title} ({task.id})")
    else:
        print("(No existing ideas found)")

    create_option_idx = len(ideas) + 1
    print(f"{create_option_idx}. [Create New Idea]")

    choice = -1
    while choice < 1 or choice > create_option_idx:
        try:
            print(f"\nSelect an option (1-{create_option_idx}): ", end="", flush=True)
            inp = await anyio.to_thread.run_sync(sys.stdin.readline)
            if not inp:
                sys.exit(0)
            choice = int(inp.strip())
        except ValueError:
            pass

    if choice == create_option_idx:
        print("\nCreating new idea:")
        print("Title: ", end="", flush=True)
        title = (await anyio.to_thread.run_sync(sys.stdin.readline)).strip()
        if not title:
            print("Title is required.")
            sys.exit(0)

        print("Description: ", end="", flush=True)
        description = (await anyio.to_thread.run_sync(sys.stdin.readline)).strip()

        # ID generation
        slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
        if not slug:
            slug = f"idea-{len(tasks.ideas) + 1}"

        existing_ids = {t.id for t in tasks.ideas}
        base_slug = slug
        counter = 1
        while slug in existing_ids:
            slug = f"{base_slug}-{counter}"
            counter += 1

        selected_task = Task(
            id=slug,
            title=title,
            description=description,
            status="idea"
        )
        tasks.ideas.append(selected_task)
        save_tasks(config.tasks_path, tasks)
        print(f"\nCreated new idea: {selected_task.title} ({selected_task.id})\n")

    else:
        selected_task = ideas[choice - 1]
        print(f"\nSelected: {selected_task.title}")
        print(f"Description: {selected_task.description}\n")

    return {
        "tasks": tasks,
        "current_task": selected_task,
    }

async def ideate_node(state: PlannerState) -> dict:
    config = state["config"]
    task = state["current_task"]

    print("Starting ideation session with Claude...")

    options = ClaudeAgentOptions(
        setting_sources=["project", "user"],
        allowed_tools=["Read", "Bash", "Grep", "Glob"],
        permission_mode="acceptEdits",
        cwd=str(config.project_path),
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": (
                f"\n\nYou are an expert Product Manager helping to plan the task: {task.title}\n"
                f"Description: {task.description}\n"
                "Your goal is to discuss with the user to clarify requirements until you can write a detailed specification.\n"
                "Use the structured output to communicate with the user and control the flow.\n"
                "If you need to ask a question, set is_question=True.\n"
                "If you are ready to write the spec, set ready_to_generate_spec=True.\n"
                "When strictly instructed to generate the spec, populate spec_content and spec_filename.\n"
            )
        },
        output_format={
            "type": "json_schema",
            "schema": IdeationState.model_json_schema(),
        },
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query("Introduce yourself and ask the first clarification question.")

        while True:
            turn_data: Optional[IdeationState] = None
            async for message in client.receive_response():
                _print_message(message)
                if hasattr(message, "structured_output"):
                    turn_data = IdeationState.model_validate(message.structured_output)

            if not turn_data:
                print("\n[Error] Agent did not return valid structured output. Retrying...")
                await client.query("Please respond using the correct structured format.")
                continue

            if turn_data.spec_content and turn_data.spec_filename:
                os.makedirs(config.tasks_dir, exist_ok=True)
                filepath = os.path.join(config.tasks_dir, turn_data.spec_filename)

                with open(filepath, "w") as f:
                    f.write(turn_data.spec_content)

                print(f"\nSpecification saved to {filepath}")

                tasks = state["tasks"]
                updated_ideas = []
                for t in tasks.ideas:
                    if t.id == task.id:
                        t.status = "planned"
                        t.task_file = f"tasks/{turn_data.spec_filename}"
                    updated_ideas.append(t)
                tasks.ideas = updated_ideas
                save_tasks(config.tasks_path, tasks)

                return {"spec_content": turn_data.spec_content}

            if turn_data.ready_to_generate_spec:
                print(f"\nAgent: {turn_data.message_to_user}")
                print("\nAgent is ready to generate the spec. Proceed? (y/n): ", end="", flush=True)
                user_inp = await anyio.to_thread.run_sync(sys.stdin.readline)
                if not user_inp:
                    sys.exit(0)
                user_inp = user_inp.strip()

                if user_inp.lower().startswith("y"):
                    await client.query("Proceed to generate the specification now. Fill in spec_content and spec_filename.")
                else:
                    await client.query("User wants to continue discussion. Ask what is missing.")
                continue

            print(f"\nAgent: {turn_data.message_to_user}")

            print("\nYou: ", end="", flush=True)
            user_inp = await anyio.to_thread.run_sync(sys.stdin.readline)
            if not user_inp:
                sys.exit(0)
            user_inp = user_inp.strip()

            if user_inp.lower() in ["exit", "quit"]:
                sys.exit(0)

            await client.query(user_inp)

workflow = StateGraph(PlannerState)
workflow.add_node(select_task_node)
workflow.add_node(ideate_node)

workflow.add_edge(START, "select_task_node")
workflow.add_edge("select_task_node", "ideate_node")
workflow.add_edge("ideate_node", END)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Planner Agent")
    parser.add_argument("project_path", type=Path, nargs="?", default=".")
    return parser.parse_args()

async def main():
    args = parse_args()
    project_path = args.project_path.resolve()
    config = ProjectConfig(project_path=project_path)

    print(f"Planning tasks for: {config.project_path}")

    db_path = get_checkpoint_db_path(config.state_path)
    os.makedirs(config.state_path, exist_ok=True)

    async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
        app = workflow.compile(checkpointer=checkpointer)
        thread_id = generate_thread_id()
        tasks = load_tasks(config.tasks_path)

        initial_state = {
            "config": config,
            "tasks": tasks,
            "current_task": None,
            "spec_content": None,
        }

        run_config = {"configurable": {"thread_id": thread_id}}
        await app.ainvoke(initial_state, run_config)

if __name__ == "__main__":
    try:
        anyio.run(main)
    except KeyboardInterrupt:
        pass
