"""Stage 5 integration tests: end-to-end workflows, isolation, concurrency, CodeAct."""

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

from swe_env.server.environment import SWEEnvironment
from openenv.core.env_server.mcp_types import CallToolAction


@pytest.fixture()
def local_repo(tmp_path):
    """Create a local git repo with a known bug to serve as the 'remote'."""
    repo = tmp_path / "test_repo"
    repo.mkdir()

    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, capture_output=True, check=True,
    )

    buggy_file = repo / "calc.py"
    buggy_file.write_text(
        textwrap.dedent("""\
            def add(a, b):
                return a - b  # BUG: should be a + b
        """)
    )

    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit with bug"],
        cwd=repo, capture_output=True, check=True,
    )

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    base_commit = result.stdout.strip()

    return repo, base_commit


@pytest.fixture()
def second_local_repo(tmp_path):
    """A second independent repo for multi-episode / concurrency tests."""
    repo = tmp_path / "test_repo_2"
    repo.mkdir()

    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, capture_output=True, check=True,
    )

    buggy_file = repo / "math_ops.py"
    buggy_file.write_text(
        textwrap.dedent("""\
            def multiply(a, b):
                return a + b  # BUG: should be a * b
        """)
    )

    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit with multiply bug"],
        cwd=repo, capture_output=True, check=True,
    )

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    base_commit = result.stdout.strip()

    return repo, base_commit


@pytest.fixture()
def test_patch_content():
    return textwrap.dedent("""\
        diff --git a/test_calc.py b/test_calc.py
        new file mode 100644
        --- /dev/null
        +++ b/test_calc.py
        @@ -0,0 +1,5 @@
        +from calc import add
        +
        +
        +def test_add():
        +    assert add(2, 3) == 5
    """)


def _make_instance(local_repo, test_patch="", instance_id="test__calc-001"):
    repo_path, base_commit = local_repo
    return {
        "instance_id": instance_id,
        "repo": str(repo_path),
        "base_commit": base_commit,
        "problem_statement": "Fix the function",
        "test_patch": test_patch,
    }


def _bash(env, command, timeout=0):
    args = {"command": command}
    if timeout:
        args["timeout"] = timeout
    obs = env.step(CallToolAction(tool_name="bash", arguments=args))
    result = obs.result
    if hasattr(result, "data"):
        return result.data
    return json.loads(result)


def _edit(env, **kwargs):
    obs = env.step(CallToolAction(tool_name="file_editor", arguments=kwargs))
    result = obs.result
    if hasattr(result, "data"):
        return result.data
    return json.loads(result)


class TestToolCompleteness:
    def test_list_tools_returns_bash_and_file_editor(self):
        env = SWEEnvironment.with_default_tools()
        try:
            env.reset()
            tool_names = sorted(env.state.available_tools)
            assert tool_names == ["bash", "file_editor"]
        finally:
            env.close()

    def test_callables_match_tool_names(self):
        env = SWEEnvironment.with_default_tools()
        try:
            env.reset()
            callables = env.get_callables()
            assert sorted(callables.keys()) == ["bash", "file_editor"]
        finally:
            env.close()


class TestCodeActMode:
    def test_get_callables_returns_functions(self):
        env = SWEEnvironment.with_default_tools()
        try:
            env.reset()
            callables = env.get_callables()
            assert callable(callables["bash"])
            assert callable(callables["file_editor"])
        finally:
            env.close()

    def test_codeact_bash_execution(self):
        env = SWEEnvironment.with_default_tools()
        try:
            env.reset()
            bash = env.get_callables()["bash"]
            result = bash(command="echo hello from codeact")
            data = result.data if hasattr(result, "data") else result
            assert data["exit_code"] == 0
            assert "hello from codeact" in data["stdout"]
        finally:
            env.close()

    def test_codeact_file_editor_execution(self):
        env = SWEEnvironment.with_default_tools()
        try:
            env.reset()
            ws = Path(env.state.workspace_path)
            file_editor = env.get_callables()["file_editor"]
            result = file_editor(
                command="create",
                path=str(ws / "test.txt"),
                file_text="hello\n",
            )
            data = result.data if hasattr(result, "data") else result
            assert data["exit_code"] == 0
            assert (ws / "test.txt").read_text() == "hello\n"
        finally:
            env.close()


class TestFullSWEBenchWorkflow:
    def test_reset_explore_fix_patch_evaluate(self, local_repo, test_patch_content):
        env = SWEEnvironment.with_default_tools()
        try:
            instance = _make_instance(local_repo, test_patch=test_patch_content)
            obs = env.reset(instance=instance)
            assert obs.metadata["status"] == "ready"
            assert obs.metadata["instance_id"] == "test__calc-001"

            repo_dir = Path(env.state.repo_path)

            data = _bash(env, f"cat {repo_dir / 'calc.py'}")
            assert "a - b" in data["stdout"]

            data = _bash(env, f"ls {repo_dir}")
            assert "test_calc.py" in data["stdout"]

            calc_file = repo_dir / "calc.py"
            data = _edit(
                env,
                command="str_replace",
                path=str(calc_file),
                old_str="return a - b  # BUG: should be a + b",
                new_str="return a + b",
            )
            assert data["exit_code"] == 0

            data = _edit(env, command="view", path=str(calc_file))
            assert "a + b" in data["output"]

            patch = env.get_patch()
            assert "a + b" in patch
            assert "a - b" in patch

            result = env.evaluate(test_command="python -m pytest test_calc.py -v")
            assert result["resolved"] is True
            assert result["exit_code"] == 0
        finally:
            env.close()


