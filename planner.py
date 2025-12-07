import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, TypeVar, TypedDict

import anyio
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
)
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import START, StateGraph, END
from pydantic import BaseModel

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

async def run_agent(
    config: ProjectConfig,
    prompt: str,
    output_schema: type[T] | None = None,
    cwd: str | None = None,
    allowed_tools: list[str] | None = None,
    model: str = "sonnet",
) -> T | None:
    cwd_path = cwd or str(config.project_path)
    base_cwd = os.getcwd()
    options = ClaudeAgentOptions(
        setting_sources=["project", "user"],
        allowed_tools=allowed_tools or ["Read", "Bash", "Grep", "Glob"],
        permission_mode="acceptEdits",
        cwd=cwd_path,
        add_dirs=[base_cwd],
        output_format={
            "type": "json_schema",
            "schema": output_schema.model_json_schema(),
        }
        if output_schema
        else None,
        model=model,
        system_prompt={"type": "preset", "preset": "claude_code"},
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt=prompt)
        async for message in client.receive_response():
            _print_message(message)
            if output_schema and hasattr(message, "structured_output"):
                return output_schema.model_validate(message.structured_output)

    return None

class ChatResponse(BaseModel):
    response: str
    action: Literal["CONTINUE", "FINISH"]

class SpecResult(BaseModel):
    content: str
    filename: str

class PlannerState(TypedDict):
    messages: Annotated[list[str], lambda old, new: old + new]
    config: ProjectConfig
    tasks: Tasks
    current_task: Task | None
    spec_content: str | None
    last_action: str | None

async def select_task_node(state: PlannerState) -> dict:
    config = state["config"]
    tasks = load_tasks(config.tasks_path)

    ideas = [t for t in tasks.ideas if t.status == "idea"]
    if not ideas:
        print("No ideas found in tasks.json")
        sys.exit(0)

    print("\nAvailable Ideas:")
    for idx, task in enumerate(ideas):
        print(f"{idx + 1}. {task.title} ({task.id})")

    choice = -1
    while choice < 1 or choice > len(ideas):
        try:
            print(f"\nSelect a task number (1-{len(ideas)}): ", end="", flush=True)
            inp = await anyio.to_thread.run_sync(sys.stdin.readline)
            if not inp:
                sys.exit(0)
            choice = int(inp.strip())
        except ValueError:
            pass

    selected_task = ideas[choice - 1]
    print(f"\nSelected: {selected_task.title}")
    print(f"Description: {selected_task.description}\n")

    initial_msg = (
        f"Agent: Hello! I'm here to help you plan the task '{selected_task.title}'. "
        f"Description: {selected_task.description}. "
        "What details can you provide to help me create a specification?"
    )

    print(initial_msg)

    return {
        "tasks": tasks,
        "current_task": selected_task,
        "messages": [initial_msg],
        "last_action": "CONTINUE"
    }

async def user_input_node(state: PlannerState) -> dict:
    print("\nYou: ", end="", flush=True)
    user_msg = await anyio.to_thread.run_sync(sys.stdin.readline)
    if not user_msg:
         sys.exit(0)

    return {"messages": [f"User: {user_msg.strip()}"]}

async def chat_node(state: PlannerState) -> dict:
    config = state["config"]
    messages = state["messages"]
    task = state["current_task"]

    history = "\n".join(messages)

    prompt = f"""
        You are an expert Product Manager and Software Architect.
        We are planning the following task:
        Title: {task.title}
        Description: {task.description}

        Your goal is to discuss with the user to gather all necessary requirements to write a detailed specification.
        The specification should include:
        - Goal
        - Detailed changes
        - Files to touch (if known)
        - Verification plan

        Conversation History:
        {history}

        If you have enough information to write a full specification, set action to 'FINISH'.
        Otherwise, set action to 'CONTINUE' and ask clarifying questions or propose ideas in 'response'.

        Important: In your response, address the user directly.
    """

    result = await run_agent(
        config=config,
        prompt=prompt,
        output_schema=ChatResponse,
        allowed_tools=["Read", "Bash", "Glob"],
    )

    if result:
        print(f"\nAgent: {result.response}")
        return {
            "messages": [f"Agent: {result.response}"],
            "last_action": result.action
        }

    return {"messages": ["Agent: (Error)"], "last_action": "CONTINUE"}

async def draft_spec_node(state: PlannerState) -> dict:
    print("\nDrafting specification...")
    config = state["config"]
    messages = state["messages"]
    task = state["current_task"]

    history = "\n".join(messages)

    prompt = f"""
        Based on the conversation below, write a detailed Markdown specification for the task.

        Task: {task.title}
        Description: {task.description}

        History:
        {history}

        Return the markdown content and a suitable filename (ending in .md).
    """

    result = await run_agent(
        config=config,
        prompt=prompt,
        output_schema=SpecResult,
        allowed_tools=["Read", "Bash", "Glob"],
    )

    if result:
        os.makedirs(config.tasks_dir, exist_ok=True)
        filepath = os.path.join(config.tasks_dir, result.filename)

        with open(filepath, "w") as f:
            f.write(result.content)

        print(f"\nSpecification saved to {filepath}")

        tasks = state["tasks"]
        updated_ideas = []
        for t in tasks.ideas:
            if t.id == task.id:
                updated_bug = Task(
                    id=t.id,
                    title=t.title,
                    description=t.description,
                    status="planned",
                    task_file=f"tasks/{result.filename}"
                )
                updated_ideas.append(updated_bug)
            else:
                updated_ideas.append(t)

        tasks.ideas = updated_ideas
        save_tasks(config.tasks_path, tasks)
        print("Task status updated to 'planned'.")

        return {"spec_content": result.content}

    return {"messages": ["Failed to draft spec."]}

def route_after_chat(state: PlannerState):
    if state["last_action"] == "FINISH":
        return "draft_spec_node"
    return "user_input_node"

workflow = StateGraph(PlannerState)
workflow.add_node(select_task_node)
workflow.add_node(chat_node)
workflow.add_node(user_input_node)
workflow.add_node(draft_spec_node)

workflow.add_edge(START, "select_task_node")
workflow.add_edge("select_task_node", "user_input_node")
workflow.add_edge("user_input_node", "chat_node")
workflow.add_conditional_edges("chat_node", route_after_chat)
workflow.add_edge("draft_spec_node", END)

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

        # Load tasks initially to pass valid structure
        tasks = load_tasks(config.tasks_path)

        initial_state = {
            "messages": [],
            "config": config,
            "tasks": tasks,
            "current_task": None,
            "spec_content": None,
            "last_action": None
        }

        run_config = {"configurable": {"thread_id": thread_id}}

        await app.ainvoke(initial_state, run_config)

if __name__ == "__main__":
    try:
        anyio.run(main)
    except KeyboardInterrupt:
        pass
