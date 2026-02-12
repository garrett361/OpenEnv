# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Subprocess-isolated Python executor with memory limits.

Wraps PyExecutor to run each code execution in a separate child process with
resource limits (RLIMIT_AS for virtual memory, RLIMIT_CPU for CPU time).
The child process is killed on timeout or OOM, preventing unbounded memory
usage from affecting the server.

This is the OpenEnv equivalent of SandboxFusion's ``memory_limit_MB`` --
SandboxFusion ran code in an isolated container with explicit memory caps;
this module achieves similar isolation via ``multiprocessing.Process`` with
``resource.setrlimit``.

Configure via environment variables:
    OPENENV_MEMORY_LIMIT_MB  Max *additional* virtual memory the child may
                             allocate beyond its inherited footprint.
                             Default: 4096 (4 GB).
    OPENENV_TIMEOUT_S        Wall-clock timeout per execution.  Default: 30.
    OPENENV_CPU_LIMIT_S      CPU-time limit (SIGXCPU on exceed).  Default: 60.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import resource
import signal

from openenv.core.env_server.types import CodeExecResult

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

_DEFAULT_MEMORY_LIMIT_MB = 4096
_DEFAULT_TIMEOUT_S = 30
_DEFAULT_CPU_LIMIT_S = 60


def _get_vm_size_bytes() -> int:
    """Read current virtual memory size from /proc/self/status (Linux)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmSize:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return 0


def _child_worker(
    code: str,
    additional_imports: list[str],
    memory_limit_bytes: int,
    cpu_limit_s: int,
    conn: mp.connection.Connection,
) -> None:
    """Execute *code* inside a resource-limited child process.

    Results are sent back through *conn* as a ``(stdout, stderr, exit_code)``
    tuple.  On ``MemoryError`` or other failures the error is reported via
    the same tuple so the parent never blocks on the pipe.
    """
    # --- Set resource limits before running any user code -----------------
    # RLIMIT_AS is relative to the total virtual address space.  After a
    # fork the child inherits the parent's mappings, so we read the current
    # VmSize and add the configured headroom.
    try:
        current_vm = _get_vm_size_bytes()
        new_limit = current_vm + memory_limit_bytes
        resource.setrlimit(resource.RLIMIT_AS, (new_limit, new_limit))
    except (ValueError, OSError):
        logger.debug("Could not set RLIMIT_AS", exc_info=True)
        raise

    try:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit_s, cpu_limit_s))
    except (ValueError, OSError):
        logger.debug("Could not set RLIMIT_CPU", exc_info=True)
        raise

    # --- Execute ----------------------------------------------------------
    # Import here so the limits are in place before we do any real work.
    from coding_env.server.python_executor import PyExecutor  # noqa: E402

    try:
        executor = PyExecutor(additional_imports=additional_imports)
        result = executor.run(code)
        conn.send((result.stdout, result.stderr, result.exit_code))
    except MemoryError:
        try:
            conn.send(("", "MemoryError: execution exceeded memory limit", 137))
        except Exception:
            logger.debug("Child could not send MemoryError through pipe", exc_info=True)
    except Exception as e:
        try:
            conn.send(("", f"Subprocess error: {e}", 1))
        except Exception:
            logger.debug("Child could not send error through pipe", exc_info=True)
    finally:
        conn.close()


class SubprocessPyExecutor:
    """Execute Python code in an isolated subprocess with memory/time limits.

    Each call to :meth:`run` spawns a child process (via ``fork``) that:

    1. Sets ``RLIMIT_AS`` to ``current_vm + memory_limit`` to cap virtual
       memory.
    2. Sets ``RLIMIT_CPU`` as a CPU-time backstop.
    3. Creates a fresh :class:`PyExecutor` and runs the code.
    4. Is ``terminate``/``kill``-ed on timeout.

    The interface (``run(code) -> CodeExecResult``) is identical to
    :class:`PyExecutor`, so this is a drop-in replacement.
    """

    def __init__(self, additional_imports: list[str] | None = None):
        self.additional_imports = additional_imports or []
        self.memory_limit_mb = int(
            os.environ.get("OPENENV_MEMORY_LIMIT_MB", _DEFAULT_MEMORY_LIMIT_MB)
        )
        self.timeout_s = int(
            os.environ.get("OPENENV_TIMEOUT_S", _DEFAULT_TIMEOUT_S)
        )
        self.cpu_limit_s = int(
            os.environ.get("OPENENV_CPU_LIMIT_S", _DEFAULT_CPU_LIMIT_S)
        )
        logger.info(
            "SubprocessPyExecutor: memory_limit=%dMB timeout=%ds cpu_limit=%ds",
            self.memory_limit_mb,
            self.timeout_s,
            self.cpu_limit_s,
        )

    def run(self, code: str) -> CodeExecResult:
        """Execute *code* in an isolated subprocess and return the result."""
        parent_conn, child_conn = mp.Pipe(duplex=False)

        proc = mp.Process(
            target=_child_worker,
            args=(
                code,
                self.additional_imports,
                self.memory_limit_mb * 1024 * 1024,
                self.cpu_limit_s,
                child_conn,
            ),
            daemon=True,
        )
        proc.start()
        # Close the write-end in the parent so we get EOF when child closes.
        child_conn.close()

        try:
            if parent_conn.poll(timeout=self.timeout_s):
                stdout, stderr, exit_code = parent_conn.recv()
                proc.join(timeout=5)
                return CodeExecResult(
                    stdout=stdout, stderr=stderr, exit_code=exit_code
                )

            # Timeout -- kill the child.
            self._kill_process(proc)
            return CodeExecResult(
                stdout="",
                stderr=f"TIMEOUT: execution exceeded {self.timeout_s}s limit",
                exit_code=1,
            )

        except (EOFError, OSError):
            # Pipe broken before we got a result -- child crashed (OOM /
            # signal).
            self._kill_process(proc)
            exit_code = proc.exitcode
            if exit_code is not None and exit_code < 0:
                sig_num = -exit_code
                try:
                    sig_name = signal.Signals(sig_num).name
                except (ValueError, KeyError):
                    sig_name = str(sig_num)
                return CodeExecResult(
                    stdout="",
                    stderr=(
                        f"Process killed by {sig_name} "
                        "(likely exceeded memory or CPU limit)"
                    ),
                    exit_code=137,
                )
            return CodeExecResult(
                stdout="",
                stderr=f"Process crashed with exit code {exit_code}",
                exit_code=exit_code or 1,
            )
        finally:
            parent_conn.close()
            if proc.is_alive():
                self._kill_process(proc)

    @staticmethod
    def _kill_process(proc: mp.Process) -> None:
        """Terminate then kill *proc*, ensuring cleanup."""
        try:
            proc.terminate()
            proc.join(timeout=5)
        except Exception:
            logger.warning("Failed to terminate child pid=%s", proc.pid, exc_info=True)
        if proc.is_alive():
            try:
                proc.kill()
                proc.join(timeout=5)
            except Exception:
                logger.warning("Failed to kill child pid=%s", proc.pid, exc_info=True)
