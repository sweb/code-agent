# TDD Subgraph Generalization

**Status:** Completed
**Task ID:** subgraph-generalization

## Summary

Extract the reproduce → fix → refactor → review sequence from `bug_hunter.py` into a reusable TDD subgraph that can be parameterized for different task types (bug fixing, feature development, refactoring).

## Motivation

The current workflow has 4 hardcoded nodes for bug fixing via unit tests:
- `reproduce_unit_test_bug_node`
- `fix_unit_test_bug_node`
- `refactor_fix_node`
- `review_fix_node`

This is a general TDD pattern that applies to other task types:
- **Feature development:** spec test → implement → refactor → review
- **Refactoring:** characterization test → refactor → verify → review

Extracting this as a reusable subgraph reduces duplication and enables new workflows.

## Design

### Core Structure

The TDD subgraph is a 4-phase workflow with an internal review loop:

```
┌─────────────────────────────────────────────────────────┐
│                    TDD Subgraph                         │
│                                                         │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────┐ │
│  │  Write   │ → │Implement │ → │ Refactor │ → │Review│ │
│  │  Tests   │   │          │   │ (skip?)  │   │      │ │
│  └────┬─────┘   └──────────┘   └──────────┘   └──┬───┘ │
│       │                                          │     │
│       ↓ (DISCARDED)               (REJECTED) ←───┘     │
│      END                              ↓                │
│                               back to Implement        │
│                               (max N attempts)         │
└─────────────────────────────────────────────────────────┘
```

### Task Types

| Phase | Bug Fixing | Feature Dev | Refactoring |
|-------|-----------|-------------|-------------|
| Write Tests | Failing repro test | Spec/behavior test | Characterization test |
| Implement | Fix the bug | Build the feature | Refactor code |
| Refactor | Clean up fix | Clean up impl | Skip (already refactoring) |
| Review | Verify fix | Verify feature | Verify behavior preserved |

### Configuration

The subgraph uses built-in prompt templates per task type. Callers pass a simple config:

```python
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
```

### Built-in Templates

Templates are stored in the subgraph module, keyed by task type:

```python
TEMPLATES = {
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
        "refactor": None,  # Skip - already refactoring
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
```

### Subgraph State

The subgraph has isolated state, separate from the parent:

```python
class TDDState(TypedDict):
    config: TDDConfig
    phase: Literal["write_tests", "implement", "refactor", "review", "done"]

    test_file_path: str | None
    implementation_notes: str
    review_attempts: int

    status: Literal["SUCCESS", "DISCARDED", "MAX_ATTEMPTS_REACHED"] | None
    rejection_history: list[str]
```

### Result Model

What the subgraph returns to the parent:

```python
class TDDResult(BaseModel):
    task_id: str
    status: Literal["SUCCESS", "DISCARDED", "MAX_ATTEMPTS_REACHED"]
    test_file_path: str | None
    notes: str
    rejection_history: list[str]
```

### Subgraph Definition

```python
from langgraph.graph import START, END, StateGraph

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

def after_write_tests(state: TDDState):
    if state["status"] == "DISCARDED":
        return END
    return "implement"

def after_refactor(state: TDDState):
    return "review"

def after_review(state: TDDState):
    if state["status"] == "SUCCESS":
        return END
    if state["review_attempts"] >= state["config"].max_review_attempts:
        return END  # status = MAX_ATTEMPTS_REACHED
    return "implement"  # Loop back
```

### Entry Point

```python
async def run_tdd_subgraph(config: TDDConfig) -> TDDResult:
    """Run the TDD subgraph and return the result."""
    app = tdd_graph.compile()

    initial_state = {
        "config": config,
        "phase": "write_tests",
        "test_file_path": None,
        "implementation_notes": "",
        "review_attempts": 0,
        "status": None,
        "rejection_history": [],
    }

    final_state = None
    async for event in app.astream(initial_state, stream_mode="values"):
        final_state = event

    return TDDResult(
        task_id=config.task_id,
        status=final_state["status"],
        test_file_path=final_state["test_file_path"],
        notes=final_state["implementation_notes"],
        rejection_history=final_state["rejection_history"],
    )
```

## File Structure

**New file:**
```
src/code_agent/
├── tdd_subgraph.py    # NEW
├── tracking.py
├── checkpointing.py
├── gitlab_utils.py
└── cli.py
```

