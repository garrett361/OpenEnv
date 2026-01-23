"""FastAPI application for the Min Math Environment."""

from openenv.core.env_server.http_server import create_app

from models import MathAction, MathObservation
from .min_math_environment import MathEnvironment

app = create_app(MathEnvironment, MathAction, MathObservation, env_name="min_math")


def main(port: int = 8001):
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
