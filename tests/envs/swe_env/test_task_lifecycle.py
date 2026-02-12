"""Stage 4 tests: SWE-Bench task lifecycle (reset, patch extraction, evaluation)."""

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

from swe_env.models import SWEBenchInstance
from swe_env.server.environment import SWEEnvironment
from swe_env.server.workspace import Workspace
from swe_env.server.tools.bash_tool import BashToolModule
from swe_env.server.tools.file_editor_tool import FileEditorToolModule
from openenv.core.env_server.mcp_types import CallToolAction


@pytest.fixture()
def local_repo(tmp_path):
    """Create a local git repo with a known bug to serve as the 'remote'."""
    repo = tmp_path / "test_repo"
    repo.mkdir()

    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        capture_output=True,
        check=True,
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
        cwd=repo,
        capture_output=True,
        check=True,
    )

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    base_commit = result.stdout.strip()

    return repo, base_commit


@pytest.fixture()
def test_patch_content():
    """A patch that adds a test file exposing the bug.

    The test imports and calls add(2, 3). The buggy implementation returns
    2 - 3 = -1, so ``assert add(2, 3) == 5`` fails until the bug is fixed.
    """
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


def _make_instance(local_repo, test_patch="", problem_statement="Fix the add function"):
    repo_path, base_commit = local_repo
    return {
        "instance_id": "test__calc-001",
        "repo": str(repo_path),
        "base_commit": base_commit,
        "problem_statement": problem_statement,
        "test_patch": test_patch,
    }


@pytest.fixture()
def env():
    e = SWEEnvironment.with_default_tools()
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


def _edit(env, **kwargs):
    obs = env.step(CallToolAction(tool_name="file_editor", arguments=kwargs))
    result = obs.result
    if hasattr(result, "data"):
        return result.data
    return json.loads(result)


class TestTaskBasedReset:
    def test_reset_with_instance_clones_repo(self, env, local_repo):
        instance = _make_instance(local_repo)
        obs = env.reset(instance=instance)
        assert obs.metadata["status"] == "ready"
        repo_dir = Path(env.state.repo_path)
        assert repo_dir.exists()
        assert (repo_dir / "calc.py").exists()

    def test_cloned_repo_at_base_commit(self, env, local_repo):
        instance = _make_instance(local_repo)
        env.reset(instance=instance)
        repo_dir = Path(env.state.repo_path)
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
        _, base_commit = local_repo
        assert result.stdout.strip() == base_commit

    def test_state_has_instance_fields(self, env, local_repo):
        instance = _make_instance(local_repo, problem_statement="Fix the bug")
        env.reset(instance=instance)
        assert env.state.instance_id == "test__calc-001"
        assert env.state.problem_statement == "Fix the bug"
        assert env.state.repo_path != ""

    def test_reset_with_test_patch(self, env, local_repo, test_patch_content):
        instance = _make_instance(local_repo, test_patch=test_patch_content)
        env.reset(instance=instance)
        repo_dir = Path(env.state.repo_path)
        assert (repo_dir / "test_calc.py").exists()

    def test_reset_without_instance_clears_workspace(self, env, local_repo):
        instance = _make_instance(local_repo)
        env.reset(instance=instance)
        assert Path(env.state.repo_path).exists()

        env.reset()
        ws = Path(env.state.workspace_path)
        assert list(ws.iterdir()) == []
        assert env.state.instance_id == ""
        assert env.state.repo_path == ""

    def test_reset_with_dict_instance(self, env, local_repo):
        instance = _make_instance(local_repo)
        env.reset(instance=instance)
        assert env.state.instance_id == "test__calc-001"

    def test_reset_with_model_instance(self, env, local_repo):
        raw = _make_instance(local_repo)
        instance = SWEBenchInstance(**raw)
        env.reset(instance=instance)
        assert env.state.instance_id == "test__calc-001"

    def test_observation_contains_instance_metadata(self, env, local_repo):
        instance = _make_instance(local_repo, problem_statement="Please fix add()")
        obs = env.reset(instance=instance)
        assert obs.metadata["instance_id"] == "test__calc-001"
        assert obs.metadata["problem_statement"] == "Please fix add()"


class TestPatchExtraction:
    def test_patch_after_edit(self, env, local_repo):
        instance = _make_instance(local_repo)
        env.reset(instance=instance)
        repo_dir = Path(env.state.repo_path)

        calc_file = repo_dir / "calc.py"
        _edit(
            env,
            command="str_replace",
            path=str(calc_file),
            old_str="return a - b  # BUG: should be a + b",
            new_str="return a + b",
        )

        patch = env.get_patch()
        assert patch != ""
        assert "a + b" in patch
        assert "a - b" in patch

    def test_patch_no_changes(self, env, local_repo):
        instance = _make_instance(local_repo)
        env.reset(instance=instance)
        patch = env.get_patch()
        assert patch == ""

    def test_patch_no_repo(self, env):
        env.reset()
        patch = env.get_patch()
        assert patch == ""


class TestEvaluation:
    def test_evaluate_resolved_after_fix(self, env, local_repo, test_patch_content):
        instance = _make_instance(local_repo, test_patch=test_patch_content)
        env.reset(instance=instance)
        repo_dir = Path(env.state.repo_path)

        calc_file = repo_dir / "calc.py"
        _edit(
            env,
            command="str_replace",
            path=str(calc_file),
            old_str="return a - b  # BUG: should be a + b",
            new_str="return a + b",
        )

        result = env.evaluate(test_command="python -m pytest test_calc.py -v")
        assert result["resolved"] is True
        assert result["exit_code"] == 0

    def test_evaluate_not_resolved_without_fix(self, env, local_repo, test_patch_content):
        instance = _make_instance(local_repo, test_patch=test_patch_content)
        env.reset(instance=instance)

        result = env.evaluate(test_command="python -m pytest test_calc.py -v")
        assert result["resolved"] is False
        assert result["exit_code"] != 0

    def test_evaluate_custom_command(self, env, local_repo):
        instance = _make_instance(local_repo)
        env.reset(instance=instance)

        result = env.evaluate(test_command="echo 'custom test passed'")
        assert result["resolved"] is True
        assert "custom test passed" in result["stdout"]

    def test_evaluate_no_repo(self, env):
        env.reset()
        result = env.evaluate()
        assert result["resolved"] is False
        assert "No repo" in result["stderr"]


class TestFullLifecycle:
    def test_reset_explore_fix_patch_evaluate(self, env, local_repo, test_patch_content):
        instance = _make_instance(local_repo, test_patch=test_patch_content)
        obs = env.reset(instance=instance)
        assert obs.metadata["status"] == "ready"

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

        result = env.evaluate(test_command="python -m pytest test_calc.py -v")
        assert result["resolved"] is True
