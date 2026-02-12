"""Stage 2 tests: BashToolModule."""

import json
from pathlib import Path

import pytest

from swe_env.server.tools.bash_tool import BashToolModule
from swe_env.server.tool_module import ToolModule
from swe_env.server.workspace import Workspace
from swe_env.server.environment import SWEEnvironment
from openenv.core.env_server.mcp_types import (
    CallToolAction,
    ListToolsAction,
)


@pytest.fixture()
def env():
    """SWEEnvironment with only BashToolModule for isolated unit tests."""
    ws = Workspace()
    get_workspace = lambda: ws.path
    modules = [BashToolModule(get_workspace=get_workspace)]
    e = SWEEnvironment(workspace=ws, tool_modules=modules)
    e.reset()
    yield e
    e.close()


def _bash(env, command, timeout=0):
    args = {"command": command}
    if timeout:
        args["timeout"] = timeout
    obs = env.step(CallToolAction(tool_name="bash", arguments=args))
    result = obs.result
    if hasattr(result, "data"):
        return result.data
    return json.loads(result)


class TestBashToolModuleProtocol:
    def test_satisfies_tool_module(self):
        ws = Workspace()
        module = BashToolModule(get_workspace=lambda: ws.path)
        assert isinstance(module, ToolModule)
        ws.close()


class TestBashToolDirect:
    def test_echo(self, env):
        data = _bash(env, "echo hello")
        assert data["stdout"] == "hello\n"
        assert data["exit_code"] == 0

    def test_failed_command(self, env):
        data = _bash(env, "false")
        assert data["exit_code"] == 1

    def test_timeout(self, env):
        data = _bash(env, "sleep 30", timeout=1)
        assert data["exit_code"] == 124

    def test_stderr(self, env):
        data = _bash(env, "echo err >&2")
        assert "err" in data["stderr"]

    def test_working_directory(self, env):
        data = _bash(env, "pwd")
        assert data["stdout"].strip() == env.state.workspace_path

    def test_file_creation(self, env):
        _bash(env, "touch foo.txt")
        assert (Path(env.state.workspace_path) / "foo.txt").exists()


class TestBashToolIntegration:
    def test_list_tools_includes_bash(self):
        env = SWEEnvironment.with_default_tools()
        env.reset()
        obs = env.step(ListToolsAction())
        tool_names = [t.name for t in obs.tools]
        assert "bash" in tool_names
        env.close()

    def test_call_bash_echo(self):
        env = SWEEnvironment.with_default_tools()
        env.reset()
        obs = env.step(CallToolAction(tool_name="bash", arguments={"command": "echo hi"}))
        assert obs.result is not None
        assert "hi" in str(obs.result)
        env.close()

    def test_call_bash_creates_file_in_workspace(self):
        env = SWEEnvironment.with_default_tools()
        env.reset()
        ws = Path(env.state.workspace_path)
        env.step(
            CallToolAction(
                tool_name="bash", arguments={"command": "echo content > test.txt"}
            )
        )
        assert (ws / "test.txt").exists()
        assert "content" in (ws / "test.txt").read_text()
        env.close()

    def test_reset_clears_bash_created_files(self):
        env = SWEEnvironment.with_default_tools()
        env.reset()
        ws = Path(env.state.workspace_path)
        env.step(
            CallToolAction(tool_name="bash", arguments={"command": "touch artifact.txt"})
        )
        assert (ws / "artifact.txt").exists()

        env.reset()
        ws_new = Path(env.state.workspace_path)
        assert list(ws_new.iterdir()) == []
        env.close()
