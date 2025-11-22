# Tool Elimination Refactoring

## Objective

Replace MCP tools in `tracking.py` with structured outputs (`output_format`) and prompt injection. This simplifies the architecture by removing the tool layer between agents and state persistence.

## Current State

### Files Involved
- `bug_hunter.py` - LangGraph workflow with 7 nodes
- `src/code_agent/tracking.py` - `BugHunterNotebook` class + 8 MCP tools

### Current Flow
```
Agent → MCP Tool → BugHunterNotebook → File System
```

### MCP Tools to Eliminate

| Tool | Type | Used In |
|------|------|---------|
| `load_bugs` | Read | `scout_node` |
| `load_bug_details` | Read | `scout_node`, `classify_bug_candidate_node` |
| `create_bug` | Write | `scout_node` |
| `classify_bug` | Write | (unused - classification done via `output_format` already) |
| `add_entrypoints` | Write | `suggest_entrypoint_node` |
| `change_status` | Write | `reproduce_unit_test_bug_node`, `fix_unit_test_bug_node`, `review_fix_node` |
| `create_fix` | Write | `fix_unit_test_bug_node` |
| `update_fix` | Write | `review_fix_node` |

## Target State

### New Flow
```
Node prepares context → Agent explores → Structured output → Node persists
```

### Key Changes

1. **Read operations**: Inject data into prompt instead of tool calls
2. **Write operations**: Use `output_format` with Pydantic schemas
3. **Persistence**: Node functions handle persistence after agent completes

## Implementation

### Step 1: Define Output Schemas

Create Pydantic models for each node's output in `bug_hunter.py`:

```python
class SuggestEntrypointsResult(BaseModel):
    entrypoints: list[str]
    reasoning: str

class ScoutResult(BaseModel):
    bugs: list[Bug]
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

class ReviewResult(BaseModel):
    status: Literal["SOLVED", "PREPARED_FOR_FIX"]
    rejection_reason: str | None
    notes: str
```

### Step 2: Create Agent Helper

Extract common agent setup into a reusable function:

```python
from typing import TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

async def run_agent(
    config: ProjectConfig,
    prompt: str,
    output_schema: type[T],
    cwd: str | None = None,
    allowed_tools: list[str] | None = None,
    model: str = "sonnet",
) -> T:
    options = ClaudeAgentOptions(
        setting_sources=["project"],
        allowed_tools=allowed_tools or ["Read", "Bash", "Grep", "Glob"],
        permission_mode="acceptEdits",
        cwd=cwd or str(config.project_path),
        output_format={"type": "json_schema", "schema": output_schema.model_json_schema()},
        model=model,
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt=prompt)
        async for message in client.receive_response():
            if hasattr(message, "structured_output"):
                return output_schema.model_validate(message.structured_output)

    raise RuntimeError("No structured output received")
```

### Step 3: Refactor Nodes

Convert each node to use the helper. Example for `scout_node`:

**Before:**
```python
def scout_node(state: BugHunterState):
    config = state["config"]

    async def _func():
        cwd = os.getcwd()
        options = ClaudeAgentOptions(
            mcp_servers={"bug_hunter_tools": custom_server},
            allowed_tools=[
                "Read", "Bash",
                "mcp__bug_hunter_tools__load_bugs",
                "mcp__bug_hunter_tools__create_bug",
                "mcp__bug_hunter_tools__load_bug_details",
            ],
            # ... 10 more lines of setup
        )
        # ... 30 more lines

    return {"messages": asyncio.run(_func())}
```

**After:**
```python
async def scout_node(state: BugHunterState) -> dict:
    config = state["config"]
    notebook = BugHunterNotebook(path=config.state_path)
    entrypoint = notebook.pop_entrypoint()

    result = await run_agent(
        config=config,
        prompt=f"""
            Explore this codebase starting from @{entrypoint}.
            Find potential bugs: crashes, incorrect behavior, missing config validation, performance issues.

            Known bugs (do not duplicate):
            {notebook.bugs.model_dump_json()}

            Return 1-3 HIGH severity bugs found.
        """,
        output_schema=ScoutResult,
    )

    for bug in result.bugs:
        notebook.add_or_update_bug(bug.id, bug)

    return {"messages": [result.exploration_summary]}
```

### Step 4: Clean Up tracking.py

Remove all `@tool` decorated functions and the `custom_server`. Keep only:
- Pydantic models (`Bug`, `Bugs`, `BugFix`, `BugFixes`)
- `BugHunterNotebook` class

