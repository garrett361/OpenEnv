---
title: Min Math Environment Server
emoji: 🥇
colorFrom: pink
colorTo: blue
sdk: docker
pinned: false
app_port: 8000
base_path: /web
tags:
  - openenv
---

# Min Math Environment

Simple math env which looks for exact matches between gold answers and the final characters of the
response. Not actually specific to math yet.

## Quick Start

The simplest way to use the Min Math environment is through the `MathClient` class:

```python
from examples.min_math import MathAction, MathClient

try:
    # Create environment from Docker image
    client = MathClient.from_docker_image("min_math-env:latest")

    # Reset
    result = client.reset()

    # Wrong answer
    result = client.step(MathAction(gold_answer="2", response="What is 1+1? 3"))
    print(f"Reward: {result.reward}")  # 0.0

    # Correct answer
    result = client.step(MathAction(gold_answer="2", response="What is 1+1? 2"))
    print(f"Reward: {result.reward}")  # 1.0

finally:
    # Always clean up
    client.close()
```

That's it! The `MathClient.from_docker_image()` method handles:
- Starting the Docker container
- Waiting for the server to be ready
- Connecting to the environment
- Container cleanup when you call `close()`

## Building the Docker Image

Before using the environment, you need to build the Docker image:

```bash
# From project root
docker build -t min_math-env:latest -f server/Dockerfile .
```

## Deploying to Hugging Face Spaces

You can easily deploy your OpenEnv environment to Hugging Face Spaces using the `openenv push` command:

```bash
# From the environment directory (where openenv.yaml is located)
openenv push

# Or specify options
openenv push --namespace my-org --private
```

The `openenv push` command will:
1. Validate that the directory is an OpenEnv environment (checks for `openenv.yaml`)
2. Prepare a custom build for Hugging Face Docker space (enables web interface)
3. Upload to Hugging Face (ensuring you're logged in)

### Prerequisites

- Authenticate with Hugging Face: The command will prompt for login if not already authenticated

### Options

- `--directory`, `-d`: Directory containing the OpenEnv environment (defaults to current directory)
- `--repo-id`, `-r`: Repository ID in format 'username/repo-name' (defaults to 'username/env-name' from openenv.yaml)
- `--base-image`, `-b`: Base Docker image to use (overrides Dockerfile FROM)
- `--private`: Deploy the space as private (default: public)

### Examples

```bash
# Push to your personal namespace (defaults to username/env-name from openenv.yaml)
openenv push

# Push to a specific repository
openenv push --repo-id my-org/my-env

# Push with a custom base image
openenv push --base-image ghcr.io/meta-pytorch/openenv-base:latest

# Push as a private space
openenv push --private

# Combine options
openenv push --repo-id my-org/my-env --base-image custom-base:latest --private
```

After deployment, your space will be available at:
`https://huggingface.co/spaces/<repo-id>`

The deployed space includes:
- **Web Interface** at `/web` - Interactive UI for exploring the environment
- **API Documentation** at `/docs` - Full OpenAPI/Swagger interface
- **Health Check** at `/health` - Container health monitoring
- **WebSocket** at `/ws` - Persistent session endpoint for low-latency interactions

## Environment Details

### Action
**MathAction**: Contains two fields
- `gold_answer` (str) - The correct answer to compare against
- `response` (str) - The model's response (e.g., "The answer is 42")

### Observation
**MathObservation**: Inherits from base Observation
- `reward` (float) - 1.0 if gold_answer matches end of response, else 0.0
- `done` (bool) - Always True after a step

### Reward
The reward checks if the response string ends with the gold answer:
```python
reward = 1.0 if action.gold_answer == action.response[-len(action.gold_answer):] else 0.0
```

Examples:
- gold="2", response="The answer is 2" → reward: 1.0
- gold="42", response="I think it's 42" → reward: 1.0
- gold="2", response="The answer is 3" → reward: 0.0

## Advanced Usage

### Connecting to an Existing Server

If you already have a Min Math environment server running, you can connect directly:

```python
from examples.min_math import MathClient, MathAction

# Connect to existing server
client = MathClient(base_url="<ENV_HTTP_URL_HERE>")

# Use as normal
result = client.reset()
result = client.step(MathAction(gold_answer="2", response="1+1=2"))
```

Note: When connecting to an existing server, `client.close()` will NOT stop the server.

### Using the Context Manager

The client supports context manager usage for automatic connection management:

```python
from examples.min_math import MathAction, MathClient

# Connect with context manager (auto-connects and closes)
with MathClient(base_url="http://localhost:8000") as env:
    result = env.reset()
    # Multiple steps with low latency
    result = env.step(MathAction(gold_answer="4", response="2+2=4"))
    print(f"Reward: {result.reward}")
```

The client uses WebSocket connections for:
- **Lower latency**: No HTTP connection overhead per request
- **Persistent session**: Server maintains your environment state
- **Efficient for episodes**: Better for many sequential steps

### Concurrent WebSocket Sessions

The server supports multiple concurrent WebSocket connections. To enable this,
modify `server/app.py` to use factory mode:

```python
# In server/app.py - use factory mode for concurrent sessions
app = create_app(
    MathEnvironment,  # Pass class, not instance
    MathAction,
    MathObservation,
    max_concurrent_envs=4,  # Allow 4 concurrent sessions
)
```

Then multiple clients can connect simultaneously:

```python
from concurrent.futures import ThreadPoolExecutor

from examples.min_math import MathAction, MathClient


def run_episode(client_id: int):
    with MathClient(base_url="http://localhost:8000") as env:
        env.reset()
        result = env.step(MathAction(gold_answer="2", response="1+1=2"))
        return client_id, result.reward


# Run 4 episodes concurrently
with ThreadPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(run_episode, range(4)))
```

## Development & Testing

### Direct Environment Testing

Test the environment logic directly without starting the HTTP server:

```bash
# From the server directory
python3 server/min_math_environment.py
```

This verifies that:
- Environment resets correctly
- Step executes actions properly
- State tracking works
- Rewards are calculated correctly

### Running Locally

Run the server locally for development:

```bash
uvicorn server.app:app --reload
```

## Project Structure

```
min_math/
├── .dockerignore          # Docker build exclusions
├── __init__.py            # Module exports
├── README.md              # This file
├── openenv.yaml           # OpenEnv manifest
├── pyproject.toml         # Project metadata and dependencies
├── uv.lock                # Locked dependencies (generated)
├── client.py              # MathClient client
├── models.py              # Action and Observation models
├── test_min_math.py       # Standalone test script 
└── server/
    ├── __init__.py        # Server module exports
    ├── min_math_environment.py  # Core environment logic
    ├── app.py             # FastAPI application (HTTP + WebSocket endpoints)
    └── Dockerfile         # Container image definition
```
