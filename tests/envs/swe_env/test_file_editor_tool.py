"""Stage 3 tests: FileEditorToolModule."""

import json
from pathlib import Path

import pytest

from swe_env.server.tools.file_editor_tool import FileEditorToolModule
from swe_env.server.tool_module import ToolModule
from swe_env.server.workspace import Workspace
from swe_env.server.environment import SWEEnvironment
from openenv.core.env_server.mcp_types import (
    CallToolAction,
    ListToolsAction,
)


@pytest.fixture()
def env():
    """SWEEnvironment with only FileEditorToolModule for isolated unit tests."""
    ws = Workspace()
    get_workspace = lambda: ws.path
    modules = [FileEditorToolModule(get_workspace=get_workspace)]
    e = SWEEnvironment(workspace=ws, tool_modules=modules)
    e.reset()
    yield e
    e.close()


def _edit(env, **kwargs):
    obs = env.step(CallToolAction(tool_name="file_editor", arguments=kwargs))
    result = obs.result
    if hasattr(result, "data"):
        return result.data
    return json.loads(result)


def _create_file(env, rel_path, content):
    ws = Path(env.state.workspace_path)
    p = ws / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


class TestFileEditorProtocol:
    def test_satisfies_tool_module(self):
        ws = Workspace()
        module = FileEditorToolModule(get_workspace=lambda: ws.path)
        assert isinstance(module, ToolModule)
        ws.close()


class TestView:
    def test_view_file(self, env):
        p = _create_file(env, "hello.py", "line1\nline2\nline3\n")
        data = _edit(env, command="view", path=str(p))
        assert data["exit_code"] == 0
        assert "line1" in data["output"]
        assert "line2" in data["output"]

    def test_view_with_line_numbers(self, env):
        p = _create_file(env, "nums.py", "a\nb\nc\n")
        data = _edit(env, command="view", path=str(p))
        assert "     1\t" in data["output"]

    def test_view_range(self, env):
        p = _create_file(env, "range.py", "a\nb\nc\nd\ne\n")
        data = _edit(env, command="view", path=str(p), view_range="2,4")
        assert data["exit_code"] == 0
        assert "b" in data["output"]
        assert "c" in data["output"]
        assert "d" in data["output"]
        assert "     2\t" in data["output"]

    def test_view_directory(self, env):
        ws = Path(env.state.workspace_path)
        (ws / "subdir").mkdir()
        (ws / "file.txt").write_text("hi")
        data = _edit(env, command="view", path=str(ws))
        assert data["exit_code"] == 0
        assert "file.txt" in data["output"]
        assert "subdir/" in data["output"]

    def test_view_nonexistent(self, env):
        ws = Path(env.state.workspace_path)
        data = _edit(env, command="view", path=str(ws / "nope.txt"))
        assert data["exit_code"] == 1
        assert "does not exist" in data["output"]


class TestCreate:
    def test_create_new_file(self, env):
        ws = Path(env.state.workspace_path)
        target = ws / "new.py"
        data = _edit(env, command="create", path=str(target), file_text="hello\n")
        assert data["exit_code"] == 0
        assert "created successfully" in data["output"]

    def test_create_existing_file_fails(self, env):
        p = _create_file(env, "exists.py", "old")
        data = _edit(env, command="create", path=str(p), file_text="new")
        assert data["exit_code"] == 1
        assert "already exists" in data["output"]

    def test_create_file_contents(self, env):
        ws = Path(env.state.workspace_path)
        target = ws / "content.py"
        _edit(env, command="create", path=str(target), file_text="print('hi')\n")
        assert target.read_text() == "print('hi')\n"

    def test_create_with_nested_dirs(self, env):
        ws = Path(env.state.workspace_path)
        target = ws / "a" / "b" / "c.py"
        data = _edit(env, command="create", path=str(target), file_text="nested\n")
        assert data["exit_code"] == 0
        assert target.exists()


class TestStrReplace:
    def test_replace_unique(self, env):
        p = _create_file(env, "rep.py", "foo = 1\nbar = 2\n")
        data = _edit(
            env,
            command="str_replace",
            path=str(p),
            old_str="foo = 1",
            new_str="foo = 42",
        )
        assert data["exit_code"] == 0
        assert "foo = 42" in p.read_text()

    def test_not_found(self, env):
        p = _create_file(env, "nf.py", "hello world\n")
        data = _edit(
            env,
            command="str_replace",
            path=str(p),
            old_str="missing",
            new_str="found",
        )
        assert data["exit_code"] == 1
        assert "did not appear verbatim" in data["output"]

    def test_multiple_matches(self, env):
        p = _create_file(env, "dup.py", "test\ntest\n")
        data = _edit(
            env,
            command="str_replace",
            path=str(p),
            old_str="test",
            new_str="replaced",
        )
        assert data["exit_code"] == 1
        assert "Multiple occurrences" in data["output"]

    def test_same_old_new(self, env):
        p = _create_file(env, "same.py", "foo\n")
        data = _edit(
            env,
            command="str_replace",
            path=str(p),
            old_str="foo",
            new_str="foo",
        )
        assert data["exit_code"] == 1
        assert "must be different" in data["output"]


