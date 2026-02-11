"""Bash tool module for swe_env.

Provides a ``bash`` MCP tool that runs commands via ``subprocess.run``
in the workspace directory.
"""

import subprocess
from pathlib import Path
from typing import Any, Callable, Dict

from fastmcp import FastMCP


class BashToolModule:
    """Runs bash commands in the workspace via subprocess.

    Each invocation is stateless -- a fresh ``bash -c`` process is spawned
    per call, with ``cwd`` set to the workspace directory.
    """

    def __init__(
        self,
        get_workspace: Callable[[], Path],
        default_timeout: int = 120,
    ) -> None:
        self._get_workspace = get_workspace
        self._default_timeout = default_timeout

    def register(self, mcp: FastMCP) -> None:
        get_workspace = self._get_workspace
        default_timeout = self._default_timeout

        @mcp.tool()
        def bash(command: str, timeout: int = 0) -> Dict[str, Any]:
            """Run a bash command in the workspace directory.

            Args:
                command: The bash command to execute.
                timeout: Maximum seconds to wait. 0 uses the module default.

            Returns:
                Dict with stdout, stderr, and exit_code.
            """
            effective_timeout = timeout if timeout > 0 else default_timeout
            try:
                result = subprocess.run(
                    ["bash", "-c", command],
                    cwd=get_workspace(),
                    capture_output=True,
                    text=True,
                    timeout=effective_timeout,
                )
                return {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.returncode,
                }
            except subprocess.TimeoutExpired:
                return {
                    "stdout": "",
                    "stderr": f"Command timed out after {effective_timeout}s",
                    "exit_code": 124,
                }

    def reset(self) -> None:
        pass

    def cleanup(self) -> None:
        pass
