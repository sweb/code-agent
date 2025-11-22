# Bug Hunter

An autonomous bug hunting agent built with Claude Agent SDK and LangGraph. It explores codebases to find potential bugs, reproduces them via unit tests, implements fixes, and reviews the solutions.

## How It Works

The agent runs through a workflow of specialized nodes:
1. **Suggest Entrypoints** - Identifies files to start exploring
2. **Scout** - Explores code from entrypoints to find potential bugs
3. **Classify** - Determines how to reproduce each bug (unit test, integration test, manual)
4. **Reproduce** - Creates failing unit tests to confirm the bug
5. **Fix** - Implements code changes to make tests pass
6. **Refactor** - Cleans up both production code and tests
7. **Review** - Validates the fix addresses the bug correctly

State is persisted to disk and workflow progress is checkpointed, allowing runs to be resumed.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Usage

Run the bug hunter on a project:

```bash
uv run python bug_hunter.py <project_path> [--name <project_name>] [--subdir <subdir>]
```

Options:
- `--name` - Override project name (defaults to directory name)
- `--subdir` - Subdirectory for monorepo setups
- `--resume` - Resume incomplete run without prompting
- `--no-resume` - Start fresh run without prompting

Clear tracked bugs and entrypoints:

```bash
uv run code-agent clear --state-dir <state_dir>
```
