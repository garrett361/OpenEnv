"""ToolModule protocol for swe_env.

Each tool category (bash, file_editor, etc.) implements this protocol to
register its MCP tools with a shared FastMCP server.
"""

from typing import Protocol, runtime_checkable

from fastmcp import FastMCP


@runtime_checkable
class ToolModule(Protocol):
    """Protocol that all tool modules must satisfy.

    Methods:
        register: Register MCP tools with the shared FastMCP server.
        reset: Reset any internal state (called on episode reset).
        cleanup: Release resources (called on environment close).
    """

    def register(self, mcp: FastMCP) -> None: ...

    def reset(self) -> None: ...

    def cleanup(self) -> None: ...
