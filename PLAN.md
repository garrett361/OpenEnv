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

## Progress Tracker

| Stage | Status | Description |
|-------|--------|-------------|
| Stage 1 | Not Started | Foundation: Workspace, ToolModule protocol, SWEEnvironment skeleton |
| Stage 2 | Not Started | Bash tool module |
| Stage 3 | Not Started | Git tool module |
| Stage 4 | Not Started | Python tool module |
| Stage 5 | Not Started | App, Client, Dockerfile, integration tests |

---

## Context

OpenEnv has individual environments for Python execution (`coding_env`), Git operations (`git_env`), and various other tasks -- but no environment that combines these into a persistent workspace where bash, git, and Python tools coexist. The OpenHands SDK (`software-agent-sdk/`) demonstrates this pattern well: a unified workspace with modular tools (terminal, file_editor, grep, glob) sharing a common execution context.

This plan creates `swe_env`, a new OpenEnv environment that provides a sandboxed, persistent workspace with modular tools exposed via MCP. Initial scope: **bash, git, Python**. The tool module design supports adding more tools (file_editor, grep, glob, test runner) later without changing the core architecture.

## Key Design Decisions

1. **Base class: `MCPEnvironment`** -- gives us `ListToolsAction`/`CallToolAction` routing, `get_callables()` for CodeAct mode, and tool name validation for free.
2. **`ToolModule` protocol** -- each tool category (bash, git, python) is an independent module that registers its tools with a shared `FastMCP` server. Adding a new tool = one new file + one line in the constructor.
3. **`get_workspace` callable pattern** -- tool modules receive a `() -> Path` callable instead of a static `Path`, so they always reference the *current* workspace even after `reset()` recreates it.
4. **Bash via `subprocess.run`** (stateless per-command) -- simpler than a persistent shell session. Each command runs in the workspace directory. Upgrade path to persistent shell exists but isn't needed initially.
5. **Git via local subprocess** (not Gitea) -- self-contained, no external service dependency. Agent runs `git` commands directly in the workspace.
6. **Python via existing `PyExecutor`** -- reuses `src/openenv/core/tools/local_python_executor.py` (wraps `smolagents.LocalPythonExecutor`) for persistent namespace execution.

## Sandboxing & Concurrency

Concurrent `swe_env` instances must not interfere with each other. Isolation is provided at three layers, each progressively stronger:

### Layer 1: Instance-Level Isolation (Within a Single Server Process)

OpenEnv's `HTTPEnvServer` (`src/openenv/core/env_server/http_server.py`) uses a **factory pattern**: `create_app()` receives a callable (class or factory function), and each WebSocket session calls that factory to create a **new, independent `SWEEnvironment` instance**. This means:

- Each session gets its own `Workspace` object, which creates a **unique temp directory** via `tempfile.mkdtemp()` (e.g., `/tmp/swe_workspace_a1b2c3/` vs `/tmp/swe_workspace_d4e5f6/`).
- Each session gets its own `PyExecutor` instance with a **separate Python namespace**.
- Each session gets its own `FastMCP` server with its own tool closures bound to its own workspace path.
- Tool calls within a session are serialized by a **per-session `ThreadPoolExecutor(max_workers=1)`**, preventing race conditions within a single agent's workspace.
- `SWEEnvironment` sets `SUPPORTS_CONCURRENT_SESSIONS = True` to opt into multi-session support. The server's `max_concurrent_envs` parameter caps how many sessions can run simultaneously.

**What this isolates**: Workspace directories, Python namespaces, tool state, and in-flight tool execution.

**What this does NOT isolate**: Host filesystem outside the workspace, system processes, network, environment variables, git global config (`~/.gitconfig`). A bash command like `cat /etc/passwd` or `rm -rf /home` would escape the workspace boundary.

### Layer 2: Docker Container Isolation (Production)

In production, each `swe_env` server runs in its own **Docker container** (see `server/Dockerfile`). The container provides:

