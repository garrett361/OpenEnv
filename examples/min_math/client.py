"""Min Math Environment Client."""

from typing import Dict

from openenv.core.client_types import StepResult
from openenv.core.env_server.types import State
from openenv.core.env_client import EnvClient

from .models import MathAction, MathObservation


class MathClient(EnvClient[MathAction, MathObservation, State]):
    """Client for the Min Math Environment."""

    def _step_payload(self, action: MathAction) -> Dict:
        return {"gold_answer": action.gold_answer, "response": action.response}

    def _parse_result(self, payload: Dict) -> StepResult[MathObservation]:
        obs_data = payload.get("observation", {})
        return StepResult(
            observation=MathObservation(
                done=obs_data.get("done", True),
                reward=obs_data.get("reward", 0.0),
            ),
            reward=payload.get("reward", 0.0),
            done=payload.get("done", True),
        )

    def _parse_state(self, payload: Dict) -> State:
        return State(
            episode_id=payload.get("episode_id"),
            step_count=payload.get("step_count", 0),
        )
