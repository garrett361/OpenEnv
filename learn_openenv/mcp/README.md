# MCP Integration in OpenEnv

## Overview

OpenEnv integrates the **Model Context Protocol (MCP)** to expose environment functionality as discoverable, callable tools. This enables LLM agents to interact with environments using a standardized tool-calling interface.

MCP in OpenEnv follows a **dual API boundary**:
- **WebSocket API** (Gym-style): For infrastructure/training orchestration (`reset`, `step`, `state`)
- **MCP API** (Tool-calling): For agent interactions (`list_tools`, `call_tool`)

## Architecture Diagram

```
                              OpenEnv MCP Architecture
    ================================================================================

    +-------------------+                              +------------------------+
    |   Training Loop   |                              |    LLM Agent (Claude,  |
    | (Infrastructure)  |                              |    GPT, etc.)          |
    +--------+----------+                              +-----------+------------+
             |                                                     |
             | reset(), step(), state()                            | tool calls
             | (controls time/episodes)                            | (actions)
             v                                                     v
    +--------+----------------------------------------------------------+--------+
    |                           MCPToolClient                                    |
    |   +------------------------------------------------------------------+     |
    |   | Async WebSocket Client                                           |     |
    |   |  - connect() / disconnect()                                      |     |
    |   |  - list_tools() -> List[Tool]                                    |     |
    |   |  - call_tool(name, **kwargs) -> result                           |     |
    |   |  - step(action) -> StepResult                                    |     |
    |   +------------------------------------------------------------------+     |
    +--------+----------------------------------------------------------+--------+
             |                                                     |
             | WebSocket /ws                                       | WebSocket /ws
             | JSON messages                                       | (type: "mcp")
             |                                                     |
    =========|=====================================================|================
             |                     NETWORK                         |
    =========|=====================================================|================
             |                                                     |
             v                                                     v
    +--------+----------------------------------------------------------+--------+
    |                        HTTPEnvServer (FastAPI)                             |
    |   +------------------------------------------------------------------+     |
    |   | Routes:                                                          |     |
    |   |   POST /reset      -> ResetResponse                              |     |
    |   |   POST /step       -> StepResponse                               |     |
    |   |   GET  /state      -> State                                      |     |
    |   |   GET  /schema     -> SchemaResponse                             |     |
    |   |   GET  /health     -> HealthResponse                             |     |
    |   |   WS   /ws         -> Session handler (step, reset, mcp)         |     |
    |   +------------------------------------------------------------------+     |
    +--------+----------------------------------------------------------+--------+
             |
             | delegates to
             v
    +--------+----------------------------------------------------------+--------+
    |                         MCPEnvironment (Base Class)                        |
    |   +------------------------------------------------------------------+     |
    |   | step(action) routing:                                            |     |
    |   |   - ListToolsAction  -> _handle_list_tools() -> ListToolsObs     |     |
    |   |   - CallToolAction   -> _handle_call_tool()  -> CallToolObs      |     |
    |   |   - Other actions    -> _step_impl() (subclass)                  |     |
    |   |                                                                  |     |
    |   | Tool validation:                                                 |     |
    |   |   - Reserved names blocked: reset, step, state, close            |     |
    |   +------------------------------------------------------------------+     |
    +--------+----------------------------------------------------------+--------+
             |
             | wraps
             v
    +--------+----------------------------------------------------------+--------+
    |                          FastMCP Server                                    |
    |   +------------------------------------------------------------------+     |
    |   |  @mcp.tool                                                       |     |
    |   |  def echo_message(message: str) -> str:                          |     |
    |   |      return message                                              |     |
    |   |                                                                  |     |
    |   |  @mcp.tool                                                       |     |
    |   |  def calculate(a: int, b: int, op: str) -> int:                  |     |
    |   |      ...                                                         |     |
    |   +------------------------------------------------------------------+     |
    +----------------------------------------------------------------------------+
```

## Data Flow

### 1. SIM Mode (Training/Simulation)

In SIM mode, all interactions go through `step()` for infrastructure control:

```
Agent -> ListToolsAction -> MCPEnvironment.step() -> ListToolsObservation
Agent -> CallToolAction  -> MCPEnvironment.step() -> CallToolObservation
```

This allows:
- Infrastructure to control time (step-by-step execution)
- Logging/recording of all agent actions
- Reward computation based on tool usage

### 2. Direct MCP Mode (Production Inference)

For production, agents can use direct MCP JSON-RPC via WebSocket:

```
Agent -> WS {"type": "mcp", "data": {"method": "tools/list"}} -> tools list
Agent -> WS {"type": "mcp", "data": {"method": "tools/call", ...}} -> result
```