The file shrinks from ~380 lines to ~140 lines.

### Step 5: Update Imports

In `bug_hunter.py`, remove:
```python
from code_agent.tracking import BugHunterNotebook, custom_server
```

Replace with:
```python
from code_agent.tracking import BugHunterNotebook, Bug, BugFix
```

## Node-by-Node Refactoring Guide

### suggest_entrypoint_node
- Output: `SuggestEntrypointsResult`
- Post-process: `notebook.add_entrypoints(result.entrypoints)`

### scout_node
- Input context: `notebook.bugs.model_dump_json()`, entrypoint file
- Output: `ScoutResult`
- Post-process: Loop through `result.bugs`, call `notebook.add_or_update_bug()`

### classify_bug_candidate_node
- Already uses `output_format` - just remove MCP server setup
- Input context: Bug JSON + details markdown
- Output: `ClassifyResult`
- Post-process: Update bug with classification fields

### reproduce_unit_test_bug_node
- Needs `Write` tool (creates test files)
- Input context: Bug JSON + details markdown
- Output: `ReproduceResult`
- Post-process: `notebook.add_or_update_bug()` with new status

### fix_unit_test_bug_node
- Needs `Write`, `Edit` tools (modifies code)
- Input context: Bug JSON + details + potential fix if rejected
- Output: `FixResult`
- Post-process: Update bug status, create fix record

### refactor_fix_node
- Needs `Write`, `Edit` tools
- No structured output needed (just runs and commits)
- Can keep as-is or add simple confirmation output

### review_fix_node
- Read-only exploration
- Input context: Bug JSON + details + git diff
- Output: `ReviewResult`
- Post-process: Update bug status, update fix record

## Testing Strategy

1. Run the full workflow on a test project before/after refactoring
2. Verify state files (`bugs.json`, `fixes.json`) contain equivalent data
3. Check that worktree commits are created correctly

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Agent doesn't return valid structured output | Add retry logic or fallback in `run_agent()` |
| Bug ID generation changes | Keep ID generation logic in `BugHunterNotebook`, pass to agent in prompt |
| Loss of intermediate state on crash | Accept for now; address in checkpoints refactoring |

## Definition of Done

- [x] All MCP tools removed from `tracking.py`
- [x] `custom_server` removed
- [x] All nodes use `run_agent()` helper or similar pattern
- [x] Nodes are async (no `asyncio.run()` wrappers)
- [ ] Workflow completes successfully on test project
- [x] Code passes linting (`ruff`)

## Implementation Notes

### Changes Made

**tracking.py** (379 → 137 lines):
- Removed all 8 `@tool` decorated functions
- Removed `custom_server` creation
- Removed `claude_agent_sdk` imports (`create_sdk_mcp_server`, `tool`)
- Kept: Pydantic models (`Bug`, `Bugs`, `BugFix`, `BugFixes`) and `BugHunterNotebook` class

**bug_hunter.py**:
- Added 7 Pydantic output schemas at module level
- Added `run_agent()` helper function with optional `output_schema` parameter
- Converted all 7 nodes from sync (with `asyncio.run()` wrapper) to native async functions
- Bug ID generation moved from MCP tool to `scout_node` directly
- Bug details now injected into prompts instead of using `load_bug_details` tool
- Removed `ResultMessage` import (unused after refactoring)

### Design Decisions

1. **`run_agent()` returns `None` instead of raising on missing output**: Allows nodes to handle missing structured output gracefully with fallback messages. The original plan's `raise RuntimeError` was changed to `return None`.

2. **Added `ScoutBug` intermediate model**: The agent returns `ScoutBug` objects (without `id` and `status` fields) which are then converted to full `Bug` objects in the node. This separates agent output from persistence concerns.

3. **Added `RefactorResult` schema**: Even though the plan said refactor_fix_node could skip structured output, adding it provides consistency and captures refactoring notes.

4. **Bug details persisted incrementally**: Each node appends a new section to the bug's markdown file (e.g., `## Classification Summary`, `## Reproduction Notes`, `## Fix Notes`, `## Review Notes`) preserving the full history.

5. **`output_format` made optional in `run_agent()`**: Some future use cases might not need structured output, so the parameter is optional and defaults to `None`.

### Potential Improvements

- Add retry logic to `run_agent()` for when structured output parsing fails
- Add type stubs or use `cast()` to silence Pylance warnings about `structured_output` attribute
- Consider extracting node-specific prompts to separate template files for easier maintenance
