"""SWEEnvironment -- MCP environment with modular tools and a shared workspace."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from fastmcp import FastMCP

from openenv.core.env_server.mcp_environment import MCPEnvironment
from openenv.core.env_server.types import Action, Observation

from swe_env.models import SWEBenchInstance, SWEState
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
        self._instance: Optional[SWEBenchInstance] = None
        self._base_commit: str = ""
        self._repo_path: Optional[Path] = None

    def reset(
        self,
        seed: Optional[int] = None,
        episode_id: Optional[str] = None,
        instance: Optional[Union[Dict[str, Any], SWEBenchInstance]] = None,
        **kwargs: Any,
    ) -> Observation:
        self._workspace.reset()

        for module in self._tool_modules:
            module.reset()

        self._instance = None
        self._base_commit = ""
        self._repo_path = None

        if instance is not None:
            self._setup_instance(instance)

        tool_names = list(self.get_callables().keys())

        self._state = SWEState(
            episode_id=episode_id or str(uuid4()),
            step_count=0,
            workspace_path=str(self._workspace.path),
            available_tools=tool_names,
            instance_id=self._instance.instance_id if self._instance else "",
            problem_statement=self._instance.problem_statement
            if self._instance
            else "",
            repo_path=str(self._repo_path) if self._repo_path else "",
        )

        metadata: Dict[str, Any] = {
            "status": "ready",
            "workspace_path": str(self._workspace.path),
            "available_tools": tool_names,
        }
        if self._instance:
            metadata["instance_id"] = self._instance.instance_id
            metadata["problem_statement"] = self._instance.problem_statement

        return Observation(
            done=False,
            reward=0.0,
            metadata=metadata,
        )

    def _setup_instance(
        self, instance: Union[Dict[str, Any], SWEBenchInstance]
    ) -> None:
        if isinstance(instance, dict):
            instance = SWEBenchInstance(**instance)
        self._instance = instance
        self._base_commit = instance.base_commit

        repo = instance.repo
        if not repo.startswith(("http://", "https://", "/")):
            repo_url = f"https://github.com/{repo}.git"
        else:
            repo_url = repo

        repo_dir = self._workspace.path / "repo"

        subprocess.run(
            ["git", "clone", repo_url, str(repo_dir)],
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )

        subprocess.run(
            ["git", "checkout", instance.base_commit],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )

        if instance.test_patch:
            patch_file = self._workspace.path / "test_patch.diff"
            patch_file.write_text(instance.test_patch)
            subprocess.run(
                ["git", "apply", str(patch_file)],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
            )
            patch_file.unlink()

        self._repo_path = repo_dir

    def get_patch(self) -> str:
        """Extract the agent's changes as a git diff from base_commit.

        Returns the diff as a string. Empty string if no changes or no repo.
        """
        if not self._repo_path or not self._repo_path.exists() or not self._base_commit:
            return ""

        subprocess.run(
            ["git", "add", "-A"],
            cwd=self._repo_path,
            capture_output=True,
            text=True,
            timeout=60,
        )

        result = subprocess.run(
            ["git", "diff", "--cached", self._base_commit],
            cwd=self._repo_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.stdout

    def evaluate(self, test_command: str = "") -> Dict[str, Any]:
        """Run tests and return evaluation results.

        Args:
            test_command: Shell command to run tests. If empty, uses
                'python -m pytest' in the repo directory.

        Returns:
            Dict with keys: exit_code, stdout, stderr, resolved (bool).
        """
        if not self._repo_path or not self._repo_path.exists():
            return {
                "exit_code": 1,
                "stdout": "",
                "stderr": "No repo available for evaluation",
                "resolved": False,
            }

        cmd = test_command if test_command else "python -m pytest"
        result = subprocess.run(
            ["bash", "-c", cmd],
            cwd=self._repo_path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "resolved": result.returncode == 0,
        }

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

        def get_workspace() -> Any:
            return workspace.path

        from swe_env.server.tools.bash_tool import BashToolModule
        from swe_env.server.tools.file_editor_tool import FileEditorToolModule

        tool_modules: List[ToolModule] = [
            BashToolModule(get_workspace=get_workspace),
            FileEditorToolModule(get_workspace=get_workspace),
        ]

        return cls(workspace=workspace, tool_modules=tool_modules)
