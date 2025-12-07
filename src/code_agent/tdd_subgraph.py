from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, TypeVar

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from typing_extensions import TypedDict


class TaskType(Enum):
    BUG_FIX = "bug_fix"
    FEATURE = "feature"
    REFACTOR = "refactor"


@dataclass
class TDDConfig:
    task_id: str
    task_type: TaskType
    worktree_path: str
    description: str
    details: str
    relevant_files: list[str] = field(default_factory=list)
    max_review_attempts: int = 3


class TDDResult(BaseModel):
    task_id: str
    status: Literal["SUCCESS", "DISCARDED", "MAX_ATTEMPTS_REACHED"]
    test_file_path: str | None
    notes: str
    rejection_history: list[str]


class TDDState(TypedDict):
    config: TDDConfig
    phase: Literal["write_tests", "implement", "refactor", "review", "done"]
    test_file_path: str | None
    implementation_notes: str
    review_attempts: int
    status: Literal["SUCCESS", "DISCARDED", "MAX_ATTEMPTS_REACHED"] | None
    rejection_history: list[str]


class WriteTestsResult(BaseModel):
    status: Literal["PREPARED_FOR_FIX", "DISCARDED"]
    test_file_path: str | None
    notes: str


class ImplementResult(BaseModel):
    status: Literal["READY_FOR_REVIEW", "DISCARDED"]
    notes: str


class RefactorResult(BaseModel):
    refactored: bool
    notes: str


class ReviewResult(BaseModel):
    status: Literal["SUCCESS", "REJECTED"]
    rejection_reason: str | None
    notes: str


TEMPLATES: dict[TaskType, dict[str, str | None]] = {
    TaskType.BUG_FIX: {
        "write_tests": """
You are reproducing bug {task_id}.

Bug description: {description}
Details: {details}
Relevant files: {relevant_files}

Write a failing unit test that demonstrates the bug.
Use the `testing-anti-patterns` skill for guidance.
Commit your test with message: "test: reproduce {task_id}"

If the bug cannot be reproduced, return status DISCARDED with reason.
        """,
        "implement": """
Fix bug {task_id}. The failing test is already in place.

Make the test pass with minimal changes.
Use the `test-driven-development` skill.
Commit with message: "fix: {task_id}"
        """,
        "refactor": """
Clean up the fix for {task_id}.

- Simplify production code
- Transform TDD tests into maintainable tests
- Remove test scaffolding
- Ensure tests still pass

Use the `testing-anti-patterns` skill.
Commit with message: "refactor: clean up {task_id}"
        """,
        "review": """
Review the fix for {task_id}.

Check:
- Does the fix fully address the bug?
- Does the code follow project style?
- Are the tests meaningful?

Return SUCCESS if complete, or REJECTED with reason.
        """,
    },
    TaskType.FEATURE: {
        "write_tests": """
Implement feature {task_id}.

Feature description: {description}
Details: {details}

Write tests that specify the expected behavior.
Focus on what the feature should do, not how.
Commit with message: "test: specify {task_id}"
        """,
        "implement": """
Build feature {task_id}. Tests are in place.

Implement the minimal code to make tests pass.
Commit with message: "feat: {task_id}"
        """,
        "refactor": """
Clean up the implementation of {task_id}.

- Remove duplication
- Improve naming
- Simplify logic
- Ensure tests still pass

Commit with message: "refactor: clean up {task_id}"
        """,
        "review": """
Review feature {task_id}.

Check:
- Does it meet the requirements?
- Is the implementation clean?
- Are edge cases handled?

Return SUCCESS or REJECTED with reason.
        """,
    },
    TaskType.REFACTOR: {
        "write_tests": """
Prepare to refactor {task_id}.

Refactoring goal: {description}
Details: {details}

Write characterization tests that capture current behavior.
These tests ensure the refactoring doesn't break anything.
Commit with message: "test: characterize {task_id}"
        """,
        "implement": """
Refactor {task_id}. Characterization tests are in place.

Goal: {description}

Make changes while keeping all tests green.
Commit with message: "refactor: {task_id}"
        """,
        "refactor": None,
        "review": """
Review refactoring {task_id}.

Check:
- Is behavior preserved?
- Is the code cleaner?
- Do all tests pass?

Return SUCCESS or REJECTED with reason.
        """,
    },
}