- **Filesystem isolation**: Each container has its own root filesystem. Workspaces are truly private.
- **Process isolation**: Processes in one container cannot see or signal processes in another.
- **Network isolation**: Containers get separate network namespaces (unless explicitly bridged).
- **Resource limits**: CPU, memory, and disk can be capped per container via Docker/orchestrator settings.

The deployment model is **one container per environment server**, with `max_concurrent_envs` controlling how many agent sessions share a single container. For full isolation between agents, set `max_concurrent_envs=1` (one agent per container).

```
Training Orchestrator
  ├── Container A (swe_env server) ← Agent 1's WebSocket session
  │     └── /tmp/swe_workspace_xxx/
  ├── Container B (swe_env server) ← Agent 2's WebSocket session
  │     └── /tmp/swe_workspace_yyy/
  └── Container C (swe_env server) ← Agent 3's WebSocket session
        └── /tmp/swe_workspace_zzz/
```

### Layer 3: What We Build (swe_env Responsibilities)

Our code is responsible for Layer 1 only. Specifically:

1. **`Workspace.create()`** always produces a unique temp directory. No two instances share a workspace path.
2. **All tool modules use `cwd=workspace_path`** when spawning subprocesses. Bash, git, and Python tools never operate on a shared or hardcoded directory.
3. **`reset()` destroys and recreates the workspace**, ensuring no state leaks between episodes.
4. **`close()` cleans up the workspace**, preventing temp directory accumulation.
5. **The factory pattern** (`SWEEnvironment.with_default_tools`) creates fresh Workspace + tool module instances on every call, so the `HTTPEnvServer` can safely instantiate one per session.

Docker container orchestration (Layer 2) is handled by OpenEnv's existing container runtime (`src/openenv/core/containers/`) and is outside our scope -- we just provide the Dockerfile.

### Concurrency Test Plan (Stage 5)

Integration tests will verify isolation by running two `SWEEnvironment` instances in parallel:
- Both create files via bash -- verify each only sees its own files.
- Both init git repos -- verify independent git histories.
- Both define Python variables -- verify no namespace leakage.
- One resets while the other is mid-episode -- verify no cross-contamination.

## File Structure

```
envs/swe_env/
├── __init__.py
├── models.py                    # SWEState
├── client.py                    # MCPToolClient subclass
├── openenv.yaml
├── pyproject.toml
└── server/
    ├── __init__.py
    ├── app.py                   # create_app() entrypoint
    ├── environment.py           # SWEEnvironment
    ├── workspace.py             # Workspace lifecycle
    ├── tool_module.py           # ToolModule protocol
    ├── tools/
    │   ├── __init__.py
    │   ├── bash_tool.py         # BashToolModule
    │   ├── git_tool.py          # GitToolModule
    │   └── python_tool.py       # PythonToolModule
    └── Dockerfile
```

## Dependency Graph

```
Stage 1 (Foundation)
  ├── workspace.py
  ├── tool_module.py (Protocol)
  ├── models.py
  └── environment.py (skeleton)
        │
        ├── Stage 2 (Bash) ──── independent
        ├── Stage 3 (Git) ───── independent
        └── Stage 4 (Python) ── independent
              │
              Stage 5 (Integration) ── depends on all above
```

Stages 2, 3, 4 are independent of each other (all depend only on Stage 1).

---

## Stage 1: Foundation (Workspace + ToolModule Protocol + Environment Skeleton)

**Files to create:** `server/workspace.py`, `server/tool_module.py`, `models.py`, `server/environment.py`, `server/__init__.py`, `server/tools/__init__.py`

**Study first** (read these before writing code):
- `envs/echo_env/server/echo_environment.py` -- how MCPEnvironment is subclassed, tool registration, reset/step pattern
- `src/openenv/core/env_server/mcp_environment.py` -- MCPEnvironment constructor signature, `_step_impl` abstract method
- `src/openenv/core/env_server/types.py` -- `State`, `Action`, `Observation` base classes
- `envs/echo_env/models.py` -- how State is extended (if it exists; echo_env may use base State directly)

