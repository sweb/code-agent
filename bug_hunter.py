import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, TypeVar

import anyio
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
)
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import START, StateGraph
from pydantic import BaseModel
from typing_extensions import TypedDict

from code_agent.checkpointing import (
    check_for_incomplete_run,
    clear_thread_id,
    generate_thread_id,
    get_checkpoint_db_path,
    prompt_resume,
    save_thread_id,
)
from code_agent.tracking import (
    Bug,
    BugDetailsPersistence,
    BugFix,
    load_initial_state,
    persist_state,
)


def merge_bugs(existing: dict[str, Bug], new: dict[str, Bug]) -> dict[str, Bug]:
    return {**existing, **new}


def merge_fixes(
    existing: dict[str, BugFix], new: dict[str, BugFix]
) -> dict[str, BugFix]:
    return {**existing, **new}


def replace_entrypoints(existing: list[str], new: list[str] | None) -> list[str]:
    return new if new is not None else existing


T = TypeVar("T", bound=BaseModel)


class SuggestEntrypointsResult(BaseModel):
    entrypoints: list[str]
    reasoning: str


class ScoutBug(BaseModel):
    short_description: str
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    relevant_files: list[str]
    details: str


class ScoutResult(BaseModel):
    bugs: list[ScoutBug]
    exploration_summary: str


class ClassifyResult(BaseModel):
    reproducibility_approach: Literal["UNIT_TEST", "MANUAL", "INTEGRATION_TEST"]
    reproducibility_chance: Literal["EASY", "MEDIUM", "HARD"]
    reasoning: str


class ReproduceResult(BaseModel):
    status: Literal["PREPARED_FOR_FIX", "DISCARDED"]
    test_file_path: str | None
    notes: str


class FixResult(BaseModel):
    status: Literal["READY_FOR_REVIEW", "DISCARDED"]
    fix_description: str
    notes: str


class RefactorResult(BaseModel):
    refactored: bool
    notes: str


class ReviewResult(BaseModel):
    status: Literal["SOLVED", "PREPARED_FOR_FIX"]
    rejection_reason: str | None
    notes: str