T = TypeVar("T", bound=BaseModel)


def _print_message(message):
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                print(block.text)


async def _run_agent(
    cwd: str,
    prompt: str,
    output_schema: type[T],
    allowed_tools: list[str] | None = None,
    model: str = "opus",
) -> T | None:
    options = ClaudeAgentOptions(
        setting_sources=["project", "user"],
        allowed_tools=allowed_tools or ["Read", "Bash", "Grep", "Glob"],
        permission_mode="acceptEdits",
        cwd=cwd,
        output_format={
            "type": "json_schema",
            "schema": output_schema.model_json_schema(),
        },
        model=model,
        system_prompt={"type": "preset", "preset": "claude_code"},
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt=prompt)
        async for message in client.receive_response():
            _print_message(message)
            if isinstance(message, ResultMessage) and message.structured_output:
                return output_schema.model_validate(message.structured_output)

    return None


def _format_prompt(config: TDDConfig, phase: str) -> str:
    template = TEMPLATES[config.task_type][phase]
    if template is None:
        return ""
    return template.format(
        task_id=config.task_id,
        description=config.description,
        details=config.details,
        relevant_files=", ".join(config.relevant_files) if config.relevant_files else "none specified",
    )


def after_write_tests(state: TDDState):
    if state["status"] == "DISCARDED":
        return END
    return "implement"


def after_refactor(_state: TDDState):
    return "review"


def after_review(state: TDDState):
    if state["status"] == "SUCCESS":
        return END
    if state["review_attempts"] >= state["config"].max_review_attempts:
        return END
    return "implement"


