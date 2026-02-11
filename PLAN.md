# Plan: `swe_env` -- Software Engineering Environment

**Status**: In Progress
**Created**: 2026-02-11
**Branch**: `swe`

## How to Use This Document

This plan is the primary guide for implementing `swe_env`. It is designed for **context-free sessions** -- each new Claude Code session should read this file first to understand the current state and what to do next.

### Starting a New Session

1. **Read this file** (`PLAN.md`) first.
2. **Check the Progress Tracker** below to see which stages are done.
3. **Find the next "Not Started" or "In Progress" stage** and work on it.
4. **Read the stage's "Study First" files** before writing any code.
5. **Run the stage's "Definition of Done" checks** to verify completion.
6. **Update the Progress Tracker** and add notes in the "Session Log" at the bottom.

### Rules

- **Do not modify any files under `src/openenv/`** -- treat OpenEnv as a read-only library.
- **All new code goes under `envs/swe_env/`** and tests under `tests/envs/`.
- **Each stage should pass its tests before moving to the next.**
- **If you deviate from the plan**, note what changed and why in the Session Log.
- **No dead code.** At the end of every stage, all code must be working and importable. Never leave broken scaffolding, stale imports, or references to deleted files. If something isn't needed yet, remove or stub it cleanly (a one-line docstring-only module is fine).
- **No commented-out code or section headers.** Do not add commented-out section headers, divider lines (e.g. `# ---------------------------------------------------------------------------`), or commented-out future code. This applies to both production code AND test files. Use class names and test method names to organize — they are self-documenting.
- **Run tests with:** `PYTHONPATH=src:envs uv run python -m pytest <test_file> -v`

## Progress Tracker

| Stage | Status | Description |
|-------|--------|-------------|
| Stage 1 | Done | Foundation: Workspace, ToolModule protocol, SWEEnvironment skeleton |
| Stage 2 | Not Started | Bash tool module |
| Stage 3 | Not Started | Git tool module |
| Stage 4 | Not Started | Python tool module |
| Stage 5 | Not Started | App, Client, Dockerfile, integration tests |

---

## Context

OpenEnv has individual environments for Python execution (`coding_env`), Git operations (`git_env`), and various other tasks -- but no environment that combines these into a persistent workspace where bash, git, and Python tools coexist. The OpenHands SDK (`software-agent-sdk/`) demonstrates this pattern well: a unified workspace with modular tools (terminal, file_editor, grep, glob) sharing a common execution context.

This plan creates `swe_env`, a new OpenEnv environment that provides a sandboxed, persistent workspace with modular tools exposed via MCP. Initial scope: **bash, git, Python**. The tool module design supports adding more tools (file_editor, grep, glob, test runner) later without changing the core architecture.

## Architecture Overview

### How MCP Tool Calling Works

Agents never see MCP protocol details. There are two interaction modes:

1. **Tool-calling mode (most common):** The agent sends `CallToolAction(tool_name="bash", arguments={"command": "ls"})` and gets back a `CallToolObservation`. This is identical in shape to LLM tool-calling schema. `MCPEnvironment.step()` routes it through FastMCP transparently.

2. **CodeAct mode:** `MCPEnvironment.get_callables()` extracts registered tools as plain Python callables. An agent writes `result = bash(command="ls")` directly.

MCP is an implementation detail giving us automatic tool discovery, standard dispatch, and modularity.

### Workspace Lifecycle

The `HTTPEnvServer` creates one `SWEEnvironment` instance per WebSocket session (via the factory pattern). Within that session:

```
WebSocket connect → factory creates SWEEnvironment (Workspace dir created eagerly)
  → client sends "reset" → Workspace.reset() clears dir contents (episode 1)
  → client sends "step" × N (workspace persists across steps)
  → client sends "reset" → Workspace.reset() clears dir contents (episode 2)
  → ...
  → WebSocket disconnect → env.close() → Workspace.close() removes dir
```

The Workspace uses `tempfile.TemporaryDirectory` so cleanup happens even if `close()` is missed (via `__del__`). Each concurrent session gets its own independent Workspace.

### ToolModule Pattern

Each tool category is a `ToolModule` that:
1. Receives a `get_workspace: Callable[[], Path]` in its constructor
2. Registers MCP tools with a shared `FastMCP` server via `register(mcp)`
3. Supports `reset()` (episode boundary) and `cleanup()` (session end)

