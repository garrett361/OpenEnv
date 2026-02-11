"""Stage 1 tests: Workspace, ToolModule protocol, SWEEnvironment skeleton."""

from pathlib import Path

import pytest
from fastmcp import FastMCP

from swe_env.models import SWEState
from swe_env.server.workspace import Workspace
from swe_env.server.tool_module import ToolModule
from swe_env.server.environment import SWEEnvironment
from openenv.core.env_server.mcp_types import ListToolsAction
from openenv.core.env_server.types import Action


class DummyToolModule:
    """Minimal implementation satisfying the ToolModule protocol."""

    def __init__(self):
        self.registered = False
        self.reset_called = False
        self.cleanup_called = False

    def register(self, mcp: FastMCP) -> None:
        self.registered = True

    def reset(self) -> None:
        self.reset_called = True

    def cleanup(self) -> None:
        self.cleanup_called = True


class TestWorkspace:
    def test_path_exists_after_init(self):
        ws = Workspace()
        assert ws.path.exists()
        assert ws.is_active
        ws.close()

    def test_reset_clears_contents(self):
        ws = Workspace()
        (ws.path / "file.txt").write_text("hello")
        (ws.path / "subdir").mkdir()
        (ws.path / "subdir" / "nested.txt").write_text("nested")

        ws.reset()

        assert ws.path.exists()
        assert list(ws.path.iterdir()) == []
        ws.close()

    def test_reset_returns_path(self):
        ws = Workspace()
        result = ws.reset()
        assert result == ws.path
        ws.close()

    def test_close_removes_directory(self):
        ws = Workspace()
        path = ws.path
        ws.close()
        assert not path.exists()

    def test_two_workspaces_have_different_paths(self):
        ws1 = Workspace()
        ws2 = Workspace()
        assert ws1.path != ws2.path
        ws1.close()
        ws2.close()

    def test_is_active_false_after_close(self):
        ws = Workspace()
        ws.close()
        assert not ws.is_active


class TestToolModuleProtocol:
    def test_dummy_satisfies_protocol(self):
        assert isinstance(DummyToolModule(), ToolModule)

    def test_non_conforming_class_fails(self):
        class Bad:
            pass

        assert not isinstance(Bad(), ToolModule)


class TestSWEState:
    def test_default_fields(self):
        s = SWEState()
        assert s.workspace_path == ""
        assert s.available_tools == []
        assert s.step_count == 0

    def test_custom_fields(self):
        s = SWEState(
            episode_id="ep-1",
            workspace_path="/tmp/ws",
            available_tools=["bash", "git"],
        )
        assert s.workspace_path == "/tmp/ws"
        assert s.available_tools == ["bash", "git"]
        assert s.episode_id == "ep-1"


class TestSWEEnvironmentSkeleton:
    def test_reset_returns_observation(self):
        env = SWEEnvironment.with_default_tools()
        obs = env.reset()

        assert obs.done is False
        assert obs.metadata["status"] == "ready"
        assert "workspace_path" in obs.metadata
        env.close()

    def test_state_tracks_step_count(self):
        env = SWEEnvironment.with_default_tools()
        env.reset()
        assert env.state.step_count == 0

        env.step(ListToolsAction())
        assert env.state.step_count == 1

        env.step(ListToolsAction())
        assert env.state.step_count == 2
        env.close()

    def test_reset_resets_step_count(self):
        env = SWEEnvironment.with_default_tools()
        env.reset()
        env.step(ListToolsAction())
        env.step(ListToolsAction())

        env.reset()
        assert env.state.step_count == 0
        env.close()

    def test_state_has_workspace_path(self):
        env = SWEEnvironment.with_default_tools()
        obs = env.reset()

        assert env.state.workspace_path == obs.metadata["workspace_path"]
        assert env.state.workspace_path != ""
        env.close()

    def test_close_destroys_workspace(self):
        env = SWEEnvironment.with_default_tools()
        env.reset()
        ws_path = env.state.workspace_path
        env.close()

        assert not Path(ws_path).exists()

    def test_list_tools_empty_without_modules(self):
        env = SWEEnvironment.with_default_tools()
        env.reset()
        obs = env.step(ListToolsAction())

        assert obs.tools == []
        env.close()

    def test_unknown_action_returns_error(self):
        env = SWEEnvironment.with_default_tools()
        env.reset()
        obs = env.step(Action())

        assert "error" in obs.metadata
        env.close()

    def test_tool_module_lifecycle(self):
        module = DummyToolModule()
        ws = Workspace()
        env = SWEEnvironment(workspace=ws, tool_modules=[module])

        assert module.registered

        env.reset()
        assert module.reset_called

        env.close()
        assert module.cleanup_called

    def test_with_default_tools_produces_independent_instances(self):
        env1 = SWEEnvironment.with_default_tools()
        env2 = SWEEnvironment.with_default_tools()
        env1.reset()
        env2.reset()

        assert env1.state.workspace_path != env2.state.workspace_path

        env1.close()
        env2.close()

    def test_reset_clears_workspace_files(self):
        env = SWEEnvironment.with_default_tools()
        env.reset()

        ws = Path(env.state.workspace_path)
        (ws / "leftover.txt").write_text("stale")

        env.reset()

        ws_new = Path(env.state.workspace_path)
        assert list(ws_new.iterdir()) == []
        env.close()

    def test_custom_episode_id(self):
        env = SWEEnvironment.with_default_tools()
        env.reset(episode_id="my-episode")
        assert env.state.episode_id == "my-episode"
        env.close()