class TestWorkspaceIsolation:
    def test_files_from_previous_episode_gone_after_reset(self, local_repo):
        env = SWEEnvironment.with_default_tools()
        try:
            instance = _make_instance(local_repo)
            env.reset(instance=instance)
            repo_dir = Path(env.state.repo_path)
            assert (repo_dir / "calc.py").exists()

            env.reset()
            ws = Path(env.state.workspace_path)
            assert list(ws.iterdir()) == []
        finally:
            env.close()


class TestMultipleEpisodes:
    def test_sequential_episodes_with_different_instances(
        self, local_repo, second_local_repo
    ):
        env = SWEEnvironment.with_default_tools()
        try:
            instance_1 = _make_instance(local_repo, instance_id="episode-1")
            env.reset(instance=instance_1)
            assert env.state.instance_id == "episode-1"
            repo_dir_1 = Path(env.state.repo_path)
            assert (repo_dir_1 / "calc.py").exists()

            instance_2 = _make_instance(second_local_repo, instance_id="episode-2")
            env.reset(instance=instance_2)
            assert env.state.instance_id == "episode-2"
            repo_dir_2 = Path(env.state.repo_path)
            assert (repo_dir_2 / "math_ops.py").exists()
            assert not (repo_dir_2 / "calc.py").exists()
        finally:
            env.close()


class TestConcurrentInstances:
    def test_two_environments_no_cross_contamination(self, local_repo, second_local_repo):
        env1 = SWEEnvironment.with_default_tools()
        env2 = SWEEnvironment.with_default_tools()
        try:
            instance_1 = _make_instance(local_repo, instance_id="env1-task")
            env1.reset(instance=instance_1)

            instance_2 = _make_instance(second_local_repo, instance_id="env2-task")
            env2.reset(instance=instance_2)

            assert env1.state.workspace_path != env2.state.workspace_path
            assert env1.state.instance_id == "env1-task"
            assert env2.state.instance_id == "env2-task"

            repo1 = Path(env1.state.repo_path)
            repo2 = Path(env2.state.repo_path)
            assert (repo1 / "calc.py").exists()
            assert not (repo1 / "math_ops.py").exists()
            assert (repo2 / "math_ops.py").exists()
            assert not (repo2 / "calc.py").exists()

            _edit(
                env1,
                command="str_replace",
                path=str(repo1 / "calc.py"),
                old_str="return a - b  # BUG: should be a + b",
                new_str="return a + b",
            )

            _edit(
                env2,
                command="str_replace",
                path=str(repo2 / "math_ops.py"),
                old_str="return a + b  # BUG: should be a * b",
                new_str="return a * b",
            )

            patch1 = env1.get_patch()
            patch2 = env2.get_patch()
            assert "a + b" in patch1
            assert "a * b" in patch2
            assert "math_ops" not in patch1
            assert "calc" not in patch2
        finally:
            env1.close()
            env2.close()

    def test_independent_undo_histories(self, local_repo, second_local_repo):
        env1 = SWEEnvironment.with_default_tools()
        env2 = SWEEnvironment.with_default_tools()
        try:
            env1.reset(instance=_make_instance(local_repo))
            env2.reset(instance=_make_instance(second_local_repo))

            repo1 = Path(env1.state.repo_path)
            repo2 = Path(env2.state.repo_path)

            _edit(
                env1,
                command="str_replace",
                path=str(repo1 / "calc.py"),
                old_str="return a - b  # BUG: should be a + b",
                new_str="return a + b",
            )

            data = _edit(env1, command="undo_edit", path=str(repo1 / "calc.py"))
            assert data["exit_code"] == 0

            data = _edit(env2, command="undo_edit", path=str(repo2 / "math_ops.py"))
            assert data["exit_code"] == 1
        finally:
            env1.close()
            env2.close()

    def test_reset_one_while_other_active(self, local_repo, second_local_repo):
        env1 = SWEEnvironment.with_default_tools()
        env2 = SWEEnvironment.with_default_tools()
        try:
            env1.reset(instance=_make_instance(local_repo, instance_id="env1"))
            env2.reset(instance=_make_instance(second_local_repo, instance_id="env2"))

            env1.reset()
            assert env1.state.instance_id == ""

            assert env2.state.instance_id == "env2"
            repo2 = Path(env2.state.repo_path)
            assert (repo2 / "math_ops.py").exists()
        finally:
            env1.close()
            env2.close()


class TestAppImports:
    def test_app_is_fastapi_instance(self):
        from swe_env.server.app import app
        from fastapi import FastAPI

        assert isinstance(app, FastAPI)

    def test_client_class_exists(self):
        from swe_env import SWEEnv
        from openenv.core.mcp_client import MCPToolClient

        assert issubclass(SWEEnv, MCPToolClient)