class TestInsert:
    def test_insert_after_line(self, env):
        p = _create_file(env, "ins.py", "line1\nline3\n")
        data = _edit(
            env,
            command="insert",
            path=str(p),
            insert_line=1,
            new_str="line2",
        )
        assert data["exit_code"] == 0
        assert p.read_text() == "line1\nline2\nline3\n"

    def test_insert_at_zero(self, env):
        p = _create_file(env, "pre.py", "second\n")
        data = _edit(
            env,
            command="insert",
            path=str(p),
            insert_line=0,
            new_str="first",
        )
        assert data["exit_code"] == 0
        content = p.read_text()
        assert content.startswith("first\n")

    def test_insert_after_last_line(self, env):
        p = _create_file(env, "app.py", "a\nb")
        lines = p.read_text().split("\n")
        data = _edit(
            env,
            command="insert",
            path=str(p),
            insert_line=len(lines),
            new_str="c",
        )
        assert data["exit_code"] == 0
        assert p.read_text() == "a\nb\nc"

    def test_insert_invalid_line(self, env):
        p = _create_file(env, "bad.py", "one\n")
        data = _edit(
            env,
            command="insert",
            path=str(p),
            insert_line=999,
            new_str="nope",
        )
        assert data["exit_code"] == 1
        assert "Invalid insert_line" in data["output"]


class TestUndoEdit:
    def test_undo_str_replace(self, env):
        p = _create_file(env, "undo1.py", "original\n")
        _edit(
            env,
            command="str_replace",
            path=str(p),
            old_str="original",
            new_str="changed",
        )
        assert "changed" in p.read_text()
        data = _edit(env, command="undo_edit", path=str(p))
        assert data["exit_code"] == 0
        assert p.read_text() == "original\n"

    def test_undo_insert(self, env):
        p = _create_file(env, "undo2.py", "a\nb\n")
        original = p.read_text()
        _edit(env, command="insert", path=str(p), insert_line=1, new_str="x")
        data = _edit(env, command="undo_edit", path=str(p))
        assert data["exit_code"] == 0
        assert p.read_text() == original

    def test_undo_no_history(self, env):
        p = _create_file(env, "nohist.py", "content\n")
        data = _edit(env, command="undo_edit", path=str(p))
        assert data["exit_code"] == 1
        assert "No undo history" in data["output"]

    def test_undo_stack_order(self, env):
        p = _create_file(env, "stack.py", "v1\n")
        _edit(
            env,
            command="str_replace",
            path=str(p),
            old_str="v1",
            new_str="v2",
        )
        _edit(
            env,
            command="str_replace",
            path=str(p),
            old_str="v2",
            new_str="v3",
        )
        assert "v3" in p.read_text()

        _edit(env, command="undo_edit", path=str(p))
        assert "v2" in p.read_text()

        _edit(env, command="undo_edit", path=str(p))
        assert p.read_text() == "v1\n"


class TestReset:
    def test_reset_clears_undo_history(self, env):
        p = _create_file(env, "reset.py", "before\n")
        _edit(
            env,
            command="str_replace",
            path=str(p),
            old_str="before",
            new_str="after",
        )
        env.reset()

        p2 = _create_file(env, "reset.py", "new content\n")
        data = _edit(env, command="undo_edit", path=str(p2))
        assert data["exit_code"] == 1
        assert "No undo history" in data["output"]


class TestIntegration:
    def test_list_tools_includes_both(self):
        e = SWEEnvironment.with_default_tools()
        e.reset()
        obs = e.step(ListToolsAction())
        tool_names = sorted(t.name for t in obs.tools)
        assert tool_names == ["bash", "file_editor"]
        e.close()

    def test_full_workflow(self):
        e = SWEEnvironment.with_default_tools()
        e.reset()
        ws = Path(e.state.workspace_path)
        target = ws / "app.py"

        data = _edit(
            e,
            command="create",
            path=str(target),
            file_text="def greet():\n    return 'hello'\n",
        )
        assert data["exit_code"] == 0

        data = _edit(e, command="view", path=str(target))
        assert data["exit_code"] == 0
        assert "hello" in data["output"]

        data = _edit(
            e,
            command="str_replace",
            path=str(target),
            old_str="return 'hello'",
            new_str="return 'goodbye'",
        )
        assert data["exit_code"] == 0
        assert "goodbye" in target.read_text()

        data = _edit(e, command="view", path=str(target))
        assert "goodbye" in data["output"]

        data = _edit(e, command="undo_edit", path=str(target))
        assert data["exit_code"] == 0
        assert "hello" in target.read_text()

        data = _edit(e, command="view", path=str(target))
        assert "hello" in data["output"]

        e.close()
