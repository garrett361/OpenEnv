#!/usr/bin/env python
"""Minimal math verification environment example."""

import subprocess
import sys
import time
from typing import Any

from openenv.core.client_types import StepResult
from openenv.core.env_client import EnvClient
from openenv.core.env_server import Action, Environment, Observation, State


class MathAction(Action):
    gold_answer: str
    response: str


class MathObservation(Observation):
    done: bool = True
    reward: float = 0.0


class MathState(State):
    step_count: int = 0


class MathEnvironment(Environment[MathAction, MathObservation, MathState]):
    def __init__(self):
        self._state = MathState()

    def reset(self) -> MathObservation:
        self._state = MathState()
        return MathObservation()

    def step(self, action: MathAction) -> MathObservation:
        self._state.step_count += 1
        reward = 1.0 if action.gold_answer[-1] == action.response[-1] else 0.0
        return MathObservation(reward=reward)

    @property
    def state(self) -> MathState:
        return self._state


class MathClient(EnvClient[MathAction, MathObservation, MathState]):
    def _step_payload(self, action: MathAction) -> dict[str, Any]:
        return {"gold_answer": action.gold_answer, "response": action.response}

    def _parse_result(self, payload: dict[str, Any]) -> StepResult[MathObservation]:
        obs_data = payload.get("observation", {})
        return StepResult(
            observation=MathObservation(
                done=obs_data.get("done", True),
                reward=obs_data.get("reward", 0.0),
            ),
            reward=payload.get("reward", 0.0),
            done=payload.get("done", True),
        )

    def _parse_state(self, payload: dict[str, Any]) -> MathState:
        return MathState(step_count=payload.get("step_count", 0))


def run_server():
    import uvicorn

    from openenv.core.env_server import create_fastapi_app

    app = create_fastapi_app(MathEnvironment, MathAction, MathObservation)
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="warning")


def main():
    print("=== Minimal Math Verification Environment ===\n")

    print("Starting server...")
    server = subprocess.Popen(
        [sys.executable, __file__, "--server"],
    )
    time.sleep(2)

    try:
        client = MathClient(base_url="http://localhost:8001")
        client.reset()

        result = client.step(MathAction(gold_answer="2", response="3"))
        print(f"Q: What is 1+1?  Gold: '2'  Response: '3'  Reward: {result.reward}")

        result = client.step(MathAction(gold_answer="2", response="2"))
        print(f"Q: What is 1+1?  Gold: '2'  Response: '2'  Reward: {result.reward}")

        print("\nDone!")

    finally:
        server.terminate()
        server.wait()


if __name__ == "__main__":
    if "--server" in sys.argv:
        run_server()
    else:
        main()