async def write_tests_node(state: TDDState) -> dict:
    config = state["config"]
    print(f"\n{'=' * 60}")
    print(f">>> WRITE TESTS NODE ({config.task_type.value}: {config.task_id}) <<<")
    print(f"{'=' * 60}\n")

    prompt = _format_prompt(config, "write_tests")
    result = await _run_agent(
        cwd=config.worktree_path,
        prompt=prompt,
        output_schema=WriteTestsResult,
        allowed_tools=["Skill", "Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    )

    if result:
        status = "DISCARDED" if result.status == "DISCARDED" else None
        return {
            "phase": "implement" if status is None else "done",
            "test_file_path": result.test_file_path,
            "implementation_notes": result.notes,
            "status": status,
        }

    return {"phase": "done", "status": "DISCARDED", "implementation_notes": "Failed to write tests."}


async def implement_node(state: TDDState) -> dict:
    config = state["config"]
    rejection_history = state["rejection_history"]
    print(f"\n{'=' * 60}")
    print(f">>> IMPLEMENT NODE ({config.task_type.value}: {config.task_id}) <<<")
    print(f"{'=' * 60}\n")

    prompt = _format_prompt(config, "implement")
    if rejection_history:
        prompt += "\n\nPrevious review feedback:\n" + "\n".join(f"- {r}" for r in rejection_history)

    result = await _run_agent(
        cwd=config.worktree_path,
        prompt=prompt,
        output_schema=ImplementResult,
        allowed_tools=["Skill", "Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    )

    if result:
        if result.status == "DISCARDED":
            return {
                "phase": "done",
                "status": "DISCARDED",
                "implementation_notes": state["implementation_notes"] + f"\n\nImplement: {result.notes}",
            }
        return {
            "phase": "refactor",
            "implementation_notes": state["implementation_notes"] + f"\n\nImplement: {result.notes}",
        }

    return {"phase": "done", "status": "DISCARDED", "implementation_notes": "Failed to implement."}


async def refactor_node(state: TDDState) -> dict:
    config = state["config"]
    print(f"\n{'=' * 60}")
    print(f">>> REFACTOR NODE ({config.task_type.value}: {config.task_id}) <<<")
    print(f"{'=' * 60}\n")

    template = TEMPLATES[config.task_type]["refactor"]
    if template is None:
        return {"phase": "review"}

    prompt = _format_prompt(config, "refactor")
    result = await _run_agent(
        cwd=config.worktree_path,
        prompt=prompt,
        output_schema=RefactorResult,
        allowed_tools=["Skill", "Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    )

    if result:
        return {
            "phase": "review",
            "implementation_notes": state["implementation_notes"] + f"\n\nRefactor: {result.notes}",
        }

    return {"phase": "review"}


async def review_node(state: TDDState) -> dict:
    config = state["config"]
    review_attempts = state["review_attempts"]
    print(f"\n{'=' * 60}")
    print(f">>> REVIEW NODE ({config.task_type.value}: {config.task_id}, attempt {review_attempts + 1}) <<<")
    print(f"{'=' * 60}\n")

    prompt = _format_prompt(config, "review")
    result = await _run_agent(
        cwd=config.worktree_path,
        prompt=prompt,
        output_schema=ReviewResult,
        allowed_tools=["Read", "Bash", "Glob", "Grep"],
    )

    new_attempt = review_attempts + 1
    if result:
        if result.status == "SUCCESS":
            return {
                "phase": "done",
                "status": "SUCCESS",
                "review_attempts": new_attempt,
                "implementation_notes": state["implementation_notes"] + f"\n\nReview: {result.notes}",
            }
        new_history = state["rejection_history"] + [result.rejection_reason or result.notes]
        if new_attempt >= config.max_review_attempts:
            return {
                "phase": "done",
                "status": "MAX_ATTEMPTS_REACHED",
                "review_attempts": new_attempt,
                "rejection_history": new_history,
                "implementation_notes": state["implementation_notes"] + f"\n\nReview (rejected): {result.notes}",
            }
        return {
            "phase": "implement",
            "review_attempts": new_attempt,
            "rejection_history": new_history,
            "implementation_notes": state["implementation_notes"] + f"\n\nReview (rejected): {result.notes}",
        }

    return {"phase": "done", "status": "MAX_ATTEMPTS_REACHED", "review_attempts": new_attempt}


tdd_graph = StateGraph(TDDState)

tdd_graph.add_node("write_tests", write_tests_node)
tdd_graph.add_node("implement", implement_node)
tdd_graph.add_node("refactor", refactor_node)
tdd_graph.add_node("review", review_node)

tdd_graph.add_edge(START, "write_tests")
tdd_graph.add_conditional_edges("write_tests", after_write_tests)
tdd_graph.add_edge("implement", "refactor")
tdd_graph.add_conditional_edges("refactor", after_refactor)
tdd_graph.add_conditional_edges("review", after_review)


async def run_tdd_subgraph(config: TDDConfig) -> TDDResult:
    app = tdd_graph.compile()

    initial_state: TDDState = {
        "config": config,
        "phase": "write_tests",
        "test_file_path": None,
        "implementation_notes": "",
        "review_attempts": 0,
        "status": None,
        "rejection_history": [],
    }

    final_state: TDDState | None = None
    async for event in app.astream(initial_state, stream_mode="values"):
        final_state = event  # type: ignore[assignment]

    if final_state is None:
        raise RuntimeError("TDD graph produced no state")

    status = final_state["status"]
    if status is None:
        if final_state["review_attempts"] >= config.max_review_attempts:
            status = "MAX_ATTEMPTS_REACHED"
        else:
            status = "SUCCESS"

    return TDDResult(
        task_id=config.task_id,
        status=status,
        test_file_path=final_state["test_file_path"],
        notes=final_state["implementation_notes"],
        rejection_history=final_state["rejection_history"],
    )