To add a tool module to the environment, instantiate it and append to the `tool_modules` list in `SWEEnvironment.with_default_tools()`.

## Key Design Decisions

1. **Base class: `MCPEnvironment`** -- gives us `ListToolsAction`/`CallToolAction` routing, `get_callables()` for CodeAct mode, and tool name validation for free.
2. **`ToolModule` protocol** -- each tool category (bash, git, python) is an independent module that registers its tools with a shared `FastMCP` server. Adding a new tool = one new file + one line in the factory.
3. **`get_workspace` callable pattern** -- tool modules receive a `() -> Path` callable instead of a static `Path`, so they always reference the current workspace.
4. **Bash via `subprocess.run`** (stateless per-command) -- simpler than a persistent shell session. Each command runs in the workspace directory.
5. **Git via local subprocess** (not Gitea) -- self-contained, no external service dependency.
6. **Python via existing `PyExecutor`** -- reuses `src/openenv/core/tools/local_python_executor.py` for persistent namespace execution.

## Stage 1: Foundation (DONE)

### What Was Built

| File | Purpose |
|------|---------|
| `envs/swe_env/server/workspace.py` | `Workspace` class -- temp dir via `TemporaryDirectory`, `reset()` clears contents, `close()` deletes dir |
| `envs/swe_env/server/tool_module.py` | `ToolModule` -- `runtime_checkable` Protocol with `register(mcp)`, `reset()`, `cleanup()` |
| `envs/swe_env/models.py` | `SWEState(State)` -- adds `workspace_path: str` and `available_tools: list[str]` |
| `envs/swe_env/server/environment.py` | `SWEEnvironment(MCPEnvironment)` -- constructor takes `workspace` + `tool_modules`, `with_default_tools()` factory |
| `envs/swe_env/server/tools/__init__.py` | Empty package for tool modules |
| `envs/swe_env/server/__init__.py` | Exports `SWEEnvironment` |
| `envs/swe_env/__init__.py` | Exports `SWEState` |
| `envs/swe_env/server/app.py` | Stub (wired up in Stage 5) |
| `envs/swe_env/client.py` | Stub (wired up in Stage 5) |
| `tests/envs/test_swe_env_stage1.py` | 21 tests covering Workspace, ToolModule protocol, SWEState, SWEEnvironment skeleton |

### Key Implementation Details

**Workspace** (`server/workspace.py`):
- Creates temp dir eagerly in `__init__` via `tempfile.TemporaryDirectory(prefix="swe_workspace_")`
- `reset()` clears contents (iterates children, removes each) but keeps the directory
- `close()` calls `self._tmpdir.cleanup()` to remove the directory
- `path` property returns `self._path` (a `Path` object); `is_active` checks `.exists()`

**SWEEnvironment** (`server/environment.py`):
- Constructor takes `workspace: Workspace` and `tool_modules: list[ToolModule]`
- Creates `FastMCP("swe_env")`, calls `module.register(mcp)` for each module, passes `mcp` to `super().__init__(mcp)`
- `reset()` calls `self._workspace.reset()`, then `module.reset()` for each module, builds `SWEState`
- `step()` increments `self._state.step_count`, delegates to `super().step()`
- `close()` calls `module.cleanup()` for each module, `self._workspace.close()`, `super().close()`
- `with_default_tools()` classmethod: creates `Workspace()`, builds `get_workspace = lambda: workspace.path`, instantiates tool modules (currently empty list), returns `cls(workspace=workspace, tool_modules=tool_modules)`

**How to add a new tool module (Stages 2-4):**
1. Create `envs/swe_env/server/tools/<name>_tool.py` implementing `ToolModule`
2. In `SWEEnvironment.with_default_tools()`, import and append to `tool_modules` list
3. Write tests in `tests/envs/test_swe_env_stage<N>.py`

### Verification

```bash
PYTHONPATH=src:envs uv run python -m pytest tests/envs/test_swe_env_stage1.py -v
# 21 passed
```

---

## Stage 2: Bash Tool

**File to create:** `envs/swe_env/server/tools/bash_tool.py`

**Study first:**
- `envs/swe_env/server/tool_module.py` -- the ToolModule protocol to implement
- `envs/swe_env/server/environment.py` -- how `with_default_tools()` wires modules in
- `software-agent-sdk/openhands-tools/openhands/tools/terminal/definition.py` -- OpenHands terminal tool for inspiration (but we use simpler subprocess.run)

