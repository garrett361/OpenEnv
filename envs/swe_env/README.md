---
title: SWE Environment Server
emoji: 🔧
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
app_port: 8000
base_path: /web
tags:
  - openenv
---

# SWE Environment

A sandboxed workspace environment for software engineering agents. Exposes `bash` and `file_editor` tools via MCP, designed to run SWE-Bench tasks end-to-end. Drop-in replacement for OpenHands as the environment backend in SWE-Bench agent training pipelines like SkyRL-Agent.

## Quick Start

```python
from swe_env import SWEEnv, CallToolAction

# Connect to a running server
with SWEEnv(base_url="http://localhost:8000") as env:
    env.reset()

    # Discover available tools
    tools = env.list_tools()
    print([t.name for t in tools])  # ['bash', 'file_editor']

    # Run a shell command
    result = env.call_tool("bash", command="ls -la")
    print(result)

    # Edit a file
    result = env.call_tool(
        "file_editor",
        command="create",
        path="hello.py",
        file_text="print('hello')\n",
    )
```

## SWE-Bench Workflow

The environment supports the full SWE-Bench task lifecycle: reset with an instance, explore and fix the bug, extract the patch, evaluate.

```python
from swe_env import SWEEnv, SWEBenchInstance, CallToolAction

with SWEEnv(base_url="http://localhost:8000") as env:
    # 1. Reset with a SWE-Bench instance
    instance = {
        "instance_id": "django__django-11099",
        "repo": "django/django",
        "base_commit": "abc123...",
        "problem_statement": "Bug report text...",
        "test_patch": "diff --git a/...",
    }
    obs = env.reset(instance=instance)
    # obs.metadata contains instance_id, problem_statement, workspace_path

    # 2. Agent explores and fixes the bug
    env.call_tool("bash", command="find . -name '*.py' | head -20")
    env.call_tool("bash", command="python -m pytest tests/ -x")
    env.call_tool(
        "file_editor",
        command="str_replace",
        path="repo/src/module.py",
        old_str="broken_code()",
        new_str="fixed_code()",
    )

    # 3. Extract the patch
    patch = env.call_tool("get_patch")  # git diff from base_commit

    # 4. Evaluate
    result = env.call_tool("evaluate", test_command="python -m pytest tests/")
    print(result["resolved"])  # True/False
```

## Tools

### `bash`

Runs shell commands via `subprocess.run` in the workspace directory.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `command` | str | required | Shell command to execute |
| `timeout` | int | 120 | Timeout in seconds (0 = use default) |

Returns `{"stdout": str, "stderr": str, "exit_code": int}`. Exit code 124 on timeout.

### `file_editor`

Structured file editing with five operations, selected by the `command` parameter.

| Command | Description | Required Parameters |
|---------|-------------|---------------------|
| `view` | Display file contents with line numbers, or list directory | `path` |
| `create` | Create a new file (fails if exists) | `path`, `file_text` |
| `str_replace` | Find and replace an exact string (must match once) | `path`, `old_str`, `new_str` |
| `insert` | Insert text after a line number (0 = before first line) | `path`, `insert_line`, `new_str` |
| `undo_edit` | Revert the last edit to a file | `path` |

Returns `{"output": str, "exit_code": int}`.

Optional parameters: `view_range` (string `"start,end"`, 1-indexed) for `view`.

## Architecture

```
WebSocket connect
  → factory creates SWEEnvironment (independent workspace per session)
    → reset(instance=...) → clone repo, checkout commit, apply test_patch
    → step() × N → agent uses bash + file_editor
    → get_patch() → git diff from base_commit
    → evaluate() → run tests, return resolved/not-resolved
    → reset(instance=...) → next episode
  → disconnect → cleanup workspace
```

Each WebSocket session gets its own:
- **Workspace**: isolated temp directory via `tempfile.TemporaryDirectory`
- **FastMCP server**: independent tool dispatch
- **File editor state**: separate undo history

## SWE-Bench Instance Format

The `reset(instance=...)` method accepts a dict or `SWEBenchInstance` with:

| Field | Type | Description |
|-------|------|-------------|
| `instance_id` | str | Unique identifier (e.g. `django__django-11099`) |
| `repo` | str | Repository (`owner/name` or full URL or local path) |
| `base_commit` | str | Git commit hash to checkout |
| `problem_statement` | str | Bug report text (the agent's instructions) |
| `test_patch` | str | Patch with failing tests (optional) |
| `version` | str | Version identifier (optional) |

## Building and Running

### Docker

```bash
# Build
docker build -t swe-env:latest -f server/Dockerfile .

# Run
docker run -p 8000:8000 swe-env:latest

# Or from Docker image
from swe_env import SWEEnv
env = SWEEnv.from_docker_image("swe-env:latest")
```

### Local Development

```bash
# Run the server
uvicorn server.app:app --host 0.0.0.0 --port 8000

# Run tests
PYTHONPATH=src:envs uv run python -m pytest tests/envs/swe_env/ -v
```

## Project Structure

```
swe_env/
├── __init__.py              # Exports: SWEEnv, SWEBenchInstance, SWEState
├── models.py                # SWEState, SWEBenchInstance
├── client.py                # SWEEnv(MCPToolClient)
├── openenv.yaml             # OpenEnv manifest
├── pyproject.toml            # Dependencies
└── server/
    ├── __init__.py           # Exports: SWEEnvironment
    ├── app.py                # FastAPI app via create_app()
    ├── environment.py        # SWEEnvironment(MCPEnvironment)
    ├── workspace.py          # Workspace (temp directory wrapper)
    ├── tool_module.py        # ToolModule Protocol
    ├── tools/
    │   ├── __init__.py
    │   ├── bash_tool.py      # BashToolModule
    │   └── file_editor_tool.py  # FileEditorToolModule
    ├── Dockerfile
    └── requirements.txt
```