### `server/workspace.py` -- Workspace

Manages a temp directory per episode. Key methods:
- `create() -> Path` -- creates fresh tmpdir, destroys old one
- `destroy()` -- removes tmpdir
- `path -> Path` property (raises if not initialized)
- `is_active -> bool`

### `server/tool_module.py` -- ToolModule Protocol

```python
@runtime_checkable
class ToolModule(Protocol):
    def register(self, mcp: FastMCP) -> None: ...
    def reset(self) -> None: ...
    def cleanup(self) -> None: ...
```

### `models.py` -- SWEState

Extends `State` with `workspace_path: str` and `available_tools: list[str]`.

### `server/environment.py` -- SWEEnvironment

- Subclasses `MCPEnvironment`
- Constructor takes `tool_modules: list[ToolModule]`, creates `FastMCP("swe_env")`, registers all modules
- `reset()`: creates fresh workspace via `Workspace.create()`, calls `module.reset()` on each module
- `step()`: increments step count, delegates to `super().step()` (MCPEnvironment handles tool routing)
- `close()`: calls `module.cleanup()` on each, destroys workspace
- `with_default_tools()` classmethod factory: creates Workspace + standard tool modules with `get_workspace = lambda: self._workspace.path`

### Tests (`tests/envs/test_swe_env_stage1.py`)
- `Workspace`: create/destroy lifecycle, create-twice replaces old, path raises before create
- `ToolModule` protocol: mock class satisfies `isinstance` check
- `SWEEnvironment` skeleton: reset returns observation with workspace path, state tracks step count, close destroys workspace

### Definition of Done
- [ ] All files listed above exist under `envs/swe_env/`
- [ ] `PYTHONPATH=src:envs uv run pytest tests/envs/test_swe_env_stage1.py -v` passes
- [ ] `SWEEnvironment` can be instantiated with no tool modules and reset/step/close work
- [ ] Update Progress Tracker: Stage 1 -> "Done"

---

## Stage 2: Bash Tool

**File to create:** `server/tools/bash_tool.py`

**Study first:**
- Stage 1 code (must be complete)
- `software-agent-sdk/openhands-tools/openhands/tools/terminal/definition.py` -- OpenHands terminal tool for inspiration (but we use simpler subprocess.run)

### `BashToolModule`

Constructor takes `get_workspace: Callable[[], Path]` and `default_timeout: int = 120`.

Registers one MCP tool:
- **`bash(command: str, timeout: int) -> dict`** -- runs `subprocess.run(["bash", "-c", command], cwd=workspace)`, returns `{stdout, stderr, exit_code}`. Handles `TimeoutExpired` (exit_code=124).

`reset()` and `cleanup()` are no-ops (no internal state).

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
- [ ] `PYTHONPATH=src:envs uv run pytest tests/envs/test_swe_env_stage2.py -v` passes
- [ ] Update Progress Tracker: Stage 2 -> "Done"

---

## Stage 3: Git Tool

**File to create:** `server/tools/git_tool.py`

**Study first:**
- Stage 1 code (must be complete)
- `envs/git_env/server/git_task_environment.py` -- existing git env for patterns (but we use local subprocess, not Gitea)

### `GitToolModule`

Registers two MCP tools:
- **`git(command: str, working_dir: str = "", timeout: int = 60) -> dict`** -- runs `git <command>` in workspace (or `workspace/working_dir`). Returns `{stdout, stderr, exit_code}`.
- **`git_clone(repo_url: str, target_dir: str = "", branch: str = "", depth: int = 0) -> dict`** -- structured clone with parameters. Longer default timeout (300s).

### Tests (`tests/envs/test_swe_env_stage3.py`)
- `git init` + `git status` in workspace
- `git add` + `git commit` flow
- `working_dir` parameter navigates into subdirectory
- Nonexistent `working_dir` returns error
- `git_clone` with branch/depth parameters
- Full integration: list_tools returns `["bash", "git", "git_clone"]`

