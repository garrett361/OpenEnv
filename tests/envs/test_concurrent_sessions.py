"""Tests for concurrent WebSocket session support on coding_env and memlimited_coding_env.

Run with:
    PYTHONPATH=openenv/src:openenv/envs python -m pytest openenv/tests/envs/test_concurrent_sessions.py -v
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time

import pytest
import uvicorn
from coding_env.client import CodingEnv
from coding_env.models import CodeAction, CodeObservation
from coding_env.server.python_codeact_env import PythonCodeActEnv
from memlimited_coding_env.server.memlimited_python_codeact_env import (
    MemlimitedPythonCodeActEnv,
)

from openenv.core.env_server import create_app, create_fastapi_app


class TestConcurrentSessionsFlag:
    def test_coding_env_supports_concurrent_sessions(self):
        assert PythonCodeActEnv.SUPPORTS_CONCURRENT_SESSIONS is True

    def test_memlimited_env_supports_concurrent_sessions(self):
        assert MemlimitedPythonCodeActEnv.SUPPORTS_CONCURRENT_SESSIONS is True


class TestCreateAppWithConcurrentSessions:
    def test_create_app_with_concurrent_sessions(self):
        app = create_app(
            PythonCodeActEnv,
            CodeAction,
            CodeObservation,
            max_concurrent_envs=4,
        )
        assert app is not None

    def test_create_app_memlimited_with_concurrent_sessions(self):
        app = create_app(
            MemlimitedPythonCodeActEnv,
            CodeAction,
            CodeObservation,
            max_concurrent_envs=4,
        )
        assert app is not None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_env_server(env_cls):
    """Start a uvicorn server for the given env class and yield its base URL."""
    import requests as req

    port = _free_port()
    app = create_fastapi_app(env_cls, CodeAction, CodeObservation, max_concurrent_envs=4)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            resp = req.get(f"{base_url}/health", timeout=1)
            if resp.status_code == 200:
                return base_url, server, thread
        except Exception:
            pass
        time.sleep(0.1)

    raise RuntimeError(f"OpenEnv server failed to start on port {port}")


@pytest.fixture(scope="module")
def coding_env_server():
    """Start a coding_env server on a random port for the module."""
    base_url, server, thread = _start_env_server(PythonCodeActEnv)
    yield base_url
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def memlimited_env_server():
    """Start a memlimited_coding_env server on a random port for the module."""
    base_url, server, thread = _start_env_server(MemlimitedPythonCodeActEnv)
    yield base_url
    server.should_exit = True
    thread.join(timeout=5)


@pytest.mark.integration
class TestMultipleWSSessions:
    def test_multiple_ws_sessions_independent_state(self, coding_env_server):
        """Two WS sessions should have isolated state (no shared variables)."""
        base_url = coding_env_server

        async def _run():
            env_a = CodingEnv(base_url=base_url)
            env_b = CodingEnv(base_url=base_url)

            await env_a.connect()
            await env_b.connect()
            try:
                await env_a.reset()
                await env_b.reset()

                # Session A defines x = 42
                result_a = await env_a.step(CodeAction(code="x = 42"))
                assert result_a.observation.exit_code == 0

                # Session A can read x
                result_a2 = await env_a.step(CodeAction(code="print(x)"))
                assert result_a2.observation.exit_code == 0
                assert "42" in result_a2.observation.stdout

                # Session B should NOT see x (isolated state)
                result_b = await env_b.step(CodeAction(code="print(x)"))
                assert result_b.observation.exit_code == 1
                assert "not defined" in result_b.observation.stderr
            finally:
                await env_a.close()
                await env_b.close()

        asyncio.run(_run())

    def test_memlimited_ws_sessions_independent_execution(self, memlimited_env_server):
        """Two memlimited WS sessions can execute concurrently without interference."""
        base_url = memlimited_env_server

        async def _run():
            env_a = CodingEnv(base_url=base_url)
            env_b = CodingEnv(base_url=base_url)

            await env_a.connect()
            await env_b.connect()
            try:
                await env_a.reset()
                await env_b.reset()

                result_a = await env_a.step(CodeAction(code="print(1 + 1)"))
                assert result_a.observation.exit_code == 0
                assert "2" in result_a.observation.stdout

                result_b = await env_b.step(CodeAction(code="print(3 + 4)"))
                assert result_b.observation.exit_code == 0
                assert "7" in result_b.observation.stdout
            finally:
                await env_a.close()
                await env_b.close()

        asyncio.run(_run())
