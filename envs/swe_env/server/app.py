"""FastAPI application for the SWE Environment.

This module creates an HTTP server that exposes the SWEEnvironment
over HTTP and WebSocket endpoints, compatible with MCPToolClient.

Usage:
    # Development (with auto-reload):
    uvicorn server.app:app --reload --host 0.0.0.0 --port 8000

    # Production:
    uvicorn server.app:app --host 0.0.0.0 --port 8000 --workers 4

    # Or run directly:
    uv run --project . server
"""

try:
    from openenv.core.env_server.http_server import create_app
    from openenv.core.env_server.mcp_types import CallToolAction, CallToolObservation
    from .environment import SWEEnvironment
except ImportError:
    from openenv.core.env_server.http_server import create_app
    from openenv.core.env_server.mcp_types import CallToolAction, CallToolObservation
    from server.environment import SWEEnvironment

app = create_app(
    SWEEnvironment.with_default_tools,
    CallToolAction,
    CallToolObservation,
    env_name="swe_env",
)


def main():
    """Entry point for direct execution via uv run or python -m."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
