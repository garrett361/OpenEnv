"""SWE Environment Client.

This module provides the client for connecting to an SWE Environment server.
SWEEnv extends MCPToolClient to provide tool-calling style interactions.

Example:
    >>> with SWEEnv(base_url="http://localhost:8000") as env:
    ...     env.reset()
    ...
    ...     # Discover tools
    ...     tools = env.list_tools()
    ...     print([t.name for t in tools])  # ['bash', 'file_editor']
    ...
    ...     # Call tools
    ...     result = env.call_tool("bash", command="ls")
    ...     print(result)
"""

from openenv.core.mcp_client import MCPToolClient


class SWEEnv(MCPToolClient):
    """Client for the SWE Environment.

    Inherits all functionality from MCPToolClient:
    - ``list_tools()``: Discover available tools
    - ``call_tool(name, **kwargs)``: Call a tool by name
    - ``reset(**kwargs)``: Reset the environment
    - ``step(action)``: Execute an action

    Example:
        >>> with SWEEnv(base_url="http://localhost:8000") as env:
        ...     env.reset()
        ...     tools = env.list_tools()
        ...     result = env.call_tool("bash", command="echo hello")

    Example with Docker:
        >>> env = SWEEnv.from_docker_image("swe-env:latest")
        >>> try:
        ...     env.reset()
        ...     result = env.call_tool("bash", command="ls")
        ... finally:
        ...     env.close()
    """

    pass
