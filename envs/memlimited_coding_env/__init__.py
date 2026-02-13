# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Memory-limited Coding Environment.

A coding environment that runs each code execution in a subprocess with
RLIMIT_AS / RLIMIT_CPU limits, preventing unbounded memory usage from
crashing the server.  Reuses models and transforms from coding_env.
"""

from coding_env import CodeAction, CodeObservation, CodeState

__all__ = ["CodeAction", "CodeObservation", "CodeState"]