### `BashToolModule`

Constructor takes `get_workspace: Callable[[], Path]` and `default_timeout: int = 120`.

Registers one MCP tool:
- **`bash(command: str, timeout: int) -> dict`** -- runs `subprocess.run(["bash", "-c", command], cwd=workspace)`, returns `{stdout, stderr, exit_code}`. Handles `TimeoutExpired` (exit_code=124).

`reset()` and `cleanup()` are no-ops (no internal state).

After creating the module, update `SWEEnvironment.with_default_tools()` to include it.

### Tests (`tests/envs/test_swe_env_stage2.py`)
- Basic command: `echo hello` returns stdout="hello\n", exit_code=0
- Failed command: `false` returns exit_code=1
- Timeout: long-running command returns exit_code=124
- Stderr: invalid command captures stderr
- Working directory: `pwd` returns workspace path
- File creation: `touch foo.txt` creates file in workspace
- Full integration: `SWEEnvironment` with just `BashToolModule`, list_tools returns `["bash"]`, CallToolAction works

### Definition of Done
- [ ] `BashToolModule` exists and satisfies `ToolModule` protocol
- [ ] `SWEEnvironment.with_default_tools()` includes `BashToolModule`
- [ ] `PYTHONPATH=src:envs uv run python -m pytest tests/envs/test_swe_env_stage2.py -v` passes
- [ ] Stage 1 tests still pass: `PYTHONPATH=src:envs uv run python -m pytest tests/envs/test_swe_env_stage1.py -v`
- [ ] Update Progress Tracker: Stage 2 -> "Done"

---

## Stage 3: Git Tool

**File to create:** `envs/swe_env/server/tools/git_tool.py`

**Study first:**
- Stage 1 code (must be complete)
- `envs/git_env/server/git_task_environment.py` -- existing git env for patterns (but we use local subprocess, not Gitea)

### `GitToolModule`

Registers two MCP tools:
- **`git(command: str, working_dir: str = "", timeout: int = 60) -> dict`** -- runs `git <command>` in workspace (or `workspace/working_dir`). Returns `{stdout, stderr, exit_code}`.
- **`git_clone(repo_url: str, target_dir: str = "", branch: str = "", depth: int = 0) -> dict`** -- structured clone with parameters. Longer default timeout (300s).

After creating the module, update `SWEEnvironment.with_default_tools()` to include it.

### Tests (`tests/envs/test_swe_env_stage3.py`)
- `git init` + `git status` in workspace
- `git add` + `git commit` flow
- `working_dir` parameter navigates into subdirectory
- Nonexistent `working_dir` returns error
- `git_clone` with branch/depth parameters
- Full integration: list_tools returns `["bash", "git", "git_clone"]`

### Definition of Done
- [ ] `GitToolModule` exists and satisfies `ToolModule` protocol
- [ ] `SWEEnvironment.with_default_tools()` includes `GitToolModule`
- [ ] `PYTHONPATH=src:envs uv run python -m pytest tests/envs/test_swe_env_stage3.py -v` passes
- [ ] Previous stage tests still pass
- [ ] Update Progress Tracker: Stage 3 -> "Done"

---

## Stage 4: Python Tool

**File to create:** `envs/swe_env/server/tools/python_tool.py`

**Study first:**
- Stage 1 code (must be complete)
- `src/openenv/core/tools/local_python_executor.py` -- PyExecutor wrapper (constructor, `run()` method, `CodeExecResult` return type)
- `envs/coding_env/server/python_codeact_env.py` -- how coding_env uses PyExecutor (reset creates fresh instance)
- `src/openenv/core/env_server/types.py` -- `CodeExecResult` dataclass (has `.stdout`, `.stderr`, `.exit_code`)

### `PythonToolModule`

Constructor takes `get_workspace` and `additional_imports: list[str]`.

Registers one MCP tool:
- **`python(code: str) -> dict`** -- executes via `PyExecutor.run(code)`, returns `{stdout, stderr, exit_code}`. Executor is created lazily on first call (so workspace exists).

`reset()`: sets `self._executor = None` (next call creates fresh executor).
`cleanup()`: sets `self._executor = None`.

