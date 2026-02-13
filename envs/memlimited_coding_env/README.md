# Memory-Limited Coding Environment

A subprocess-isolated variant of [`coding_env`](../coding_env/README.md) that enforces memory, CPU, and import restrictions per code execution. Designed for stateless HTTP endpoints (e.g., TORL `POST /step`) where each request is independent.

## Key Differences from `coding_env`

| | `coding_env` | `memlimited_coding_env` |
|--|---|---|
| Executor | `PyExecutor` (in-process, smolagents AST interpreter) | `SubprocessPyExecutor` (`exec()` in forked child) |
| State between steps | Persists (variables, imports carry over) | Does not persist (fresh process per step) |
| Memory limits | None | `RLIMIT_AS` per child process |
| CPU limits | None | `RLIMIT_CPU` per child process |
| Import restrictions | smolagents allow-list | Custom allow-list (safe stdlib + data science) |
| Builtin restrictions | smolagents AST filtering | `open`/`eval`/`exec`/`compile` removed |
| Audit hooks | None | Blocks `subprocess.Popen`, `os.system`, `socket.connect`, etc. |

## Security Layers

Each `run()` call spawns a child process with four layers of protection:

1. **RLIMIT_AS / RLIMIT_CPU** -- OS-level resource caps. Memory limit is relative to the inherited VM footprint.
2. **Restricted `__import__`** -- Only allow-listed modules can be imported. Covers safe stdlib (`math`, `json`, `re`, `collections`, etc.) and data science (`numpy`, `pandas`, `scipy`, `sympy`, `sklearn`). Extendable via `additional_imports`.
3. **Stripped builtins** -- `open`, `eval`, `exec`, `compile`, `breakpoint` removed from the exec namespace.
4. **Audit hook** -- `sys.addaudithook` backstop blocking `subprocess.Popen`, `os.system`, `socket.connect`, and other dangerous syscall patterns.

## Configuration

Environment variables (read at `SubprocessPyExecutor` init time):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENENV_MEMORY_LIMIT_MB` | `4096` | Max additional virtual memory (MB) per child |
| `OPENENV_TIMEOUT_S` | `30` | Wall-clock timeout per execution |
| `OPENENV_CPU_LIMIT_S` | `60` | CPU-time limit per execution |

## Usage

```bash
# Install (pulls in coding_env transitively)
uv pip install -e openenv/envs/memlimited_coding_env

# Run server
uvicorn memlimited_coding_env.server.app:app --host 0.0.0.0 --port 8000
```

## Tests

```bash
PYTHONPATH=src:envs python -m pytest \
    tests/envs/memlimited_coding_env/test_subprocess_executor.py \
    tests/envs/memlimited_coding_env/test_memlimited_python_codeact_env.py -v
```

## Project Structure

```
memlimited_coding_env/
├── __init__.py                    # Re-exports from coding_env
├── pyproject.toml                 # Package: openenv-memlimited_coding_env
└── server/
    ├── __init__.py
    ├── app.py                     # Server entrypoint
    ├── memlimited_python_codeact_env.py  # MemlimitedPythonCodeActEnv
    └── subprocess_executor.py     # SubprocessPyExecutor (exec + security)
```