## Key Components

### Client Side (`src/openenv/core/mcp_client.py`)

| Class | Purpose |
|-------|---------|
| `MCPClientBase` | Base class with `list_tools()` and tool caching |
| `MCPToolClient` | Full client with `call_tool()`, `get_tool()`, `has_tool()` |

```python
from openenv.core.mcp_client import MCPToolClient

async with MCPToolClient(base_url="http://localhost:8000") as env:
    await env.reset()

    # Discover tools
    tools = await env.list_tools()
    print([t.name for t in tools])  # ['echo_message', 'calculate']

    # Call a tool
    result = await env.call_tool("echo_message", message="Hello!")
    print(result)  # "Hello!"
```

### Server Side (`src/openenv/core/env_server/mcp_environment.py`)

| Class | Purpose |
|-------|---------|
| `MCPEnvironment` | Base class that routes MCP actions to FastMCP server |

```python
from fastmcp import FastMCP
from openenv.core.env_server.mcp_environment import MCPEnvironment

class MyEnv(MCPEnvironment):
    def __init__(self):
        mcp = FastMCP("my-env")

        @mcp.tool
        def my_tool(arg: str) -> str:
            return f"Result: {arg}"

        super().__init__(mcp)

    def reset(self, **kwargs):
        return Observation(done=False)

    def _step_impl(self, action, **kwargs):
        # Handle non-MCP actions
        return Observation(done=False)
```

### MCP Types (`src/openenv/core/env_server/mcp_types.py`)

| Type | Purpose |
|------|---------|
| `Tool` | Tool specification with name, description, input_schema |
| `ListToolsAction` | Action to request tool list |
| `CallToolAction` | Action to invoke a specific tool |
| `ListToolsObservation` | Response with available tools |
| `CallToolObservation` | Response with tool result or error |
| `ToolError` | Structured error for tool failures |
| `ToolErrorType` | Error categories (execution, invalid_args, timeout, etc.) |

## Reserved Tool Names

The following names are **reserved** and cannot be used for MCP tools:
- `reset` - Environment reset (infrastructure)
- `step` - Action execution (infrastructure)
- `state` - State query (infrastructure)
- `close` - Connection close (infrastructure)

This protects the dual API boundary between infrastructure and agent APIs.

## Example: Echo Environment

See `envs/echo_env/server/echo_environment.py` for a complete example:

```python
from openenv.core.env_server.mcp_types import ListToolsAction, CallToolAction

env = EchoEnvironment()
env.reset()

# List tools via step()
obs = env.step(ListToolsAction())
print([t.name for t in obs.tools])  # ['echo_message', 'echo_with_length']

# Call tool via step()
obs = env.step(CallToolAction(
    tool_name="echo_message",
    arguments={"message": "Hello!"}
))
print(obs.result)  # "Hello!"
```

## WebSocket Protocol

The WebSocket endpoint (`/ws`) supports these message types:

| Type | Direction | Purpose |
|------|-----------|---------|
| `reset` | Client -> Server | Reset environment |
| `step` | Client -> Server | Execute action |
| `state` | Client -> Server | Get current state |
| `close` | Client -> Server | Close session |
| `mcp` | Client -> Server | Direct MCP JSON-RPC |
| `observation` | Server -> Client | Action result |
| `error` | Server -> Client | Error response |

### MCP via WebSocket

```json
// Request
{"type": "mcp", "data": {"jsonrpc": "2.0", "method": "tools/list", "id": 1}}

// Response
{"type": "mcp", "data": {"jsonrpc": "2.0", "result": {"tools": [...]}, "id": 1}}
```

## Error Handling

Tool errors are categorized by `ToolErrorType`:

| Error Type | When |
|------------|------|
| `EXECUTION_ERROR` | Tool ran but failed |
| `INVALID_ARGS` | Invalid arguments provided |
| `TRANSPORT_ERROR` | Communication failure |
| `TOOL_NOT_FOUND` | Tool doesn't exist |
| `TIMEOUT` | Operation timed out (default: 30s) |

## Related Files

| File | Purpose |
|------|---------|
| `src/openenv/core/mcp_client.py` | Client classes for MCP interactions |
| `src/openenv/core/env_server/mcp_environment.py` | MCPEnvironment base class |
| `src/openenv/core/env_server/mcp_types.py` | MCP type definitions |
| `src/openenv/core/env_server/http_server.py` | HTTP/WebSocket server with MCP support |
| `envs/echo_env/server/echo_environment.py` | Reference MCP environment |
| `examples/echo_mcp_demo.py` | Demo script for MCP usage |
| `tests/core/test_mcp/` | MCP integration tests |