After creating the module, update `SWEEnvironment.with_default_tools()` to include it.

### Tests (`tests/envs/test_swe_env_stage4.py`)
- Basic execution: `print("hello")` returns stdout
- Persistent namespace: define `x = 5` then `print(x)` in separate calls
- Error handling: syntax errors return stderr + exit_code=1
- Reset clears state: after reset, previously defined variables are gone
- Full integration: all three tools listed, Python variables persist across steps within episode

### Definition of Done
- [ ] `PythonToolModule` exists and satisfies `ToolModule` protocol
- [ ] `SWEEnvironment.with_default_tools()` includes `PythonToolModule`
- [ ] `PYTHONPATH=src:envs uv run python -m pytest tests/envs/test_swe_env_stage4.py -v` passes
- [ ] Previous stage tests still pass
- [ ] Update Progress Tracker: Stage 4 -> "Done"

### Note on dependency
`PyExecutor` depends on `smolagents`. If not installed, tests should skip gracefully with `pytest.importorskip("smolagents")`.

---

## Stage 5: App, Client, Dockerfile, Integration

**Files:** `server/app.py`, `client.py`, `__init__.py`, `openenv.yaml`, `pyproject.toml`, `server/Dockerfile`

### `server/app.py`
```python
app = create_app(
    SWEEnvironment.with_default_tools,
    CallToolAction, CallToolObservation,
    env_name="swe_env",
)
```

### `client.py`
```python
class SWEEnv(MCPToolClient):
    pass  # MCPToolClient provides list_tools, call_tool, reset
```

### `server/Dockerfile`
Follows echo_env pattern. Adds `git` and `bash` to runtime image via `apt-get install`.

### `pyproject.toml`
Dependencies: `openenv-core[core]`, `fastapi`, `pydantic`, `uvicorn`, `requests`, `smolagents`.

### End-to-end tests (`tests/envs/test_swe_env_integration.py`)
- Full workflow: reset -> list_tools -> bash (create file) -> git init -> git add -> git commit -> python (read file) -> verify cross-tool state sharing
- Workspace isolation: files from one episode gone after reset
- Multiple episodes: sequential reset/work/reset cycles
- Concurrent instances: two environments in parallel, verify no cross-contamination
- CodeAct mode: `env.get_callables()` returns bash/git/python functions

### Definition of Done
- [ ] `server/app.py`, `client.py`, `__init__.py`, `openenv.yaml`, `pyproject.toml`, `server/Dockerfile` all exist
- [ ] `PYTHONPATH=src:envs uv run python -m pytest tests/envs/test_swe_env_integration.py -v` passes
- [ ] `uv run ruff format envs/swe_env/ --check && uv run ruff check envs/swe_env/` passes
- [ ] All previous stage tests still pass
- [ ] Update Progress Tracker: Stage 5 -> "Done"

---

## Sandboxing & Concurrency

Concurrent `swe_env` instances must not interfere with each other. Isolation is provided at three layers, each progressively stronger:

### Layer 1: Instance-Level Isolation (Within a Single Server Process)

OpenEnv's `HTTPEnvServer` (`src/openenv/core/env_server/http_server.py`) uses a **factory pattern**: `create_app()` receives a callable (class or factory function), and each WebSocket session calls that factory to create a **new, independent `SWEEnvironment` instance**. This means:

- Each session gets its own `Workspace` object, which creates a **unique temp directory** via `tempfile.TemporaryDirectory`.
- Each session gets its own `PyExecutor` instance with a **separate Python namespace**.
- Each session gets its own `FastMCP` server with its own tool closures bound to its own workspace path.
- Tool calls within a session are serialized by a **per-session `ThreadPoolExecutor(max_workers=1)`**, preventing race conditions within a single agent's workspace.
- `SWEEnvironment` sets `SUPPORTS_CONCURRENT_SESSIONS = True` to opt into multi-session support.

### Layer 2: Docker Container Isolation (Production)

In production, each `swe_env` server runs in its own **Docker container**. The deployment model is **one container per environment server**, with `max_concurrent_envs` controlling how many agent sessions share a single container.

Docker container orchestration is handled by OpenEnv's existing container runtime and is outside our scope -- we just provide the Dockerfile.

### Concurrency Test Plan (Stage 5)

