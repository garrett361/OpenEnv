"""Tests for swe_env Workspace."""

from swe_env.server.workspace import Workspace


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
