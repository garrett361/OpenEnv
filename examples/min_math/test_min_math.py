#!/usr/bin/env python
"""Test script for the Min Math Environment."""

import os
import subprocess
import sys
import time
from pathlib import Path

repo_root = Path(__file__).parent.parent.parent
env_dir = Path(__file__).parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root))

from examples.min_math import MathClient, MathAction


def main():
    print("=== Min Math Environment Test ===\n")

    print("Starting server...")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.app:app", "--port", "8001"],
        cwd=env_dir,
        env={**os.environ, "PYTHONPATH": f"{repo_root}/src:{env_dir}"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

    try:
        client = MathClient(base_url="http://localhost:8001")
        client.reset()

        result = client.step(MathAction(gold_answer="2", response="What does 1+1 equal? 3"))
        print(f"Gold: '2'  Response: '3'  Reward: {result.reward}")
        assert result.reward == 0.0, "Wrong answer should give 0 reward"

        result = client.step(MathAction(gold_answer="2", response="What does 1+1 equal? 2"))
        print(f"Gold: '2'  Response: '2'  Reward: {result.reward}")
        assert result.reward == 1.0, "Correct answer should give 1 reward"

        print("\nAll tests passed!")

    finally:
        server.terminate()
        server.wait()


if __name__ == "__main__":
    main()
