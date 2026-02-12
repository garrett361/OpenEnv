# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
FastAPI application for the Memory-limited Coding Environment.

This module creates an HTTP server that exposes MemlimitedPythonCodeActEnv
over HTTP and WebSocket endpoints.  Each code execution runs in a subprocess
with RLIMIT_AS / RLIMIT_CPU limits.

Usage:
    uvicorn memlimited_coding_env.server.app:app --host 0.0.0.0 --port 8000
"""

from openenv.core.env_server import create_app

from coding_env.models import CodeAction, CodeObservation
from memlimited_coding_env.server.memlimited_python_codeact_env import (
    MemlimitedPythonCodeActEnv,
)

app = create_app(
    MemlimitedPythonCodeActEnv,
    CodeAction,
    CodeObservation,
    env_name="memlimited_coding_env",
)


def main():
    """Main entry point for running the server."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
