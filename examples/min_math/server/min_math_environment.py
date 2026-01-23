"""Min Math Environment Implementation."""

from uuid import uuid4

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

from models import MathAction, MathObservation


class MathEnvironment(Environment):
    """Environment that rewards +1 if final chars of gold_answer and response match."""

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(self):
        self._state = State(episode_id=str(uuid4()), step_count=0)

    def reset(self) -> MathObservation:
        self._state = State(episode_id=str(uuid4()), step_count=0)
        return MathObservation(done=False, reward=0.0)

    def step(self, action: MathAction) -> MathObservation:
        self._state.step_count += 1
        reward = (
            1.0
            if action.gold_answer == action.response[-len(action.gold_answer) :]
            else 0.0
        )
        return MathObservation(done=True, reward=reward)

    @property
    def state(self) -> State:
        return self._state
