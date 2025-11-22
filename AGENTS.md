# Agents Guide

## Overview

Bug Hunter is an autonomous agent that explores codebases to find bugs, reproduces them via unit tests, implements fixes, and reviews solutions. Built on Claude Agent SDK and LangGraph.

## Tech Stack

- **Python 3.11+** with `uv` package manager
- **Claude Agent SDK** - AI agent orchestration
- **LangGraph** - Workflow graph with SQLite checkpointing
- **Pytest** - Testing

## Project Structure

```
bug_hunter.py          # Main entry point - workflow nodes and orchestration
src/code_agent/
├── tracking.py        # State persistence and bug tracking models
├── checkpointing.py   # Thread ID and checkpoint management
├── gitlab_utils.py    # Git worktree utilities
└── cli.py             # CLI commands
tests/                 # Pytest test suite
state/                 # Runtime state (gitignored)
```

## Setup

```bash
uv sync
```

## Running

```bash
uv run python bug_hunter.py <project_path> [--name <name>] [--subdir <subdir>]
uv run python bug_hunter.py <project_path> --resume  # Resume interrupted run
```

## Testing

```bash
uv run pytest
```

## Workflow Nodes

1. **Suggest Entrypoints** → 2. **Scout** (find bugs) → 3. **Classify** → 4. **Reproduce** (failing test) → 5. **Fix** → 6. **Refactor** → 7. **Review**

## Key Patterns

- State persisted to `state/<project>/` as JSON files
- SQLite checkpointing for resumable runs
- Git worktrees isolate each bug fix
- Structured JSON outputs via Claude SDK schemas
- Async throughout using `anyio`
