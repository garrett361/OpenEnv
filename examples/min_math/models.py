"""Data models for the Min Math Environment."""

from openenv.core.env_server.types import Action, Observation


class MathAction(Action):
    """Action containing gold answer and model response to compare."""

    gold_answer: str
    response: str


class MathObservation(Observation):
    """Observation with reward based on final character match."""
    # We only use the Observation.reward attr, so no non-trivial code is needed.

    pass