async def run_agent(
    config: "ProjectConfig",
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


@dataclass
class ProjectConfig:
    project_path: Path
    project_name: str
    subdir: str = ""

    @property
    def state_path(self) -> str:
        return f"state/{self.project_name}"

    @property
    def worktree_base(self) -> str:
        return f"/tmp/bug_hunter/{self.project_name}"

    def worktree_dir(self, bug_id: str) -> str:
        return f"{self.worktree_base}/{bug_id.lower()}"

    def worktree_cwd(self, bug_id: str) -> str:
        base = self.worktree_dir(bug_id)
        if self.subdir:
            return f"{base}/{self.subdir}"
        return base


class BugHunterState(TypedDict):
    messages: Annotated[list[str], lambda old, new: old + new]
    config: ProjectConfig
    bugs: Annotated[dict[str, Bug], merge_bugs]
    fixes: Annotated[dict[str, BugFix], merge_fixes]
    entrypoints: Annotated[list[str], replace_entrypoints]


def _print_message(message):
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                print(block.text)


async def suggest_entrypoint_node(state: BugHunterState) -> dict:
    print("\n" + "=" * 60)
    print(">>> SUGGEST ENTRYPOINT NODE <<<")
    print("=" * 60 + "\n")

    config = state["config"]
    entrypoints = state["entrypoints"]

    if entrypoints:
        return {"messages": ["Entrypoints already exist."]}

    result = await run_agent(
        config=config,
        prompt="""
            You are a bug hunting agent. Your goal is to find potential bugs in the codebase.
            Suggest a couple of entrypoint files that are good candidates to search for potential bugs.
            Return the file paths and your reasoning.
        """,
        output_schema=SuggestEntrypointsResult,
        allowed_tools=["Read", "Bash", "Glob", "Grep"],
    )

    if result:
        return {
            "messages": [result.reasoning],
            "entrypoints": result.entrypoints,
        }

    return {"messages": ["Failed to suggest entrypoints."]}


async def scout_node(state: BugHunterState) -> dict:
    print("\n" + "=" * 60)
    print(">>> SCOUT NODE <<<")
    print("=" * 60 + "\n")

    config = state["config"]
    bugs = state["bugs"]
    entrypoints = state["entrypoints"]
    details = BugDetailsPersistence(config.state_path)

    if not entrypoints:
        return {"messages": ["No entrypoints to scout."]}

    entrypoint = entrypoints[0]
    remaining = entrypoints[1:]

    from code_agent.tracking import Bugs

    bugs_json = Bugs(bugs=bugs).model_dump_json()

    result = await run_agent(
        config=config,
        prompt=f"""
            Explore this codebase to find ways to:
            * cause an unhandled exception or crash
            * cause incorrect behavior that is not expected
            * missing configuration that is not detected during start up but will crash once used
            * performance bottlenecks that can be easily fixed

            Your starting point is the file: @{entrypoint}
            You can branch out to other files as needed to better understand the code, but focus on finding issues in this particular file.

            Here are the already tracked bugs (do not duplicate):
            {bugs_json}

            Explanation of severity levels:
            * HIGH: Bugs that can lead to crashes, data loss, security vulnerabilities, or major functionality failures.
            * MEDIUM: Bugs that cause significant inconvenience, incorrect results, or partial loss of functionality.
            * LOW: Minor bugs that do not significantly impact usability or functionality.

            Return 1-3 HIGH severity bugs found. For each bug provide:
            - short_description: A brief description of the bug
            - severity: HIGH, MEDIUM, or LOW
            - relevant_files: List of file paths relevant to the bug
            - details: Full context and steps to reproduce
        """,
        output_schema=ScoutResult,
        allowed_tools=["Read", "Bash", "Glob", "Grep"],
    )

    if result:
        new_bugs: dict[str, Bug] = {}
        for scout_bug in result.bugs:
            next_id = (
                max([int(b.replace("BUG-", "")) for b in bugs.keys()], default=0)
                + 1
                + len(new_bugs)
            )
            bug_id = f"BUG-{next_id:03}"
            bug = Bug(
                id=bug_id,
                short_description=scout_bug.short_description,
                severity=scout_bug.severity,
                status="POTENTIAL",
                relevant_files=scout_bug.relevant_files,
            )
            new_bugs[bug_id] = bug
            details.save_bug_details(bug_id=bug.id, details=scout_bug.details)
        return {
            "messages": [result.exploration_summary],
            "bugs": new_bugs,
            "entrypoints": remaining,
        }

    return {
        "messages": ["No bugs found."],
        "entrypoints": remaining,
    }


async def classify_bug_candidate_node(state: BugHunterState) -> dict:
    print("\n" + "=" * 60)
    print(">>> CLASSIFY BUG CANDIDATE NODE <<<")
    print("=" * 60 + "\n")

    config = state["config"]
    bugs = state["bugs"]
    details = BugDetailsPersistence(config.state_path)

    potential_bugs = [
        b for b in bugs.values() if b.status == "POTENTIAL" and b.severity == "HIGH"
    ]
    if not potential_bugs:
        return {"messages": ["No potential high severity bugs found."]}

    chosen_bug = potential_bugs[0]
    bug_details = details.load_bug_details(chosen_bug.id) or ""

    result = await run_agent(
        config=config,
        prompt=f"""
            Here is a potential bug to classify:
            {chosen_bug.model_dump_json()}

            Details:
            {bug_details}

            Look at the bug above and classify it in the following two dimensions:
            1. Reproducibility Approach: Choose one of 'UNIT_TEST', 'MANUAL', 'INTEGRATION_TEST' depending on how easy it is to reproduce the bug.
            2. Reproducibility Chance: Choose one of 'EASY', 'MEDIUM', 'HARD' depending on how likely it is that a developer can reproduce the bug given the provided information.

            A unit test is preferred as it can be verified without having to reproduce an environment. However, sometimes a bug only manifests beyond a single unit of code.
            In that case, an integration test is preferred. Manual reproduction is the least preferred as it requires the most effort from a developer.

            Provide your reasoning for the classification.
        """,
        output_schema=ClassifyResult,
        allowed_tools=["Read", "Bash", "Glob", "Grep"],
        model="haiku",
    )

    if result:
        updated_bug = Bug(
            id=chosen_bug.id,
            short_description=chosen_bug.short_description,
            severity=chosen_bug.severity,
            status="IN_ANALYSIS",
            relevant_files=chosen_bug.relevant_files,
            reproducibility_approach=result.reproducibility_approach,
            reproducibility_chance=result.reproducibility_chance,
            created_at=chosen_bug.created_at,
        )

        classification_summary = f"\n\n## Classification Summary\n\n{result.reasoning}"
        details.save_bug_details(chosen_bug.id, bug_details + classification_summary)

        return {
            "messages": [
                f"{chosen_bug.id} classified as {result.reproducibility_approach}/{result.reproducibility_chance}"
            ],
            "bugs": {chosen_bug.id: updated_bug},
        }

    return {"messages": ["Failed to classify bug."]}


def check_state(state: BugHunterState):
    bugs = state["bugs"]
    entrypoints = state["entrypoints"]

    reviewable_bugs = [b for b in bugs.values() if b.status == "READY_FOR_REVIEW"]
    if reviewable_bugs:
        return "review_fix_node"

    reproduced_bugs = [
        b
        for b in bugs.values()
        if b.status == "PREPARED_FOR_FIX" and b.reproducibility_approach == "UNIT_TEST"
    ]
    if reproduced_bugs:
        return "fix_unit_test_bug_node"

    unit_test_bugs = [
        b
        for b in bugs.values()
        if b.status == "IN_ANALYSIS" and b.reproducibility_approach == "UNIT_TEST"
    ]
    if unit_test_bugs:
        return "reproduce_unit_test_bug_node"

    high_severity_bugs = [
        b for b in bugs.values() if b.status == "POTENTIAL" and b.severity == "HIGH"
    ]
    if high_severity_bugs:
        return "classify_bug_candidate_node"

    if entrypoints:
        return "scout_node"

    return "suggest_entrypoint_node"


def review_requires_fix(state: BugHunterState):
    bugs = state["bugs"]
    fixes = state["fixes"]

    prepared_bugs = [
        b
        for b in bugs.values()
        if b.status == "PREPARED_FOR_FIX" and b.reproducibility_approach == "UNIT_TEST"
    ]
    bug_fixes = [fixes.get(b.id) for b in prepared_bugs]
    rejected_fixes = [f for f in bug_fixes if f and f.status == "REJECTED"]
    if rejected_fixes:
        return "fix_unit_test_bug_node"
    return "END"


async def reproduce_unit_test_bug_node(state: BugHunterState) -> dict:
    print("\n" + "=" * 60)
    print(">>> REPRODUCE UNIT TEST BUG NODE <<<")
    print("=" * 60 + "\n")

    config = state["config"]
    bugs = state["bugs"]
    details = BugDetailsPersistence(config.state_path)

    unit_test_bugs = [
        b
        for b in bugs.values()
        if b.status == "IN_ANALYSIS" and b.reproducibility_approach == "UNIT_TEST"
    ]
    bug = unit_test_bugs[0]
    bug_details = details.load_bug_details(bug.id) or ""
    worktree_dir = config.worktree_dir(bug.id)

    from code_agent.gitlab_utils import create_worktree_from_origin

    create_worktree_from_origin(
        worktree_path=worktree_dir, cwd=str(config.project_path)
    )
    worktree_cwd = config.worktree_cwd(bug.id)

    result = await run_agent(
        config=config,
        prompt=f"""
            You are a bug reproduction agent. Your goal is to reproduce bugs by writing unit tests.
            You have the following bug to reproduce:
            {bug.model_dump_json()}

            Details:
            {bug_details}

            You are on a git worktree created specifically for this bug at {worktree_dir}.

            The unit tests should fail before the bug is fixed. Use the `testing-anti-patterns` skill to write good unit tests.

            Once you have successfully reproduced the bug:
            1. Commit your changes with a commit message that clearly indicates this is a reproduction of bug {bug.id}
            2. Return status as 'PREPARED_FOR_FIX' with the test file path and notes

            If the bug cannot be reproduced without a lot of setup or very complex steps:
            1. Return status as 'DISCARDED' with the reason in notes
        """,
        output_schema=ReproduceResult,
        cwd=worktree_cwd,
        allowed_tools=["Skill", "Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    )

    if result:
        updated_bug = Bug(
            id=bug.id,
            short_description=bug.short_description,
            severity=bug.severity,
            status=result.status,
            relevant_files=bug.relevant_files,
            reproducibility_approach=bug.reproducibility_approach,
            reproducibility_chance=bug.reproducibility_chance,
            created_at=bug.created_at,
        )

        reproduction_notes = f"\n\n## Reproduction Notes\n\n{result.notes}"
        if result.test_file_path:
            reproduction_notes += f"\nTest file: {result.test_file_path}"
        details.save_bug_details(bug.id, bug_details + reproduction_notes)

        return {
            "messages": [f"{bug.id} reproduction: {result.status}"],
            "bugs": {bug.id: updated_bug},
        }

    return {"messages": ["Failed to reproduce bug."]}


async def fix_unit_test_bug_node(state: BugHunterState) -> dict:
    print("\n" + "=" * 60)
    print(">>> FIX UNIT TEST BUG NODE <<<")
    print("=" * 60 + "\n")

    config = state["config"]
    bugs = state["bugs"]
    fixes = state["fixes"]
    details = BugDetailsPersistence(config.state_path)

    prepared_bugs = [
        b
        for b in bugs.values()
        if b.status == "PREPARED_FOR_FIX" and b.reproducibility_approach == "UNIT_TEST"
    ]
    bug = prepared_bugs[0]
    bug_details = details.load_bug_details(bug.id) or ""
    potential_fix = fixes.get(bug.id)
    worktree_dir = config.worktree_dir(bug.id)
    worktree_cwd = config.worktree_cwd(bug.id)

    existing_fix_info = ""
    if potential_fix and potential_fix.status == "REJECTED":
        existing_fix_info = (
            f"\n\nPrevious fix was rejected:\nReason: {potential_fix.rejection_reason}"
        )

    result = await run_agent(
        config=config,
        prompt=f"""
            You are a bug fixing agent. Your goal is to fix bugs that have been reproduced via a unit test.
            You have the following bug to fix:
            {bug.model_dump_json()}

            Details:
            {bug_details}{existing_fix_info}

            You are on a git worktree created specifically for this bug at {worktree_dir}.

            Unit tests that reproduce it have been added to the codebase. Your goal is to fix the bug by modifying the code so that these tests pass.

            Once you have a first working solution, try to simplify the code changes as much as possible.
            Then refactor the unit tests to fit the style of the project - describe the situation being tested, not bug IDs.

            Use the `test-driven-development` and `testing-anti-patterns` skills.

            Once you have successfully fixed the bug:
            1. Commit your changes with a commit message indicating this is a fix for {bug.id}
            2. Return status as 'READY_FOR_REVIEW' with a fix description and notes

            If you cannot fix the bug or determine it's not actually a bug:
            1. Return status as 'DISCARDED' with the reason in notes
        """,
        output_schema=FixResult,
        cwd=worktree_cwd,
        allowed_tools=["Skill", "Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    )

    if result:
        updated_bug = Bug(
            id=bug.id,
            short_description=bug.short_description,
            severity=bug.severity,
            status=result.status,
            relevant_files=bug.relevant_files,
            reproducibility_approach=bug.reproducibility_approach,
            reproducibility_chance=bug.reproducibility_chance,
            created_at=bug.created_at,
        )

        fix_notes = f"\n\n## Fix Notes\n\n{result.notes}\n\nFix description: {result.fix_description}"
        details.save_bug_details(bug.id, bug_details + fix_notes)

        state_update: dict = {
            "messages": [f"{bug.id} fix: {result.status}"],
            "bugs": {bug.id: updated_bug},
        }

        if result.status == "READY_FOR_REVIEW":
            fix = BugFix(bug_id=bug.id, status="IN_REVIEW")
            state_update["fixes"] = {bug.id: fix}

        return state_update

    return {"messages": ["Failed to fix bug."]}


async def refactor_fix_node(state: BugHunterState) -> dict:
    print("\n" + "=" * 60)
    print(">>> REFACTOR FIX NODE <<<")
    print("=" * 60 + "\n")

    config = state["config"]
    bugs = state["bugs"]
    details = BugDetailsPersistence(config.state_path)

    reviewable_bugs = [
        b
        for b in bugs.values()
        if b.status == "READY_FOR_REVIEW" and b.reproducibility_approach == "UNIT_TEST"
    ]
    bug = reviewable_bugs[0]
    bug_details = details.load_bug_details(bug.id) or ""
    worktree_dir = config.worktree_dir(bug.id)
    worktree_cwd = config.worktree_cwd(bug.id)

    result = await run_agent(
        config=config,
        prompt=f"""
            You are a code refactoring agent. Your goal is to simplify and clean up code that was written during bug fixing.

            Bug context:
            {bug.model_dump_json()}

            Details:
            {bug_details}

            You are on a git worktree at {worktree_dir} that contains the fix.

            Your tasks:

            1. SIMPLIFY PRODUCTION CODE:
               - Remove any unnecessary complexity introduced during the fix
               - Consolidate duplicate logic
               - Improve naming for clarity
               - Remove dead code paths
               - Keep changes minimal and focused

            2. TRANSFORM TESTS FROM TDD TO MAINTAINABLE:
               The unit tests were written in TDD style to drive the implementation.
               Now that the code works, transform them into maintainable tests:
               - Remove test scaffolding that was only needed to drive development
               - Consolidate redundant test cases that test the same behavior
               - Focus tests on documenting behavior, not implementation details
               - Remove tests that only verify mock behavior (anti-pattern)
               - Ensure tests describe the "what" not the "how"

            3. ENSURE TESTS STILL PASS:
               Run the tests after refactoring to ensure nothing broke.

            Use the `testing-anti-patterns` skill for guidance on good test practices.
            Commit your refactoring changes with a clear commit message.
        """,
        output_schema=RefactorResult,
        cwd=worktree_cwd,
        allowed_tools=["Skill", "Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    )

    if result:
        refactor_notes = f"\n\n## Refactor Notes\n\n{result.notes}"
        details.save_bug_details(bug.id, bug_details + refactor_notes)
        return {"messages": [f"{bug.id} refactored: {result.refactored}"]}

    return {"messages": ["Refactoring completed."]}


async def review_fix_node(state: BugHunterState) -> dict:
    print("\n" + "=" * 60)
    print(">>> REVIEW FIX NODE <<<")
    print("=" * 60 + "\n")

    config = state["config"]
    bugs = state["bugs"]
    fixes = state["fixes"]
    details = BugDetailsPersistence(config.state_path)

    reviewable_bugs = [
        b
        for b in bugs.values()
        if b.status == "READY_FOR_REVIEW" and b.reproducibility_approach == "UNIT_TEST"
    ]
    bug = reviewable_bugs[0]
    bug_details = details.load_bug_details(bug.id) or ""
    worktree_dir = config.worktree_dir(bug.id)

    result = await run_agent(
        config=config,
        prompt=f"""
            The following bug was first reproduced and a fix for it was implemented:
            {bug.model_dump_json()}

            Details:
            {bug_details}

            You are on a git worktree created specifically for this bug at {worktree_dir} that contains the reproduction and the fix.
            Review the code changes carefully. Use the git diff command to see the changes made.
            The commit messages state what commits introduced the reproduction and what commits introduced the fix.

            Check if the fix is addressing the whole bug or whether this requires further changes.
            In addition, check if the code changes are following best practices and the style of the project.

            If further changes are required:
            - Return status as 'PREPARED_FOR_FIX' with rejection_reason explaining what needs to change

            If the bug is fully fixed:
            - Return status as 'SOLVED' with notes about the review

            Focus solely on this bug and do not branch out to other issues.
        """,
        output_schema=ReviewResult,
        cwd=worktree_dir,
        allowed_tools=["Read", "Bash", "Glob", "Grep"],
    )

    if result:
        review_notes = f"\n\n## Review Notes\n\n{result.notes}"
        details.save_bug_details(bug.id, bug_details + review_notes)

        updated_bug = Bug(
            id=bug.id,
            short_description=bug.short_description,
            severity=bug.severity,
            status=result.status,
            relevant_files=bug.relevant_files,
            reproducibility_approach=bug.reproducibility_approach,
            reproducibility_chance=bug.reproducibility_chance,
            created_at=bug.created_at,
        )

        state_update: dict = {
            "messages": [f"{bug.id} review: {result.status}"],
            "bugs": {bug.id: updated_bug},
        }

        existing_fix = fixes.get(bug.id)
        if existing_fix:
            if result.status == "SOLVED":
                updated_fix = BugFix(
                    bug_id=existing_fix.bug_id,
                    status="FINISHED",
                    rejection_reason=existing_fix.rejection_reason,
                    created_at=existing_fix.created_at,
                    manual_adjustments=existing_fix.manual_adjustments,
                )
            else:
                updated_fix = BugFix(
                    bug_id=existing_fix.bug_id,
                    status="REJECTED",
                    rejection_reason=result.rejection_reason,
                    created_at=existing_fix.created_at,
                    manual_adjustments=existing_fix.manual_adjustments,
                )
            state_update["fixes"] = {bug.id: updated_fix}

        return state_update

    return {"messages": ["Review completed."]}


workflow = StateGraph(BugHunterState)

workflow.add_node(suggest_entrypoint_node)
workflow.add_node(scout_node)
workflow.add_node(classify_bug_candidate_node)
workflow.add_node(reproduce_unit_test_bug_node)
workflow.add_node(fix_unit_test_bug_node)
workflow.add_node(refactor_fix_node)
workflow.add_node(review_fix_node)

workflow.add_conditional_edges(START, check_state)
workflow.add_conditional_edges("suggest_entrypoint_node", check_state)
workflow.add_edge("scout_node", "classify_bug_candidate_node")
workflow.add_conditional_edges("classify_bug_candidate_node", check_state)
workflow.add_conditional_edges("reproduce_unit_test_bug_node", check_state)
workflow.add_edge("fix_unit_test_bug_node", "refactor_fix_node")
workflow.add_edge("refactor_fix_node", "review_fix_node")
workflow.add_conditional_edges("review_fix_node", review_requires_fix)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bug Hunter - Find and fix bugs in codebases"
    )
    parser.add_argument(
        "project_path",
        type=Path,
        help="Path to the project to hunt bugs in",
    )
    parser.add_argument(
        "--name",
        type=str,
        help="Project name (defaults to directory name)",
    )
    parser.add_argument(
        "--subdir",
        type=str,
        default="",
        help="Subdirectory within the repo for monorepo setups (e.g., 'apps/myapp')",
    )
    resume_group = parser.add_mutually_exclusive_group()
    resume_group.add_argument(
        "--resume",
        action="store_true",
        help="Resume incomplete run without prompting",
    )
    resume_group.add_argument(
        "--no-resume",
        action="store_true",
        help="Start fresh run without prompting",
    )
    return parser.parse_args()


async def main():
    args = parse_args()
    project_path = args.project_path.resolve()
    project_name = args.name or project_path.name
    config = ProjectConfig(
        project_path=project_path,
        project_name=project_name,
        subdir=args.subdir,
    )

    print(f"Bug hunting in: {config.project_path}")
    print(f"State stored at: {config.state_path}")

    db_path = get_checkpoint_db_path(config.state_path)
    os.makedirs(config.state_path, exist_ok=True)

    async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
        app = workflow.compile(checkpointer=checkpointer)

        has_incomplete, existing_thread_id = await check_for_incomplete_run(
            checkpointer, config.state_path
        )

        if has_incomplete and existing_thread_id:
            if args.resume:
                should_resume = True
            elif args.no_resume:
                should_resume = False
            else:
                should_resume = prompt_resume()

            if should_resume:
                thread_id = existing_thread_id
                initial_state = None
            else:
                thread_id = generate_thread_id()
                bugs, fixes, entrypoints = load_initial_state(config.state_path)
                initial_state = {
                    "messages": ["Starting the bug hunt"],
                    "config": config,
                    "bugs": bugs,
                    "fixes": fixes,
                    "entrypoints": entrypoints,
                }
        else:
            thread_id = generate_thread_id()
            bugs, fixes, entrypoints = load_initial_state(config.state_path)
            initial_state = {
                "messages": ["Starting the bug hunt"],
                "config": config,
                "bugs": bugs,
                "fixes": fixes,
                "entrypoints": entrypoints,
            }

        save_thread_id(config.state_path, thread_id)
        run_config = {"configurable": {"thread_id": thread_id}}

        final_state = None
        run_completed = False
        try:
            async for event in app.astream(
                initial_state, run_config, stream_mode="values"
            ):
                final_state = event
                message = event["messages"][-1]
                if hasattr(message, "content") and message.content:
                    print(f"\n{message.content}")
            run_completed = True
        finally:
            if final_state:
                persist_state(
                    config.state_path,
                    final_state["bugs"],
                    final_state["fixes"],
                    final_state["entrypoints"],
                )
            if run_completed:
                clear_thread_id(config.state_path)


if __name__ == "__main__":
    try:
        anyio.run(main)
    except KeyboardInterrupt:
        pass
