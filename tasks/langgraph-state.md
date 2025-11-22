# Task: Use LangGraph State for Ephemeral Data

## Objective

Move ephemeral data (bugs, fixes, entrypoints) from file I/O into LangGraph state. This eliminates redundant disk operations during workflow execution while maintaining the ability to persist state for debugging and resume.

## Current Problem

Every node in the workflow:
1. Creates a new `BugHunterNotebook` instance
2. Reads `bugs.json`, `fixes.json`, `entrypoints.json` from disk
3. Makes changes and writes back to disk

This results in ~14 file operations per workflow iteration (7 nodes × 2 loads each). The `pop_entrypoint()` operation writes to disk on every call.

## Requirements

- Move `bugs`, `fixes`, `entrypoints` into LangGraph state
- Keep markdown detail files (`bugs/BUG-*.md`) on disk
- Load existing state from disk at workflow startup (backward compatibility)
- Persist state to disk at end of workflow run

## Files to Modify

| File | Changes |
|------|---------|
| `bug_hunter.py` | Update state definition, all 7 nodes, conditional edges, main() |
| `src/code_agent/tracking.py` | Refactor BugHunterNotebook into separate concerns |

## Implementation Details

### 1. New State Definition (`bug_hunter.py`)

```python
from typing import Annotated

def merge_bugs(existing: dict[str, Bug], new: dict[str, Bug]) -> dict[str, Bug]:
    return {**existing, **new}

def merge_fixes(existing: dict[str, BugFix], new: dict[str, BugFix]) -> dict[str, BugFix]:
    return {**existing, **new}

def replace_entrypoints(existing: list[str], new: list[str] | None) -> list[str]:
    return new if new is not None else existing

class BugHunterState(TypedDict):
    messages: Annotated[list[str], lambda old, new: old + new]
    config: ProjectConfig
    bugs: Annotated[dict[str, Bug], merge_bugs]
    fixes: Annotated[dict[str, BugFix], merge_fixes]
    entrypoints: Annotated[list[str], replace_entrypoints]
```

**Why these reducers:**
- `merge_bugs/fixes`: Nodes return only changed entries; reducer merges with existing
- `replace_entrypoints`: Full list replacement since `pop` is destructive

### 2. Refactor tracking.py

Split `BugHunterNotebook` into three parts:

```python
class BugDetailsPersistence:
    """Handles only markdown detail files (stay on disk)."""

    def __init__(self, path: str):
        self.path = path

    def load_bug_details(self, bug_id: str) -> str | None:
        detail_path = os.path.join(self.path, "bugs", f"{bug_id}.md")
        if os.path.exists(detail_path):
            with open(detail_path, "r") as f:
                return f.read()
        return None

    def save_bug_details(self, bug_id: str, details: str):
        detail_path = os.path.join(self.path, "bugs", f"{bug_id}.md")
        os.makedirs(os.path.dirname(detail_path), exist_ok=True)
        with open(detail_path, "w") as f:
            f.write(details)


def load_initial_state(state_path: str) -> tuple[dict[str, Bug], dict[str, BugFix], list[str]]:
    """Load bugs, fixes, entrypoints from disk at startup."""
    bugs = {}
    fixes = {}
    entrypoints = []

    bugs_path = os.path.join(state_path, "bugs.json")
    if os.path.exists(bugs_path):
        with open(bugs_path, "r") as f:
            bugs = Bugs.model_validate_json(f.read()).bugs

    fixes_path = os.path.join(state_path, "fixes.json")
    if os.path.exists(fixes_path):
        with open(fixes_path, "r") as f:
            fixes = BugFixes.model_validate_json(f.read()).fixes

    entrypoints_path = os.path.join(state_path, "entrypoints.json")
    if os.path.exists(entrypoints_path):
        with open(entrypoints_path, "r") as f:
            entrypoints = json.loads(f.read())

    return bugs, fixes, entrypoints


def persist_state(
    state_path: str,
    bugs: dict[str, Bug],
    fixes: dict[str, BugFix],
    entrypoints: list[str],
):
    """Save state to disk at end of workflow."""
    os.makedirs(state_path, exist_ok=True)

    with open(os.path.join(state_path, "bugs.json"), "w") as f:
        f.write(Bugs(bugs=bugs).model_dump_json(indent=2))

    with open(os.path.join(state_path, "fixes.json"), "w") as f:
        f.write(BugFixes(fixes=fixes).model_dump_json(indent=2))

    with open(os.path.join(state_path, "entrypoints.json"), "w") as f:
        f.write(json.dumps(entrypoints, indent=2))
```