**Contents of tdd_subgraph.py:**
- `TaskType` enum
- `TDDConfig` dataclass
- `TDDResult` model
- `TDDState` TypedDict
- `TEMPLATES` dict
- Node functions: `write_tests_node`, `implement_node`, `refactor_node`, `review_node`
- Routing functions: `after_write_tests`, `after_refactor`, `after_review`
- `tdd_graph` StateGraph
- `run_tdd_subgraph()` entry point

## Integration with bug_hunter.py

### Remove

Delete these 4 nodes and their routing logic:
- `reproduce_unit_test_bug_node` (lines 403-477)
- `fix_unit_test_bug_node` (lines 479-563)
- `refactor_fix_node` (lines 566-632)
- `review_fix_node` (lines 635-726)
- `review_requires_fix` routing function (lines 387-400)

### Add

Single node that invokes the subgraph:

```python
from code_agent.tdd_subgraph import run_tdd_subgraph, TDDConfig, TaskType

async def tdd_bug_fix_node(state: BugHunterState) -> dict:
    """Invokes TDD subgraph for bug fixing."""
    config = state["config"]
    bugs = state["bugs"]
    details = BugDetailsPersistence(config.state_path)

    # Find bug ready for TDD
    bug = next(
        b for b in bugs.values()
        if b.status == "IN_ANALYSIS" and b.reproducibility_approach == "UNIT_TEST"
    )

    # Create worktree
    from code_agent.gitlab_utils import create_worktree_from_origin
    worktree_dir = config.worktree_dir(bug.id)
    create_worktree_from_origin(worktree_path=worktree_dir, cwd=str(config.project_path))

    # Build config
    tdd_config = TDDConfig(
        task_id=bug.id,
        task_type=TaskType.BUG_FIX,
        worktree_path=config.worktree_cwd(bug.id),
        description=bug.short_description,
        details=details.load_bug_details(bug.id) or "",
        relevant_files=bug.relevant_files,
    )

    # Run subgraph
    result = await run_tdd_subgraph(tdd_config)

    # Map result to bug status
    status_map = {
        "SUCCESS": "SOLVED",
        "DISCARDED": "DISCARDED",
        "MAX_ATTEMPTS_REACHED": "NEEDS_MANUAL_REVIEW",
    }

    updated_bug = Bug(
        id=bug.id,
        short_description=bug.short_description,
        severity=bug.severity,
        status=status_map[result.status],
        relevant_files=bug.relevant_files,
        reproducibility_approach=bug.reproducibility_approach,
        reproducibility_chance=bug.reproducibility_chance,
        created_at=bug.created_at,
    )

    # Persist notes
    notes = f"\n\n## TDD Result\n\nStatus: {result.status}\n{result.notes}"
    if result.rejection_history:
        notes += f"\n\nRejection history:\n" + "\n".join(f"- {r}" for r in result.rejection_history)
    details.save_bug_details(bug.id, (details.load_bug_details(bug.id) or "") + notes)

    return {
        "messages": [f"{bug.id} TDD complete: {result.status}"],
        "bugs": {bug.id: updated_bug},
    }
```

### Simplify Graph Edges

Before:
```python
workflow.add_conditional_edges("reproduce_unit_test_bug_node", check_state)
workflow.add_edge("fix_unit_test_bug_node", "refactor_fix_node")
workflow.add_edge("refactor_fix_node", "review_fix_node")
workflow.add_conditional_edges("review_fix_node", review_requires_fix)
```

After:
```python
workflow.add_conditional_edges("tdd_bug_fix_node", check_state)
```

## Implementation Steps

1. Create `src/code_agent/tdd_subgraph.py` with all components
2. Write tests for the subgraph in isolation
3. Update `bug_hunter.py` to use the new subgraph
4. Remove old node implementations
5. Update `check_state` routing to use new node name
6. Test end-to-end with a real bug fix

## Future Extensions

Once this is in place, adding new workflows becomes easy:

```python
# Feature development workflow
async def tdd_feature_node(state: FeatureDevState) -> dict:
    config = TDDConfig(
        task_id=feature.id,
        task_type=TaskType.FEATURE,
        ...
    )
    result = await run_tdd_subgraph(config)
    ...

# Refactoring workflow
async def tdd_refactor_node(state: RefactorState) -> dict:
    config = TDDConfig(
        task_id=refactor.id,
        task_type=TaskType.REFACTOR,
        ...
    )
    result = await run_tdd_subgraph(config)
    ...
```
