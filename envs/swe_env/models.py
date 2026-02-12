"""Data models for swe_env."""

from typing import List

from pydantic import BaseModel, Field

from openenv.core.env_server.types import State


class SWEBenchInstance(BaseModel):
    """A single SWE-Bench task instance."""

    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    test_patch: str = ""
    version: str = ""


class SWEState(State):
    """Environment state extended with workspace metadata."""

    workspace_path: str = Field(
        default="", description="Path to the workspace directory"
    )
    available_tools: List[str] = Field(
        default_factory=list, description="Names of registered MCP tools"
    )
    instance_id: str = ""
    problem_statement: str = ""
    repo_path: str = ""
