"""Data models for swe_env."""

from typing import List

from pydantic import Field

from openenv.core.env_server.types import State


class SWEState(State):
    """Environment state extended with workspace metadata."""

    workspace_path: str = Field(default="", description="Path to the workspace directory")
    available_tools: List[str] = Field(
        default_factory=list, description="Names of registered MCP tools"
    )