### 3. Update main() Function

```python
async def main():
    args = parse_args()
    project_path = args.project_path.resolve()
    project_name = args.name or project_path.name
    config = ProjectConfig(
        project_path=project_path,
        project_name=project_name,
        subdir=args.subdir,
    )

    # Load existing state from disk
    bugs, fixes, entrypoints = load_initial_state(config.state_path)

    initial_state: BugHunterState = {
        "messages": ["Starting the bug hunt"],
        "config": config,
        "bugs": bugs,
        "fixes": fixes,
        "entrypoints": entrypoints,
    }

    final_state = None
    async for event in app.astream(initial_state, stream_mode="values"):
        final_state = event
        message = event["messages"][-1]
        if hasattr(message, "content") and message.content:
            print(f"\n🤖 {message.content}")

    # Persist state at end
    if final_state:
        persist_state(
            config.state_path,
            final_state["bugs"],
            final_state["fixes"],
            final_state["entrypoints"],
        )
```

### 4. Node Update Pattern

**Before (current):**
```python
async def scout_node(state: BugHunterState) -> dict:
    config = state["config"]
    notebook = BugHunterNotebook(path=config.state_path)
    entrypoint = notebook.pop_entrypoint()
    # ... work ...
    notebook.add_or_update_bug(bug_id, bug)
    return {"messages": [...]}
```

**After:**
```python
async def scout_node(state: BugHunterState) -> dict:
    config = state["config"]
    bugs = state["bugs"]
    entrypoints = state["entrypoints"]
    details = BugDetailsPersistence(config.state_path)

    if not entrypoints:
        return {"messages": ["No entrypoints"]}

    entrypoint = entrypoints[0]
    remaining = entrypoints[1:]

    # ... work ...

    # Generate next bug ID
    next_id = max([int(b.replace('BUG-', '')) for b in bugs.keys()], default=0) + 1
    bug_id = f"BUG-{next_id:03}"

    new_bug = Bug(id=bug_id, ...)
    details.save_bug_details(bug_id, bug_details)

    return {
        "messages": [...],
        "bugs": {bug_id: new_bug},  # Only the new bug
        "entrypoints": remaining,    # Full list
    }
```

### 5. Conditional Edge Functions

Update to read from state directly:

```python
def check_state(state: BugHunterState):
    bugs = state["bugs"]
    entrypoints = state["entrypoints"]

    reviewable = [b for b in bugs.values() if b.status == "READY_FOR_REVIEW"]
    if reviewable:
        return "review_fix_node"

    prepared = [b for b in bugs.values()
                if b.status == "PREPARED_FOR_FIX" and b.reproducibility_approach == "UNIT_TEST"]
    if prepared:
        return "fix_unit_test_bug_node"

    # ... rest of conditions
```

## Nodes to Update

| Node | Line | Key Changes |
|------|------|-------------|
| `suggest_entrypoint_node` | 142 | Read entrypoints from state, return new entrypoints |
| `scout_node` | 167 | Pop from state entrypoints, return new bugs + remaining entrypoints |
| `classify_bug_candidate_node` | 220 | Read bugs from state, return updated bug |
| `reproduce_unit_test_bug_node` | 329 | Read bugs from state, return updated bug |
| `fix_unit_test_bug_node` | 388 | Read bugs/fixes from state, return updated bug + fix |
| `refactor_fix_node` | 455 | Read bugs from state (no state changes needed) |
| `review_fix_node` | 518 | Read bugs/fixes from state, return updated bug + fix |

## Testing Checklist

- [ ] Fresh start with no existing state directory
- [ ] Resume with existing `bugs.json`, `fixes.json`, `entrypoints.json`
- [ ] State flows correctly through conditional edges
- [ ] Markdown detail files still written correctly
- [ ] State persisted correctly at end of workflow
- [ ] Workflow can be interrupted and resumed from persisted state

## Notes

- Keep `BugHunterNotebook` class temporarily for the `clear()` method used in CLI
- The `clear()` method can be updated to work with files directly or removed if not needed
- Consider adding try/finally around workflow execution to ensure state is persisted even on error
