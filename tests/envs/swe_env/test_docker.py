"""Docker tests for swe_env: image build and container lifecycle.

These tests verify that the swe_env Docker image builds correctly and
that the containerized server responds to health checks and HTTP endpoints.

Build prerequisites:
    docker build -t openenv-base:latest -f src/openenv/core/containers/images/Dockerfile .
    docker build -t swe-env:latest -f envs/swe_env/server/Dockerfile envs/swe_env/

Run these tests with:
    PYTHONPATH=src:envs uv run pytest tests/envs/swe_env/test_docker.py -v
"""

import shutil
import subprocess
import time

import pytest

SWE_ENV_IMAGE = "swe-env:latest"
BASE_IMAGE = "openenv-base:latest"


@pytest.fixture(scope="module")
def check_docker_available():
    if not shutil.which("docker"):
        pytest.skip("Docker is not installed")

    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10, text=True
        )
        if result.returncode != 0:
            pytest.skip("Docker daemon is not running")
    except subprocess.TimeoutExpired:
        pytest.skip("Docker daemon not responding")
    except Exception as e:
        pytest.skip(f"Cannot access Docker: {e}")


@pytest.fixture(scope="module")
def base_image_built(check_docker_available):
    result = subprocess.run(
        ["docker", "images", "-q", BASE_IMAGE],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        return

    build_result = subprocess.run(
        [
            "docker",
            "build",
            "-t",
            BASE_IMAGE,
            "-f",
            "src/openenv/core/containers/images/Dockerfile",
            ".",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if build_result.returncode != 0:
        pytest.skip(f"Failed to build base image: {build_result.stderr[:500]}")


@pytest.fixture(scope="module")
def swe_env_image_built(base_image_built):
    result = subprocess.run(
        [
            "docker",
            "build",
            "-t",
            SWE_ENV_IMAGE,
            "--build-arg",
            f"BASE_IMAGE={BASE_IMAGE}",
            "-f",
            "envs/swe_env/server/Dockerfile",
            "envs/swe_env/",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        pytest.fail(
            f"Failed to build swe-env image.\n"
            f"stdout: {result.stdout[-500:]}\n"
            f"stderr: {result.stderr[-500:]}"
        )


def _find_free_port():
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def running_container(swe_env_image_built):
    port = _find_free_port()
    container_name = f"swe-env-test-{int(time.time() * 1000)}"

    result = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "-p",
            f"{port}:8000",
            SWE_ENV_IMAGE,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.fail(
            f"Failed to start container.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    container_id = result.stdout.strip()
    base_url = f"http://localhost:{port}"

    import requests

    deadline = time.time() + 60
    proxies = {"http": None, "https": None}
    while time.time() < deadline:
        try:
            resp = requests.get(f"{base_url}/health", timeout=2.0, proxies=proxies)
            if resp.status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(1.0)
    else:
        logs = subprocess.run(
            ["docker", "logs", container_id],
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["docker", "rm", "-f", container_id],
            capture_output=True,
        )
        pytest.fail(
            f"Container did not become healthy within 60s.\n"
            f"Container logs:\n{logs.stdout[-1000:]}\n{logs.stderr[-1000:]}"
        )

    yield base_url

    subprocess.run(
        ["docker", "rm", "-f", container_id],
        capture_output=True,
        timeout=15,
    )


@pytest.mark.docker
class TestSWEEnvDockerBuild:
    def test_image_exists(self, swe_env_image_built):
        result = subprocess.run(
            ["docker", "images", "-q", SWE_ENV_IMAGE],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip(), "swe-env image was not built"

    def test_image_has_git(self, swe_env_image_built):
        result = subprocess.run(
            ["docker", "run", "--rm", SWE_ENV_IMAGE, "git", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"git not available in image.\nstderr: {result.stderr}"
        )
        assert "git version" in result.stdout

    def test_image_has_bash(self, swe_env_image_built):
        result = subprocess.run(
            ["docker", "run", "--rm", SWE_ENV_IMAGE, "bash", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"bash not available in image.\nstderr: {result.stderr}"
        )

    def test_python_can_import_app(self, swe_env_image_built):
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                SWE_ENV_IMAGE,
                "python",
                "-c",
                "from server.app import app; print(type(app).__name__)",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Cannot import app in container.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "FastAPI" in result.stdout


@pytest.mark.docker
class TestSWEEnvDockerServer:
    def test_health_endpoint(self, running_container):
        import requests

        resp = requests.get(
            f"{running_container}/health",
            timeout=5,
            proxies={"http": None, "https": None},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"

    def test_reset_endpoint(self, running_container):
        import requests

        resp = requests.post(
            f"{running_container}/reset",
            json={},
            headers={"Content-Type": "application/json"},
            timeout=10,
            proxies={"http": None, "https": None},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["observation"]["metadata"]["status"] == "ready"
        assert "bash" in data["observation"]["metadata"]["available_tools"]
        assert "file_editor" in data["observation"]["metadata"]["available_tools"]

    def test_list_tools_via_step(self, running_container):
        import requests

        proxies = {"http": None, "https": None}
        requests.post(
            f"{running_container}/reset",
            json={},
            timeout=10,
            proxies=proxies,
        )

        resp = requests.post(
            f"{running_container}/step",
            json={"action": {"type": "list_tools"}},
            headers={"Content-Type": "application/json"},
            timeout=10,
            proxies=proxies,
        )
        assert resp.status_code == 200
        data = resp.json()
        tool_names = [t["name"] for t in data["observation"]["tools"]]
        assert sorted(tool_names) == ["bash", "file_editor"]

    def test_bash_tool_via_step(self, running_container):
        import requests

        proxies = {"http": None, "https": None}
        requests.post(
            f"{running_container}/reset",
            json={},
            timeout=10,
            proxies=proxies,
        )

        resp = requests.post(
            f"{running_container}/step",
            json={
                "action": {
                    "type": "call_tool",
                    "tool_name": "bash",
                    "arguments": {"command": "echo hello-from-docker"},
                },
            },
            headers={"Content-Type": "application/json"},
            timeout=10,
            proxies=proxies,
        )
        assert resp.status_code == 200
        data = resp.json()
        result = data["observation"]["result"]
        if isinstance(result, dict) and "data" in result:
            result = result["data"]
        assert result["exit_code"] == 0
        assert "hello-from-docker" in result["stdout"]

    def test_file_editor_tool_via_step(self, running_container):
        import requests

        proxies = {"http": None, "https": None}
        requests.post(
            f"{running_container}/reset",
            json={},
            timeout=10,
            proxies=proxies,
        )

        resp = requests.post(
            f"{running_container}/step",
            json={
                "action": {
                    "type": "call_tool",
                    "tool_name": "file_editor",
                    "arguments": {
                        "command": "create",
                        "path": "test_file.txt",
                        "file_text": "hello from docker\n",
                    },
                },
            },
            headers={"Content-Type": "application/json"},
            timeout=10,
            proxies=proxies,
        )
        assert resp.status_code == 200
        data = resp.json()
        result = data["observation"]["result"]
        if isinstance(result, dict) and "data" in result:
            result = result["data"]
        assert result["exit_code"] == 0
