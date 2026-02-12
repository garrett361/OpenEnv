# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for SubprocessPyExecutor — memory isolation and timeout enforcement."""

from __future__ import annotations

import os

import pytest

from memlimited_coding_env.server.subprocess_executor import SubprocessPyExecutor


@pytest.fixture
def executor():
    """Executor with tight limits for testing."""
    old_mem = os.environ.get("OPENENV_MEMORY_LIMIT_MB")
    old_timeout = os.environ.get("OPENENV_TIMEOUT_S")
    os.environ["OPENENV_MEMORY_LIMIT_MB"] = "512"
    os.environ["OPENENV_TIMEOUT_S"] = "10"
    try:
        yield SubprocessPyExecutor()
    finally:
        if old_mem is None:
            os.environ.pop("OPENENV_MEMORY_LIMIT_MB", None)
        else:
            os.environ["OPENENV_MEMORY_LIMIT_MB"] = old_mem
        if old_timeout is None:
            os.environ.pop("OPENENV_TIMEOUT_S", None)
        else:
            os.environ["OPENENV_TIMEOUT_S"] = old_timeout


class TestBasicExecution:
    def test_hello_world(self, executor: SubprocessPyExecutor):
        result = executor.run("print('hello world')")
        assert result.exit_code == 0
        assert "hello" in result.stdout.lower()

    def test_arithmetic(self, executor: SubprocessPyExecutor):
        result = executor.run("x = 2 + 3\nprint(x)")
        assert result.exit_code == 0
        assert "5" in result.stdout

    def test_syntax_error(self, executor: SubprocessPyExecutor):
        result = executor.run("def f(\n")
        assert result.exit_code != 0
        assert result.stderr

    def test_runtime_error(self, executor: SubprocessPyExecutor):
        result = executor.run("1 / 0")
        assert result.exit_code != 0
        assert result.stderr

    def test_multiline(self, executor: SubprocessPyExecutor):
        code = "result = sum(range(5))\nprint(result)"
        result = executor.run(code)
        assert result.exit_code == 0
        assert "10" in result.stdout


class TestIsolation:
    def test_no_state_leaks_between_runs(self, executor: SubprocessPyExecutor):
        """Each run() spawns a fresh process -- variables must not persist."""
        executor.run("leaked_var = 42")
        result = executor.run("print(leaked_var)")
        assert result.exit_code != 0, "Variable from prior run should not exist"

    def test_crash_does_not_kill_parent(self, executor: SubprocessPyExecutor):
        """A child crash should return an error, not crash the test process."""
        result = executor.run("import ctypes; ctypes.string_at(0)")
        assert result.exit_code != 0
        # Parent is still alive -- run another execution.
        result2 = executor.run("print('still alive')")
        assert result2.exit_code == 0
        assert "still alive" in result2.stdout


class TestTimeout:
    def test_infinite_loop_is_killed(self):
        os.environ["OPENENV_TIMEOUT_S"] = "2"
        try:
            executor = SubprocessPyExecutor()
            result = executor.run("while True: pass")
            assert result.exit_code != 0
            assert "TIMEOUT" in result.stderr or "limit" in result.stderr.lower()
        finally:
            os.environ.pop("OPENENV_TIMEOUT_S", None)


class TestMemoryLimit:
    def test_large_allocation_is_stopped(self):
        """A 512 MB limit should prevent a multi-GB allocation."""
        os.environ["OPENENV_MEMORY_LIMIT_MB"] = "512"
        os.environ["OPENENV_TIMEOUT_S"] = "10"
        try:
            executor = SubprocessPyExecutor()
            # Try to allocate ~4 GB (list of 500M ints, ~4 GB on 64-bit).
            result = executor.run("x = [0] * (500_000_000)")
            assert result.exit_code != 0, (
                "Allocation should have been killed by RLIMIT_AS"
            )
            assert (
                "MemoryError" in result.stderr
                or "memory" in result.stderr.lower()
                or "killed" in result.stderr.lower()
                or "signal" in result.stderr.lower()
            )
        finally:
            os.environ.pop("OPENENV_MEMORY_LIMIT_MB", None)
            os.environ.pop("OPENENV_TIMEOUT_S", None)


class TestEnvVarConfig:
    def test_defaults(self):
        for key in ("OPENENV_MEMORY_LIMIT_MB", "OPENENV_TIMEOUT_S", "OPENENV_CPU_LIMIT_S"):
            os.environ.pop(key, None)
        executor = SubprocessPyExecutor()
        assert executor.memory_limit_mb == 4096
        assert executor.timeout_s == 30
        assert executor.cpu_limit_s == 60

    def test_custom(self):
        os.environ["OPENENV_MEMORY_LIMIT_MB"] = "1024"
        os.environ["OPENENV_TIMEOUT_S"] = "15"
        os.environ["OPENENV_CPU_LIMIT_S"] = "45"
        try:
            executor = SubprocessPyExecutor()
            assert executor.memory_limit_mb == 1024
            assert executor.timeout_s == 15
            assert executor.cpu_limit_s == 45
        finally:
            os.environ.pop("OPENENV_MEMORY_LIMIT_MB", None)
            os.environ.pop("OPENENV_TIMEOUT_S", None)
            os.environ.pop("OPENENV_CPU_LIMIT_S", None)