Integration tests will verify isolation by running two `SWEEnvironment` instances in parallel:
- Both create files via bash -- verify each only sees its own files.
- Both init git repos -- verify independent git histories.
- Both define Python variables -- verify no namespace leakage.
- One resets while the other is mid-episode -- verify no cross-contamination.

## File Structure (current state after Stage 1)

```
envs/swe_env/
├── __init__.py                  # exports SWEState
├── models.py                    # SWEState(State)
├── client.py                    # stub (Stage 5)
├── openenv.yaml                 # scaffolded
├── pyproject.toml               # scaffolded
├── .dockerignore                # scaffolded
├── README.md                    # scaffolded
└── server/
    ├── __init__.py              # exports SWEEnvironment
    ├── app.py                   # stub (Stage 5)
    ├── environment.py           # SWEEnvironment(MCPEnvironment)
    ├── workspace.py             # Workspace (TemporaryDirectory wrapper)
    ├── tool_module.py           # ToolModule Protocol
    ├── tools/
    │   ├── __init__.py
    │   ├── bash_tool.py         # Stage 2 (not yet created)
    │   ├── git_tool.py          # Stage 3 (not yet created)
    │   └── python_tool.py       # Stage 4 (not yet created)
    ├── Dockerfile               # scaffolded
    └── requirements.txt         # scaffolded

tests/envs/
└── test_swe_env_stage1.py       # 21 tests, all passing
```

## Verification Commands

```bash
# Run tests for a specific stage
PYTHONPATH=src:envs uv run python -m pytest tests/envs/test_swe_env_stage1.py -v

# Run all swe_env tests
PYTHONPATH=src:envs uv run python -m pytest tests/envs/test_swe_env*.py -v

# Lint
uv run ruff format envs/swe_env/ --check && uv run ruff check envs/swe_env/

# Full test suite (ensure no regressions)
PYTHONPATH=src:envs uv run python -m pytest tests/ -v --tb=short
```

## Critical Files (Read-Only References)

| File | Role |
|------|------|
| `src/openenv/core/env_server/mcp_environment.py` | Base class for MCPEnvironment |
| `src/openenv/core/env_server/types.py` | Action, Observation, State base types |
| `src/openenv/core/env_server/mcp_types.py` | CallToolAction, ListToolsAction, CallToolObservation |
| `src/openenv/core/tools/local_python_executor.py` | PyExecutor to reuse |
| `envs/echo_env/` | Reference MCPEnvironment implementation |
| `envs/coding_env/` | Reference for Python execution pattern |
| `envs/git_env/` | Reference for Git operations pattern |

## Key Imports Quick Reference

```python
from openenv.core.env_server.mcp_environment import MCPEnvironment
from openenv.core.env_server.types import Action, Observation, State
from openenv.core.env_server.mcp_types import (
    CallToolAction, CallToolObservation, ListToolsAction, ListToolsObservation,
)
from openenv.core.env_server.http_server import create_app
from openenv.core.mcp_client import MCPToolClient
from openenv.core.tools.local_python_executor import PyExecutor
from fastmcp import FastMCP

from swe_env.models import SWEState
from swe_env.server.workspace import Workspace
from swe_env.server.tool_module import ToolModule
from swe_env.server.environment import SWEEnvironment
```

## Future Extensions (Post-MVP)

These tools can be added later following the same `ToolModule` pattern:
- **FileEditorToolModule**: Structured file read/write/edit (view, create, str_replace, insert, undo)
- **GrepToolModule**: Content search across workspace files
- **GlobToolModule**: Pattern-based file discovery
- **TestRunnerToolModule**: Run pytest/unittest with structured results
- **Persistent shell**: Upgrade bash from subprocess.run to persistent tmux/subprocess session
- **Task-based reset**: Pre-configured repo states for multi-task RL training (like git_env)

---

## Session Log

| Date | Session | What was done | Notes |
|------|---------|---------------|-------|
| 2026-02-11 | 1 | Initial plan created | Explored OpenEnv + OpenHands SDK, designed architecture |
| 2026-02-11 | 2 | Stage 1 complete (21 tests passing) | Workspace simplified from create/destroy cycle to eager `TemporaryDirectory` with `reset()` clearing contents. Cleaned up scaffolded dead code (`app.py`, `client.py` stubbed; deleted `swe_env_environment.py`). Established code style rules (no dead code, no comment headers). |
