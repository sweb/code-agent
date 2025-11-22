# Add SQLite Checkpointing

Enable resume-from-failure using LangGraph's SQLite checkpoint system.

## Context

The bug hunter agent runs a multi-step LangGraph workflow. Currently, if the process crashes or is interrupted, all progress is lost. This feature adds checkpointing so interrupted runs can be resumed.

## Requirements

1. **Interactive resume**: When starting, detect incomplete runs and prompt: `Incomplete run detected. Resume? [y/n]`
2. **Keep JSON persistence**: SQLite checkpoints are for resume capability; existing JSON files (`bugs.json`, `fixes.json`) stay for human-readable export
3. **DB location**: `{state_path}/checkpoints.db` (e.g., `state/my-app/checkpoints.db`)

## Implementation

### Step 1: Add Dependency

**File**: `pyproject.toml`

```toml
dependencies = [
    "claude-agent-sdk>=0.1.9",
    "langgraph>=1.0.3",
    "langgraph-checkpoint-sqlite>=3.0.0",
]
```

Run `uv sync` after updating.

### Step 2: Create Checkpoint Module

**New file**: `src/code_agent/checkpointing.py`

```python
import os
from datetime import datetime

THREAD_ID_FILE = "current_thread.txt"
CHECKPOINT_DB = "checkpoints.db"


def get_checkpoint_db_path(state_path: str) -> str:
    return os.path.join(state_path, CHECKPOINT_DB)


def generate_thread_id() -> str:
    return f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def save_thread_id(state_path: str, thread_id: str) -> None:
    os.makedirs(state_path, exist_ok=True)
    path = os.path.join(state_path, THREAD_ID_FILE)
    with open(path, "w") as f:
        f.write(thread_id)


def load_thread_id(state_path: str) -> str | None:
    path = os.path.join(state_path, THREAD_ID_FILE)
    if os.path.exists(path):
        with open(path, "r") as f:
            return f.read().strip()
    return None


def clear_thread_id(state_path: str) -> None:
    path = os.path.join(state_path, THREAD_ID_FILE)
    if os.path.exists(path):
        os.remove(path)


async def check_for_incomplete_run(checkpointer, state_path: str) -> tuple[bool, str | None]:
    thread_id = load_thread_id(state_path)
    if not thread_id:
        return False, None

    config = {"configurable": {"thread_id": thread_id}}
    state = await checkpointer.aget(config)
    if state is not None:
        return True, thread_id
    return False, None


def prompt_resume() -> bool:
    while True:
        response = input("Incomplete run detected. Resume? [y/n]: ").strip().lower()
        if response in ("y", "yes"):
            return True
        if response in ("n", "no"):
            return False
        print("Please enter 'y' or 'n'.")
```

### Step 3: Modify bug_hunter.py

**File**: `bug_hunter.py`

#### 3a. Add imports

```python
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from code_agent.checkpointing import (
    get_checkpoint_db_path,
    generate_thread_id,
    save_thread_id,
    load_thread_id,
    clear_thread_id,
    check_for_incomplete_run,
    prompt_resume,
)
```

#### 3b. Add CLI flags

In `parse_args()`, add mutually exclusive resume flags:

```python
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
```

#### 3c. Remove module-level compile

Delete line 738:
```python
app = workflow.compile()  # DELETE THIS LINE
```

#### 3d. Restructure main()

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
            async for event in app.astream(initial_state, run_config, stream_mode="values"):
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
```

### Step 4: Add Tests

**New file**: `tests/test_checkpointing.py`

```python
import os
import tempfile

from code_agent.checkpointing import (
    get_checkpoint_db_path,
    generate_thread_id,
    save_thread_id,
    load_thread_id,
    clear_thread_id,
)


class TestThreadIdManagement:
    def test_generate_thread_id_returns_formatted_string(self):
        thread_id = generate_thread_id()
        assert thread_id.startswith("run-")
        assert len(thread_id) > 4

    def test_save_and_load_thread_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            save_thread_id(tmpdir, "test-thread-123")
            loaded = load_thread_id(tmpdir)
            assert loaded == "test-thread-123"

    def test_load_returns_none_when_no_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            loaded = load_thread_id(tmpdir)
            assert loaded is None

    def test_clear_removes_thread_id_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            save_thread_id(tmpdir, "test-thread")
            clear_thread_id(tmpdir)
            path = os.path.join(tmpdir, "current_thread.txt")
            assert not os.path.exists(path)

    def test_clear_handles_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            clear_thread_id(tmpdir)


class TestDatabasePath:
    def test_get_checkpoint_db_path(self):
        path = get_checkpoint_db_path("/some/state/path")
        assert path == "/some/state/path/checkpoints.db"
```

## Key Behaviors

1. **New run**: Generate thread ID, save to `current_thread.txt`, run graph with initial state
2. **Interrupted run**: `current_thread.txt` persists with checkpoint data in SQLite
3. **Resume**: Load existing thread ID, pass `None` as input to `astream()` - LangGraph restores state from checkpoint
4. **Completed run**: Clear `current_thread.txt` to mark run as finished

## Testing Checklist

- [ ] Fresh run creates `current_thread.txt` and `checkpoints.db`
- [ ] Interrupting (Ctrl+C) leaves `current_thread.txt` intact
- [ ] Restarting detects incomplete run and prompts
- [ ] `--resume` flag skips prompt and resumes
- [ ] `--no-resume` flag skips prompt and starts fresh
- [ ] Completed run removes `current_thread.txt`
- [ ] JSON files (`bugs.json`, `fixes.json`) still exported after run
