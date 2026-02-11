"""SWEEnvironment -- MCP environment with modular tools and a shared workspace."""

from __future__ import annotations

from typing import Any, Callable, List, Optional
from uuid import uuid4

from fastmcp import FastMCP

from openenv.core.env_server.mcp_environment import MCPEnvironment
from openenv.core.env_server.types import Action, Observation

from swe_env.models import SWEState
from swe_env.server.tool_module import ToolModule
from swe_env.server.workspace import Workspace


class SWEEnvironment(MCPEnvironment):
    """Sandboxed workspace environment exposing bash, git, and python via MCP.

    Each instance owns a Workspace (temp directory) and a set of ToolModules
    that register their MCP tools with a shared FastMCP server. The
    MCPEnvironment base class handles ListToolsAction / CallToolAction routing.

    Use the ``with_default_tools`` classmethod as the factory callable passed
    to ``create_app()``.
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(
        self,
        workspace: Workspace,
        tool_modules: List[ToolModule],
    ) -> None:
        mcp = FastMCP("swe_env")

        self._workspace = workspace
        self._tool_modules = tool_modules

        for module in self._tool_modules:
            module.register(mcp)

        super().__init__(mcp)

        self._state = SWEState(episode_id=str(uuid4()), step_count=0)

    def reset(
        self,
        seed: Optional[int] = None,
        episode_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Observation:
        self._workspace.reset()

        for module in self._tool_modules:
            module.reset()

        tool_names = list(self.get_callables().keys())

        self._state = SWEState(
            episode_id=episode_id or str(uuid4()),
            step_count=0,
            workspace_path=str(self._workspace.path),
            available_tools=tool_names,
        )

        return Observation(
            done=False,
            reward=0.0,
            metadata={
                "status": "ready",
                "workspace_path": str(self._workspace.path),
                "available_tools": tool_names,
            },
        )

    def step(
        self,
        action: Action,
        timeout_s: Optional[float] = None,
        **kwargs: Any,
    ) -> Observation:
        self._state.step_count += 1
        return super().step(action, timeout_s=timeout_s, **kwargs)

    def _step_impl(
        self,
        action: Action,
        timeout_s: Optional[float] = None,
        **kwargs: Any,
    ) -> Observation:
        return Observation(
            done=False,
            reward=0.0,
            metadata={
                "error": f"Unknown action type: {type(action).__name__}. "
                "Use ListToolsAction or CallToolAction for MCP interactions."
            },
        )

    @property
    def state(self) -> SWEState:
        return self._state

    def close(self) -> None:
        for module in self._tool_modules:
            module.cleanup()
        self._workspace.close()
        super().close()

    @classmethod
    def with_default_tools(cls) -> "SWEEnvironment":
        """Factory that creates a fully-wired SWEEnvironment.

        Intended as the callable passed to ``create_app()``. Each call
        produces an independent instance with its own workspace and tools.
        """
        workspace = Workspace()
        get_workspace: Callable[[], Any] = lambda: workspace.path

        from swe_env.server.tools.bash_tool import BashToolModule

        tool_modules: List[ToolModule] = [
            BashToolModule(get_workspace=get_workspace),
        ]

        return cls(workspace=workspace, tool_modules=tool_modules)
