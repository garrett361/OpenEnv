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
| Stage 2 | Done | Bash tool module |
| Stage 3 | Not Started | File editor tool module |
| Stage 4 | Not Started | SWE-Bench task lifecycle (task-based reset, patch extraction, evaluation) |
| Stage 5 | Not Started | App, Client, Dockerfile, integration tests |

---

## Context

**The primary goal of `swe_env` is to be a drop-in replacement for OpenHands as the environment backend in the SkyRL-Agent pipeline for SWE-Bench agent training.** [SkyRL-Agent](https://github.com/NovaSky-AI/SkyRL/tree/main/skyrl-agent) runs SWE-Bench tasks at scale for RL training. Its pipeline works in three phases: (1) `initialize_runtime()` sets up a Docker-based OpenHands runtime with a cloned repo, (2) `run_controller()` runs the agent step loop where the agent uses `bash` and `str_replace_editor` tools to explore and fix bugs, and (3) `complete_runtime()` + `evaluate_result()` extracts the git patch and grades it. We want `swe_env` to provide the same capabilities -- same tools, same task lifecycle, same interface shape -- so that SkyRL-Agent can switch from OpenHands to `swe_env` with minimal changes to the agent code.

SWE-Bench is the standard benchmark for evaluating autonomous software engineering agents. Each task gives an agent a bug report (problem statement) and a repository checked out at a specific commit. The agent must explore the codebase, understand the bug, and produce a patch that makes the failing tests pass. This shapes every design decision: the tools we expose, how reset works, what state we track, and how we evaluate results.

OpenEnv has individual environments for Python execution (`coding_env`), Git operations (`git_env`), and various other tasks -- but no environment that combines these into a persistent workspace where an agent can explore a real codebase, edit files, run tests, and produce patches. The OpenHands SDK (`software-agent-sdk/`) demonstrates this pattern: a unified workspace with modular tools (terminal, file_editor, grep, glob) sharing a common execution context.

`swe_env` brings this capability to OpenEnv: a sandboxed, persistent workspace with modular tools exposed via MCP, designed to run SWE-Bench tasks end-to-end. The environment exposes the same tool interface that agents trained on OpenHands expect (bash for terminal operations, file_editor for code modifications), so switching environments does not require retraining or changing agent prompts.

### Drop-In Replacement for SkyRL-Agent

For `swe_env` to replace OpenHands in SkyRL-Agent's pipeline, it must support:

1. **Same tool semantics**: `bash` (terminal command execution) and `file_editor` (str_replace-style editing) with the same argument shapes and return formats that OpenHands agents expect.
2. **Same task lifecycle**: SkyRL-Agent's `SWEBenchTask.initialize_runtime()` maps to our `reset(instance=...)`. The `OHCodeActAgent` step loop maps to our `step()`. `complete_runtime()` maps to our `get_patch()`. `evaluate_result()` maps to our `evaluate()`.
3. **Same instance format**: Accept SWE-Bench instances with `{instance_id, repo, base_commit, problem_statement, test_patch, version}` -- the same fields SkyRL-Agent loads from HuggingFace datasets.
4. **Same evaluation contract**: Apply patch to repo, run test suite, return resolved/not-resolved (binary reward for RL training).

The key difference is implementation: OpenHands uses Docker containers with full OS-level isolation; `swe_env` uses lightweight process-level isolation via temp directories and `subprocess.run`. This makes `swe_env` faster to start, easier to debug, and simpler to deploy, while providing the same agent-facing interface.

### SWE-Bench Task Structure

Each SWE-Bench instance contains:

| Field | Description |
|-------|-------------|
| `instance_id` | Unique identifier (e.g. `django__django-11099`) |
| `repo` | Repository name (e.g. `django/django`) |
| `base_commit` | Git commit hash to checkout |
| `problem_statement` | Bug report / issue description (the agent's instructions) |
| `test_patch` | Patch containing the test(s) that verify the fix |
| `version` | Version/branch identifier |

The agent lifecycle for one task:
```
1. Reset with instance → clone repo at base_commit, apply test_patch
2. Agent reads problem_statement
3. Agent explores code (bash: grep, find, cat), edits files (file_editor: str_replace), runs tests (bash: python -m pytest)
4. Agent signals completion
5. Extract git patch (diff from base_commit)
6. Evaluate: apply patch to clean repo, run tests → resolved or not
```

### What SkyRL Taught Us

Studying [SkyRL-Agent's](https://github.com/NovaSky-AI/SkyRL/tree/main/skyrl-agent) SWE-Bench implementation revealed the tools agents actually need:

1. **Bash** (essential): repo exploration (`grep`, `find`, `cat`), running tests (`python -m pytest`), git operations (`git status`, `git diff`), installing dependencies. This is the universal tool -- git operations route through bash, not a separate git tool.

2. **File editor** (essential): structured file editing (`str_replace`, `view`, `create`, `insert`, `undo_edit`). This is the agent's primary tool for making code changes. Agents are far more reliable with structured editing than with `sed`/heredocs via bash.

3. **Patch extraction** (essential): at episode end, `git diff --cached {base_commit}` extracts the agent's work product.

4. **Evaluation** (essential): apply patch to clean repo, run test suite, return resolved/not-resolved.

5. **Python executor** (not needed for SWE-Bench): agents don't use an in-memory Python namespace. They edit real files and run real tests via bash.

## Architecture Overview

### How MCP Tool Calling Works

Agents never see MCP protocol details. There are two interaction modes:

1. **Tool-calling mode (most common):** The agent sends `CallToolAction(tool_name="bash", arguments={"command": "ls"})` and gets back a `CallToolObservation`. This is identical in shape to LLM tool-calling schema. `MCPEnvironment.step()` routes it through FastMCP transparently.

2. **CodeAct mode:** `MCPEnvironment.get_callables()` extracts registered tools as plain Python callables. An agent writes `result = bash(command="ls")` directly.

MCP is an implementation detail giving us automatic tool discovery, standard dispatch, and modularity.

### SWE-Bench Task Lifecycle

```
WebSocket connect → factory creates SWEEnvironment (Workspace dir created eagerly)
  → client sends "reset" with instance data →
      Workspace.reset() clears dir
      Clone repo at base_commit into workspace
      Apply test_patch (so failing tests exist)
      Return problem_statement to agent
  → client sends "step" × N →
      Agent uses bash + file_editor to explore, edit, test
      Workspace persists across steps
  → client calls get_patch() →
      Extract git diff from base_commit
  → client calls evaluate() →
      Run test suite, return resolved/not-resolved
  → client sends "reset" with next instance → (next episode)
  → ...
  → WebSocket disconnect → env.close() → Workspace.close() removes dir
```

### Workspace Lifecycle

The `HTTPEnvServer` creates one `SWEEnvironment` instance per WebSocket session (via the factory pattern). Within that session:

The Workspace uses `tempfile.TemporaryDirectory` so cleanup happens even if `close()` is missed (via `__del__`). Each concurrent session gets its own independent Workspace.

### ToolModule Pattern

Each tool category is a `ToolModule` that:
1. Receives a `get_workspace: Callable[[], Path]` in its constructor
2. Registers MCP tools with a shared `FastMCP` server via `register(mcp)`
3. Supports `reset()` (episode boundary) and `cleanup()` (session end)

To add a tool module to the environment, instantiate it and append to the `tool_modules` list in `SWEEnvironment.with_default_tools()`.

## Key Design Decisions

1. **Base class: `MCPEnvironment`** -- gives us `ListToolsAction`/`CallToolAction` routing, `get_callables()` for CodeAct mode, and tool name validation for free.
2. **`ToolModule` protocol** -- each tool category (bash, file_editor) is an independent module that registers its tools with a shared `FastMCP` server. Adding a new tool = one new file + one line in the factory.
3. **`get_workspace` callable pattern** -- tool modules receive a `() -> Path` callable instead of a static `Path`, so they always reference the current workspace.
4. **Bash via `subprocess.run`** (stateless per-command) -- simpler than a persistent shell session. Each command runs in the workspace directory. Git operations route through bash (following OpenHands' pattern -- no separate git tool).
5. **File editor as a dedicated tool** -- agents are significantly more reliable with structured `str_replace` than with `sed`/heredocs. This is the most-used tool in SWE-Bench after bash.
6. **Task-based reset** -- `reset()` accepts a SWE-Bench instance dict to set up the workspace (clone repo, checkout commit, apply test patch). Without an instance, it just clears the workspace (useful for testing).
7. **Patch extraction as environment method** -- `get_patch()` extracts the agent's changes as a git diff. This is separate from `step()` because it happens after the agent signals completion.
8. **Evaluation in environment** -- `evaluate()` runs the test suite against the agent's patch and returns a resolved/not-resolved result with reward signal.

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
| `tests/envs/swe_env/test_workspace.py` | 6 tests covering Workspace class |
| `tests/envs/swe_env/test_environment.py` | 15 tests covering ToolModule protocol, SWEState, SWEEnvironment skeleton |

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
- `with_default_tools()` classmethod: creates `Workspace()`, builds `get_workspace = lambda: workspace.path`, instantiates tool modules (currently `[BashToolModule]`), returns `cls(workspace=workspace, tool_modules=tool_modules)`

**How to add a new tool module:**
1. Create `envs/swe_env/server/tools/<name>_tool.py` implementing `ToolModule`
2. In `SWEEnvironment.with_default_tools()`, import and append to `tool_modules` list
3. Write tests in `tests/envs/swe_env/test_<name>_tool.py`

### Verification

```bash
PYTHONPATH=src:envs uv run python -m pytest tests/envs/swe_env/test_workspace.py tests/envs/swe_env/test_environment.py -v
# 21 passed
```

---

## Stage 2: Bash Tool (DONE)

### What Was Built

| File | Purpose |
|------|---------|
| `envs/swe_env/server/tools/bash_tool.py` | `BashToolModule` -- runs commands via `subprocess.run(["bash", "-c", command], cwd=workspace)` |
| `tests/envs/swe_env/test_bash_tool.py` | 11 tests covering protocol conformance, direct tool behavior, and integration |

### Key Implementation Details

**BashToolModule** (`server/tools/bash_tool.py`):
- Constructor takes `get_workspace: Callable[[], Path]` and `default_timeout: int = 120`
- Registers one MCP tool: `bash(command: str, timeout: int = 0) -> dict`
- `timeout=0` means use `default_timeout`; any positive value overrides it
- Returns `{"stdout": str, "stderr": str, "exit_code": int}`
- Catches `subprocess.TimeoutExpired` and returns `exit_code=124`
- `reset()` and `cleanup()` are no-ops (stateless, fresh process per call)

**Wiring** (`server/environment.py`):
- `with_default_tools()` now imports and instantiates `BashToolModule(get_workspace=get_workspace)` in the `tool_modules` list

**Test patterns established** (`tests/envs/swe_env/test_bash_tool.py`):
- Unit tests use a fixture that constructs `SWEEnvironment` with only `BashToolModule` (not `with_default_tools()`)
- Helper `_bash(env, command, timeout=0)` calls `CallToolAction` and extracts the result dict. The `obs.result` from `CallToolAction` is a `CallToolResult` object with a `.data` attribute (already a dict), not a raw JSON string -- the helper handles both cases via `hasattr(result, "data")`
- Integration tests use `SWEEnvironment.with_default_tools()` for full-stack verification

### Verification

```bash
PYTHONPATH=src:envs uv run python -m pytest tests/envs/swe_env/test_bash_tool.py -v
# 11 passed
```

---

## Stage 3: File Editor Tool

**Pre-flight:** Before starting, verify the existing 32 tests pass:
```bash
PYTHONPATH=src:envs uv run python -m pytest tests/envs/swe_env/ -v
# Expected: 32 passed (6 workspace + 15 environment + 11 bash)
```

**File to create:** `envs/swe_env/server/tools/file_editor_tool.py`

**Study first:**
- `envs/swe_env/server/tools/bash_tool.py` -- follow the same ToolModule pattern (constructor, register, reset, cleanup)
- `tests/envs/swe_env/test_bash_tool.py` -- follow the same test patterns (fixture, helper, `obs.result.data` extraction)
- `software-agent-sdk/openhands/tools/file_editor/` -- OpenHands' file editor implementation for design reference (operations, validation, error messages, undo history, output formatting)
- `envs/swe_env/server/environment.py` -- see how `with_default_tools()` wires modules in

### Why This Tool Matters for SWE-Bench

The file editor is the **most-used tool in SWE-Bench** after bash. Agents need to make precise, targeted code modifications in large repositories. Structured editing (`str_replace` with exact string matching) is far more reliable than bash alternatives (`sed`, heredocs, `echo >>`). OpenHands uses `str_replace_editor` as its primary editing interface, and SkyRL's SWE-Bench agents rely on it heavily.

### `FileEditorToolModule`

Constructor takes `get_workspace: Callable[[], Path]`.

Registers one MCP tool with a `command` parameter that dispatches to operations:
- **`file_editor(command: str, path: str, file_text: str = "", old_str: str = "", new_str: str = "", insert_line: int = -1, view_range: str = "") -> dict`**

Operations (selected by `command`):

| Command | Description | Required params |
|---------|-------------|-----------------|
| `view` | Display file contents with line numbers. Supports `view_range` as `"start,end"` (1-indexed, end=-1 means EOF). Can also list directory contents. | `path` |
| `create` | Create a new file. Fails if file already exists. | `path`, `file_text` |
| `str_replace` | Find and replace an exact string. Must match exactly once. | `path`, `old_str`, `new_str` |
| `insert` | Insert text after a given line number (0 = before first line). | `path`, `insert_line`, `new_str` |
| `undo_edit` | Revert the last edit to a file. | `path` |

Returns `{"output": str, "exit_code": int}` where `output` contains the formatted result or error message.

**State management:**
- Maintains an undo history (dict mapping file paths to list of previous contents)
- `reset()` clears undo history
- `cleanup()` clears undo history

**Key implementation details (following OpenHands patterns):**
- All paths must be absolute. If a relative path is given, resolve it relative to workspace root.
- `str_replace` uses exact string matching (not regex). The `old_str` must appear exactly once in the file; if 0 or 2+ matches, return an error with context.
- `view` formats output as `cat -n` style (line numbers + content). Truncate to ~16,000 chars if too long.
- `create` fails if file already exists (prevents accidental overwrites). Must create parent directories if they don't exist (`mkdir -p` equivalent).
- `insert_line=0` means insert before the first line; `insert_line=N` inserts after line N.
- Undo history: dict mapping `str(path)` to `list[str]` of previous file contents. Stores the full file content before each edit (str_replace, insert, create). Max 5 entries per file. Undo pops the most recent entry (stack order).

After creating the module, update `SWEEnvironment.with_default_tools()` to include it.

### Tests (`tests/envs/swe_env/test_file_editor_tool.py`)

Follow the same test patterns as `test_bash_tool.py`: fixture builds `SWEEnvironment` with only `FileEditorToolModule`, helper function calls `CallToolAction` and extracts `obs.result.data`.

**view tests:**
- View a file shows line-numbered content
- View with `view_range="2,4"` shows only those lines
- View a directory lists its contents
- View nonexistent file returns error

**create tests:**
- Create a new file succeeds
- Create on existing file returns error
- Created file contents match `file_text`

**str_replace tests:**
- Replace unique string succeeds
- Old string not found returns error with message
- Multiple matches returns error listing line numbers
- `old_str == new_str` returns error

**insert tests:**
- Insert after line N places content correctly
- Insert at line 0 prepends
- Insert after last line appends
- Insert at invalid line number returns error

**undo_edit tests:**
- Undo after str_replace restores original
- Undo after insert restores original
- Undo with no history returns error
- Multiple edits + multiple undos work in stack order

**reset tests:**
- After reset, undo history is cleared

**Integration tests:**
- `list_tools` via `with_default_tools()` returns `["bash", "file_editor"]`
- Full SWE-Bench-like workflow: create file → view → str_replace → view (verify change) → undo_edit → view (verify restored)

### Definition of Done
- [ ] `FileEditorToolModule` exists and satisfies `ToolModule` protocol
- [ ] `SWEEnvironment.with_default_tools()` includes `FileEditorToolModule`
- [ ] `PYTHONPATH=src:envs uv run python -m pytest tests/envs/swe_env/test_file_editor_tool.py -v` passes
- [ ] Previous tests still pass: `PYTHONPATH=src:envs uv run python -m pytest tests/envs/swe_env/ -v`
- [ ] Update Progress Tracker: Stage 3 -> "Done"

---

## Stage 4: SWE-Bench Task Lifecycle

This stage adds the SWE-Bench-specific functionality that makes the environment useful for running real tasks: task-based reset, patch extraction, and evaluation.

**Files to create/modify:**
- `envs/swe_env/models.py` -- add `SWEBenchInstance` model, extend `SWEState`
- `envs/swe_env/server/environment.py` -- add task-based reset, `get_patch()`, `evaluate()`
- `tests/envs/swe_env/test_task_lifecycle.py` -- new test file

**Study first:**
- `envs/swe_env/server/environment.py` -- current reset/step/close implementation
- `envs/swe_env/models.py` -- current SWEState
- SkyRL task setup: understand what `initialize_runtime()`, `complete_runtime()`, and `evaluate_result()` do (documented in Session Log, session 4)
- `envs/git_env/server/git_task_environment.py` -- reference for task-based environment patterns in OpenEnv

### `SWEBenchInstance` Model

Add to `models.py`:

```python
class SWEBenchInstance(BaseModel):
    instance_id: str
    repo: str                     # e.g. "django/django" or full URL
    base_commit: str              # git commit hash
    problem_statement: str        # bug report text
    test_patch: str = ""          # patch with failing tests
    version: str = ""             # version/branch identifier
```

### Extended `SWEState`

Add instance-tracking fields to `SWEState`:

```python
class SWEState(State):
    workspace_path: str = ""
    available_tools: list[str] = Field(default_factory=list)
    instance_id: str = ""
    problem_statement: str = ""
    repo_path: str = ""           # path to cloned repo within workspace
```

### Task-Based Reset

Modify `SWEEnvironment.reset()` to accept an optional `instance` parameter:

```python
def reset(self, seed=None, episode_id=None, instance=None, **kwargs):
    self._workspace.reset()
    for module in self._tool_modules:
        module.reset()

    if instance is not None:
        self._setup_instance(instance)

    # Build state with instance info if present
    ...
```

**`_setup_instance(instance)` performs:**
1. Parse `instance` as `SWEBenchInstance` (accept dict or model)
2. Determine repo URL: if `repo` looks like `owner/name`, construct `https://github.com/{repo}.git`; if it's already a URL, use as-is
3. Clone: `git clone {repo_url} repo` in workspace dir
4. Checkout: `git checkout {base_commit}` in the cloned repo
5. Apply test patch: if `test_patch` is non-empty, write to temp file and `git apply {patch_file}` in the repo
6. Store `instance_id`, `problem_statement`, and repo path on state

All git/clone operations use `subprocess.run` with appropriate timeouts.

### Patch Extraction: `get_patch()`

New method on `SWEEnvironment`:

```python
def get_patch(self) -> str:
    """Extract the agent's changes as a git diff from base_commit.

    Returns the diff as a string. Empty string if no changes or no repo.
    """
```

Implementation:
1. Find the repo directory in workspace
2. `git add -A` (stage all changes)
3. `git diff --cached {base_commit}` to get diff relative to starting point
4. Return the diff string

### Evaluation: `evaluate()`

New method on `SWEEnvironment`:

```python
def evaluate(self, test_command: str = "") -> dict:
    """Run tests and return evaluation results.

    Args:
        test_command: Shell command to run tests. If empty, tries
            'python -m pytest' in the repo directory.

    Returns:
        Dict with keys: exit_code, stdout, stderr, resolved (bool).
    """
```

Implementation:
1. Run the test command in the repo directory via `subprocess.run`
2. Return `{"exit_code": int, "stdout": str, "stderr": str, "resolved": bool}`
3. `resolved = (exit_code == 0)`

Note: full SWE-Bench evaluation is more nuanced (parsing test output, checking specific test names). For MVP, `exit_code == 0` is sufficient. The evaluation harness can be made more sophisticated later.

### Tests (`tests/envs/swe_env/test_task_lifecycle.py`)

These tests use a **local git repo** created in a temp dir as the "remote" to avoid network dependencies.

**Fixture: `local_repo`**
- Creates a temp dir, `git init`, adds a Python file with a known bug, commits
- Returns the path (used as `repo` URL for cloning)

**Task-based reset tests:**
- Reset with instance clones repo into workspace
- Cloned repo is at `base_commit`
- `state.instance_id` and `state.problem_statement` are set
- `state.repo_path` points to the cloned repo
- Reset with `test_patch` applies the patch
- Reset without instance just clears workspace (existing behavior preserved)

**Patch extraction tests:**
- After editing a file via file_editor, `get_patch()` returns a non-empty diff
- Patch contains the expected changes
- `get_patch()` with no changes returns empty string
- `get_patch()` with no repo returns empty string

**Evaluation tests:**
- After fixing the bug, `evaluate()` returns `resolved=True`
- Without fixing, `evaluate()` returns `resolved=False`
- Custom `test_command` is used when provided

**Full lifecycle test:**
- Reset with instance → agent uses bash + file_editor to fix bug → get_patch() → evaluate() → resolved=True

### Definition of Done
- [ ] `SWEBenchInstance` model exists in `models.py`
- [ ] `SWEState` extended with instance fields
- [ ] `reset()` accepts `instance` parameter and sets up workspace
- [ ] `get_patch()` extracts git diff
- [ ] `evaluate()` runs tests and returns results
- [ ] `PYTHONPATH=src:envs uv run python -m pytest tests/envs/swe_env/test_task_lifecycle.py -v` passes
- [ ] Previous tests still pass: `PYTHONPATH=src:envs uv run python -m pytest tests/envs/swe_env/ -v`
- [ ] Update Progress Tracker: Stage 4 -> "Done"

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
Dependencies: `openenv-core[core]`, `fastapi`, `pydantic`, `uvicorn`, `requests`.

### End-to-end tests (`tests/envs/swe_env/test_integration.py`)

**Full SWE-Bench workflow:**
- Reset with a local test instance → list_tools → bash (explore repo) → file_editor (fix bug) → get_patch() → evaluate() → verify resolved

**Workspace isolation:**
- Files from one episode gone after reset

**Multiple episodes:**
- Sequential reset/work/reset cycles with different instances

**Concurrent instances:**
- Two environments in parallel, verify no cross-contamination
- Both clone repos, edit files, extract patches independently

**CodeAct mode:**
- `env.get_callables()` returns bash and file_editor functions

**Tool completeness:**
- `list_tools` returns exactly `["bash", "file_editor"]`

### Definition of Done
- [ ] `server/app.py`, `client.py`, `__init__.py`, `openenv.yaml`, `pyproject.toml`, `server/Dockerfile` all exist
- [ ] `PYTHONPATH=src:envs uv run python -m pytest tests/envs/swe_env/test_integration.py -v` passes
- [ ] `uv run ruff format envs/swe_env/ --check && uv run ruff check envs/swe_env/` passes
- [ ] All previous tests still pass: `PYTHONPATH=src:envs uv run python -m pytest tests/envs/swe_env/ -v`
- [ ] Update Progress Tracker: Stage 5 -> "Done"

---

## Sandboxing & Concurrency

Concurrent `swe_env` instances must not interfere with each other. Isolation is provided at three layers, each progressively stronger:

### Layer 1: Instance-Level Isolation (Within a Single Server Process)

OpenEnv's `HTTPEnvServer` (`src/openenv/core/env_server/http_server.py`) uses a **factory pattern**: `create_app()` receives a callable (class or factory function), and each WebSocket session calls that factory to create a **new, independent `SWEEnvironment` instance**. This means:

- Each session gets its own `Workspace` object, which creates a **unique temp directory** via `tempfile.TemporaryDirectory`.
- Each session gets its own `FastMCP` server with its own tool closures bound to its own workspace path.
- Each session gets its own file editor undo history.
- Tool calls within a session are serialized by a **per-session `ThreadPoolExecutor(max_workers=1)`**, preventing race conditions within a single agent's workspace.
- `SWEEnvironment` sets `SUPPORTS_CONCURRENT_SESSIONS = True` to opt into multi-session support.

### Layer 2: Docker Container Isolation (Production)

In production, each `swe_env` server runs in its own **Docker container**. The deployment model is **one container per environment server**, with `max_concurrent_envs` controlling how many agent sessions share a single container.

Docker container orchestration is handled by OpenEnv's existing container runtime and is outside our scope -- we just provide the Dockerfile.

### Concurrency Test Plan (Stage 5)

Integration tests will verify isolation by running two `SWEEnvironment` instances in parallel:
- Both clone repos via task-based reset -- verify each only sees its own files.
- Both edit files via file_editor -- verify independent undo histories.
- One resets while the other is mid-episode -- verify no cross-contamination.

## File Structure (current state after Stage 2)

```
envs/swe_env/
├── __init__.py                  # exports SWEState
├── models.py                    # SWEState(State), SWEBenchInstance (Stage 4)
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
    │   ├── bash_tool.py         # BashToolModule (done)
    │   └── file_editor_tool.py  # FileEditorToolModule (Stage 3)
    ├── Dockerfile               # scaffolded
    └── requirements.txt         # scaffolded

tests/envs/swe_env/             # no __init__.py needed
├── test_workspace.py            # 6 tests -- Workspace class
├── test_environment.py          # 15 tests -- SWEState, ToolModule protocol, SWEEnvironment
├── test_bash_tool.py            # 11 tests -- BashToolModule
├── test_file_editor_tool.py     # Stage 3
├── test_task_lifecycle.py       # Stage 4
└── test_integration.py          # Stage 5
```

## Verification Commands

```bash
# Run all swe_env tests
PYTHONPATH=src:envs uv run python -m pytest tests/envs/swe_env/ -v

# Run a single test file
PYTHONPATH=src:envs uv run python -m pytest tests/envs/swe_env/test_bash_tool.py -v

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
| `envs/echo_env/` | Reference MCPEnvironment implementation |
| `envs/git_env/` | Reference for task-based environment patterns |
| `software-agent-sdk/openhands/tools/file_editor/` | Reference for file editor design |
| `software-agent-sdk/openhands/tools/terminal/` | Reference for terminal tool design |

## Key Imports Quick Reference

```python
from openenv.core.env_server.mcp_environment import MCPEnvironment
from openenv.core.env_server.types import Action, Observation, State
from openenv.core.env_server.mcp_types import (
    CallToolAction, CallToolObservation, ListToolsAction, ListToolsObservation,
)
from openenv.core.env_server.http_server import create_app
from openenv.core.mcp_client import MCPToolClient
from fastmcp import FastMCP

from swe_env.models import SWEState, SWEBenchInstance
from swe_env.server.workspace import Workspace
from swe_env.server.tool_module import ToolModule
from swe_env.server.environment import SWEEnvironment
```

## Future Extensions (Post-MVP)

These can be added later following the same `ToolModule` pattern:
- **GrepToolModule**: Structured content search returning file paths + line numbers (better than `bash grep` for agent reasoning)
- **GlobToolModule**: Pattern-based file discovery with structured results
- **PythonToolModule**: In-memory Python execution via `PyExecutor` for coding tasks (not needed for SWE-Bench but useful for `coding_env`-style tasks)
- **Persistent shell**: Upgrade bash from `subprocess.run` to persistent tmux/subprocess session (preserves env vars, virtualenvs across commands)
- **Rich evaluation**: Parse test output to check specific test names (not just exit code), support SWE-Bench's evaluation harness directly
- **Pre-built Docker images**: Per-instance Docker images with dependencies pre-installed (like SkyRL's approach) for faster task setup
- **Dataset loaders**: Built-in loading from HuggingFace datasets (SWE-Bench Verified, R2E-Gym, SWE-Smith)

---

## Session Log

| Date | Session | What was done | Notes |
|------|---------|---------------|-------|
| 2026-02-11 | 1 | Initial plan created | Explored OpenEnv + OpenHands SDK, designed architecture |
| 2026-02-11 | 2 | Stage 1 complete (21 tests passing) | Workspace simplified from create/destroy cycle to eager `TemporaryDirectory` with `reset()` clearing contents. Cleaned up scaffolded dead code (`app.py`, `client.py` stubbed; deleted `swe_env_environment.py`). Established code style rules (no dead code, no comment headers). |
| 2026-02-11 | 3 | Stage 2 complete (32 tests passing) | Implemented `BashToolModule` and wired into `with_default_tools()`. Reorganized tests from `tests/envs/test_swe_env_stage*.py` into `tests/envs/swe_env/` with semantic grouping: `test_workspace.py` (6), `test_environment.py` (15), `test_bash_tool.py` (11). No `__init__.py` in test dir. Key discovery: `obs.result` from `CallToolAction` is a `CallToolResult` object with `.data` dict, not raw JSON -- test helpers use `hasattr(result, "data")` to handle this. Updated Stage 1's `test_list_tools_empty_without_modules` to construct env manually (since `with_default_tools()` now includes BashToolModule). |
| 2026-02-11 | 4 | Plan revised for SWE-Bench focus | Studied SkyRL's SWE-Bench implementation and OpenHands SDK tool design. Key findings: (1) Git tool unnecessary -- agents use bash for git operations (OpenHands pattern). (2) PythonToolModule (PyExecutor) wrong for SWE-Bench -- agents edit files and run tests, not in-memory Python. (3) File editor is the most critical missing tool. (4) Need task-based reset (clone repo, apply test patch), patch extraction, and evaluation. Replaced Stages 3-5: Stage 3 = File Editor Tool, Stage 4 = SWE-Bench Task Lifecycle, Stage 5 = Integration. Dropped git_tool.py and python_tool.py from file structure. |