### Definition of Done
- [ ] `GitToolModule` exists and satisfies `ToolModule` protocol
- [ ] `PYTHONPATH=src:envs uv run pytest tests/envs/test_swe_env_stage3.py -v` passes
- [ ] Update Progress Tracker: Stage 3 -> "Done"

---

## Stage 4: Python Tool

**File to create:** `server/tools/python_tool.py`

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

### Tests (`tests/envs/test_swe_env_stage4.py`)
- Basic execution: `print("hello")` returns stdout
- Persistent namespace: define `x = 5` then `print(x)` in separate calls
- Error handling: syntax errors return stderr + exit_code=1
- Reset clears state: after reset, previously defined variables are gone
- Full integration: all three tools listed, Python variables persist across steps within episode

### Definition of Done
- [ ] `PythonToolModule` exists and satisfies `ToolModule` protocol
- [ ] `PYTHONPATH=src:envs uv run pytest tests/envs/test_swe_env_stage4.py -v` passes
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
- Concurrent instances: two environments in parallel, verify no cross-contamination (see Sandboxing section)
- CodeAct mode: `env.get_callables()` returns bash/git/python functions

### Definition of Done
- [ ] `server/app.py`, `client.py`, `__init__.py`, `openenv.yaml`, `pyproject.toml`, `server/Dockerfile` all exist
- [ ] `PYTHONPATH=src:envs uv run pytest tests/envs/test_swe_env_integration.py -v` passes
- [ ] `uv run ruff format envs/swe_env/ --check && uv run ruff check envs/swe_env/` passes
- [ ] All previous stage tests still pass
- [ ] Update Progress Tracker: Stage 5 -> "Done"

---

## Verification Commands

```bash
# Run tests for a specific stage
PYTHONPATH=src:envs uv run pytest tests/envs/test_swe_env_stage1.py -v

# Run all swe_env tests
PYTHONPATH=src:envs uv run pytest tests/envs/test_swe_env*.py -v

# Lint
uv run ruff format envs/swe_env/ --check && uv run ruff check envs/swe_env/

# Full test suite (ensure no regressions)
PYTHONPATH=src:envs uv run pytest tests/ -v --tb=short
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
| `rfcs/003-mcp-support.md` | MCP architecture RFC |

## Key Imports Quick Reference

These are the imports you'll need most often. All from OpenEnv core (read-only):

```python
# Base classes for the environment
from openenv.core.env_server.mcp_environment import MCPEnvironment
from openenv.core.env_server.types import Action, Observation, State

# MCP action/observation types (used by agents to interact with tools)
from openenv.core.env_server.mcp_types import (
    CallToolAction,
    CallToolObservation,
    ListToolsAction,
    ListToolsObservation,
)

# HTTP server factory
from openenv.core.env_server.http_server import create_app

# MCP client (for the client.py)
from openenv.core.mcp_client import MCPToolClient

# Python executor (for Stage 4)
from openenv.core.tools.local_python_executor import PyExecutor
# PyExecutor.run(code: str) -> CodeExecResult  (has .stdout, .stderr, .exit_code)

# FastMCP (third-party, for tool registration)
from fastmcp import FastMCP
# Usage: mcp = FastMCP("name"); @mcp.tool; def my_tool(...) -> ...: ...
```

### MCPEnvironment Constructor Signature

```python
MCPEnvironment.__init__(self, mcp_server: FastMCP, transform=None) -> None
```

Key methods inherited:
- `step(action)` -- routes ListToolsAction/CallToolAction, delegates others to `_step_impl()`
- `get_callables() -> dict[str, Callable]` -- extracts Python callables from FastMCP for CodeAct
- `_step_impl(action, timeout_s, **kwargs) -> Observation` -- abstract, must implement

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

Record what was done in each session so future sessions have context.

| Date | Session | What was done | Notes |
|------|---------|---------------|-------|
| 2026-02-11 | 1 | Initial plan created | Explored OpenEnv + OpenHands SDK, designed architecture |
| | | | |
