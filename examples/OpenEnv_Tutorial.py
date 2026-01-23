#!/usr/bin/env python
"""
OpenEnv Tutorial - Python Script Version

This is a standalone Python script equivalent of the OpenEnv_Tutorial.ipynb notebook.
It demonstrates:
1. RL fundamentals with a simple guessing game
2. OpenEnv architecture and core abstractions
3. Using the OpenSpiel integration
4. Testing different policies against the Catch game

Usage:
    PYTHONPATH=src:envs python examples/OpenEnv_Tutorial.py
"""

import os
import random
import subprocess
import sys
import time
from pathlib import Path

# =============================================================================
# Part 1: RL in 60 Seconds - Number Guessing Game
# =============================================================================

def run_guessing_game():
    """A simple demonstration of the RL loop: observe-act-reward."""
    print("=" * 62)
    print("   Number Guessing Game - The Simplest RL Example")
    print("=" * 62)

    # Environment setup
    target = random.randint(1, 10)
    guesses_left = 3

    print(f"\nI'm thinking of a number between 1 and 10...")
    print(f"You have {guesses_left} guesses. Let's see how random guessing works!\n")

    # The RL Loop - Pure random policy (no learning!)
    while guesses_left > 0:
        # Policy: Random guessing (no learning yet!)
        guess = random.randint(1, 10)
        guesses_left -= 1

        print(f"Guess #{3-guesses_left}: {guess}", end=" -> ")

        # Reward signal (but we're not using it!)
        if guess == target:
            print("Correct! +10 points")
            break
        elif abs(guess - target) <= 2:
            print("Warm! (close)")
        else:
            print("Cold! (far)")
    else:
        print(f"\nOut of guesses. The number was {target}.")

    print("\n" + "=" * 62)
    print("This is RL: Observe -> Act -> Reward -> Repeat")
    print("But this policy is terrible! It doesn't learn from rewards.")
    print("=" * 62 + "\n")


# =============================================================================
# Part 2: Setup - Detect Environment
# =============================================================================

def setup_environment():
    """Setup Python path for local development."""
    print("Running locally")
    # Ensure we're in the correct path
    script_dir = Path(__file__).parent.absolute()
    repo_root = script_dir.parent
    # Add src for openenv imports and repo_root for envs imports
    sys.path.insert(0, str(repo_root / "src"))
    sys.path.insert(0, str(repo_root))  # For 'envs' package imports
    print("Using local OpenEnv installation")
    print("\nReady to explore OpenEnv!\n")
    return str(repo_root)


# =============================================================================
# Part 3: OpenEnv Core Abstractions
# =============================================================================

def show_core_abstractions():
    """Display OpenEnv's core abstractions."""
    from openenv.core.env_server import Environment, Action, Observation, State
    from openenv.core.env_client import EnvClient

    print("=" * 70)
    print("   OPENENV CORE ABSTRACTIONS")
    print("=" * 70)

    print("""
SERVER SIDE (runs in Docker):

    class Environment(ABC):
        '''Base class for all environment implementations'''

        @abstractmethod
        def reset(self) -> Observation:
            '''Start new episode'''

        @abstractmethod
        def step(self, action: Action) -> Observation:
            '''Execute action, return observation'''

        @property
        def state(self) -> State:
            '''Get episode metadata'''

CLIENT SIDE (your training code):

    class EnvClient(ABC):
        '''Base class for HTTP clients'''

        def reset(self) -> StepResult:
            # HTTP POST /reset

        def step(self, action) -> StepResult:
            # HTTP POST /step

        def state(self) -> State:
            # HTTP GET /state
""")

    print("=" * 70)
    print("\nSame interface on both sides - communication via HTTP!")
    print("You focus on RL, OpenEnv handles the infrastructure.\n")


# =============================================================================
# Part 4: OpenSpiel Integration
# =============================================================================

def show_openspiel_models():
    """Display OpenSpiel model fields."""
    from envs.openspiel_env.models import (
        OpenSpielAction,
        OpenSpielObservation,
        OpenSpielState
    )

    print("=" * 70)
    print("   OPENSPIEL INTEGRATION - TYPE-SAFE MODELS")
    print("=" * 70)

    print("\nOpenSpielAction (what you send):")
    print("   " + "-" * 64)
    for name, field in OpenSpielAction.model_fields.items():
        print(f"   - {name:20s} : {field.annotation}")

    print("\nOpenSpielObservation (what you receive):")
    print("   " + "-" * 64)
    for name, field in OpenSpielObservation.model_fields.items():
        print(f"   - {name:20s} : {field.annotation}")

    print("\nOpenSpielState (episode metadata):")
    print("   " + "-" * 64)
    for name, field in OpenSpielState.model_fields.items():
        print(f"   - {name:20s} : {field.annotation}")

    print("\n" + "=" * 70)
    print("\nType safety means:")
    print("   - Your IDE autocompletes these fields")
    print("   - Typos are caught before running")
    print("   - Refactoring is safe")
    print("   - Self-documenting code\n")


# =============================================================================
# Part 5: Start OpenSpiel Server
# =============================================================================

def start_openspiel_server(work_dir: str):
    """Start the OpenSpiel FastAPI server."""
    import requests

    print("=" * 70)
    print("   Starting OpenSpiel Server (Catch Game)")
    print("=" * 70 + "\n")

    # Check if open_spiel is installed
    try:
        import pyspiel
        print("OpenSpiel is installed!\n")
    except ImportError:
        print("OpenSpiel not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "open_spiel"])
        print("OpenSpiel installed!\n")

    print("Starting FastAPI server for OpenSpiel Catch...")
    print("   (This uses REAL OpenEnv + OpenSpiel integration)\n")

    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn",
         "envs.openspiel_env.server.app:app",
         "--host", "0.0.0.0",
         "--port", "8000"],
        env={**os.environ,
             "PYTHONPATH": f"{work_dir}/src:{work_dir}/envs",
             "OPENSPIEL_GAME": "catch",
             "OPENSPIEL_AGENT_PLAYER": "0",
             "OPENSPIEL_OPPONENT_POLICY": "random"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        cwd=work_dir
    )

    # Wait for server to start
    print("Waiting for server to start...")
    time.sleep(5)

    # Check if server is running
    try:
        response = requests.get('http://localhost:8000/health', timeout=2)
        print("\nOpenSpiel server is running!")
        print("Server URL: http://localhost:8000")
        print("Endpoints available:")
        print("   - POST /reset")
        print("   - POST /step")
        print("   - GET /state")
        print("\nThis is REAL OpenEnv + OpenSpiel in action!\n")
        return server_process
    except Exception as e:
        print(f"\nServer failed to start: {e}")
        server_process.kill()
        raise


# =============================================================================
# Part 6: Define Policies
# =============================================================================

def create_policies():
    """Create the four test policies."""
    from envs.openspiel_env.models import OpenSpielObservation

    class RandomPolicy:
        """Baseline: Pure random guessing."""
        name = "Random Guesser"

        def select_action(self, obs: OpenSpielObservation) -> int:
            return random.choice(obs.legal_actions)

    class AlwaysStayPolicy:
        """Bad strategy: Never moves."""
        name = "Always Stay"

        def select_action(self, obs: OpenSpielObservation) -> int:
            return 1  # STAY

    class SmartPolicy:
        """Optimal: Move paddle toward ball."""
        name = "Smart Heuristic"

        def select_action(self, obs: OpenSpielObservation) -> int:
            # Parse OpenSpiel observation
            # For Catch: info_state is a flattened 10x5 grid
            info_state = obs.info_state
            grid_size = 5

            # Find ball position
            ball_col = None
            for idx, val in enumerate(info_state):
                if abs(val - 1.0) < 0.01:
                    ball_col = idx % grid_size
                    break

            # Find paddle position in last row
            last_row = info_state[-grid_size:]
            paddle_col = last_row.index(1.0)

            if ball_col is not None and paddle_col is not None:
                if paddle_col < ball_col:
                    return 2  # Move RIGHT
                elif paddle_col > ball_col:
                    return 0  # Move LEFT

            return 1  # STAY (fallback)

    class LearningPolicy:
        """Simulated RL: Epsilon-greedy exploration."""
        name = "Learning Agent"

        def __init__(self):
            self.steps = 0
            self.smart_policy = SmartPolicy()

        def select_action(self, obs: OpenSpielObservation) -> int:
            self.steps += 1

            # Decay exploration rate over time
            epsilon = max(0.1, 1.0 - (self.steps / 100))

            if random.random() < epsilon:
                # Explore: random action
                return random.choice(obs.legal_actions)
            else:
                # Exploit: use smart strategy
                return self.smart_policy.select_action(obs)

    return [RandomPolicy(), AlwaysStayPolicy(), SmartPolicy(), LearningPolicy()]


# =============================================================================
# Part 7: Run Episodes and Evaluate
# =============================================================================

def run_episode(env, policy, visualize=True, delay=0.3):
    """Run one episode with a policy against OpenSpiel environment."""
    from envs.openspiel_env.models import OpenSpielAction

    # RESET
    result = env.reset()
    obs = result.observation

    if visualize:
        print(f"\n{'='*60}")
        print(f"   {policy.name}")
        print(f"   Playing against OpenSpiel Catch")
        print('=' * 60 + '\n')
        time.sleep(delay)

    total_reward = 0
    step = 0
    action_names = ["LEFT", "STAY", "RIGHT"]

    # THE RL LOOP
    while not obs.done:
        # 1. Policy chooses action
        action_id = policy.select_action(obs)

        # 2. Environment executes (via HTTP!)
        action = OpenSpielAction(action_id=action_id, game_name="catch")
        result = env.step(action)
        obs = result.observation

        # 3. Collect reward
        if result.reward is not None:
            total_reward += result.reward

        if visualize:
            print(f"Step {step + 1}: {action_names[action_id]} -> Reward: {result.reward}")
            time.sleep(delay)

        step += 1

    if visualize:
        result_text = "CAUGHT!" if total_reward > 0 else "MISSED"
        print(f"\n{'='*60}")
        print(f"   {result_text} Total Reward: {total_reward}")
        print('=' * 60)

    return total_reward > 0


def evaluate_policies(env, policies, num_episodes=50):
    """Compare all policies over many episodes using real OpenSpiel."""
    print("\n" + "=" * 70)
    print(f"   POLICY SHOWDOWN - {num_episodes} Episodes Each")
    print(f"   Playing against REAL OpenSpiel Catch!")
    print("=" * 70 + "\n")

    results = []
    for policy in policies:
        print(f"Testing {policy.name}...", end=" ")
        successes = sum(run_episode(env, policy, visualize=False)
                       for _ in range(num_episodes))
        success_rate = (successes / num_episodes) * 100
        results.append((policy.name, success_rate, successes))
        print("Done!")

    print("\n" + "=" * 70)
    print("   FINAL RESULTS")
    print("=" * 70 + "\n")

    # Sort by success rate (descending)
    results.sort(key=lambda x: x[1], reverse=True)

    # Award medals to top 3
    medals = ["1st", "2nd", "3rd", "4th"]

    for i, (name, rate, successes) in enumerate(results):
        medal = medals[i]
        bar = "#" * int(rate / 2)
        print(f"{medal} {name:25s} [{bar:<50}] {rate:5.1f}% ({successes}/{num_episodes})")

    print("\n" + "=" * 70)
    print("\nKey Insights:")
    print("   - Random (~20%):      Baseline - pure luck")
    print("   - Always Stay (~20%): Bad strategy - stays center")
    print("   - Smart (100%):       Optimal - perfect play!")
    print("   - Learning (~85%):    Improves over time")
    print("\nThis is Reinforcement Learning + OpenEnv in action:")
    print("   1. We USED existing OpenSpiel environment (didn't build it)")
    print("   2. Type-safe communication over HTTP")
    print("   3. Same code works for ANY OpenSpiel game")
    print("   4. Production-ready architecture\n")


# =============================================================================
# Main
# =============================================================================

def main():
    """Run the OpenEnv tutorial."""
    print("\n" + "=" * 70)
    print("   OpenEnv Tutorial - From 'Hello World' to RL Training")
    print("=" * 70 + "\n")

    # Part 1: RL basics
    run_guessing_game()

    # Part 2: Setup
    work_dir = setup_environment()

    # Part 3: Show core abstractions
    show_core_abstractions()

    # Part 4: Show OpenSpiel models
    show_openspiel_models()

    # Part 5: Start server
    server_process = start_openspiel_server(work_dir)

    try:
        # Part 6: Connect to server
        from envs.openspiel_env import OpenSpielEnv
        from envs.openspiel_env.models import OpenSpielAction

        print("=" * 70)
        print("   Connecting to OpenSpiel Server via HTTP")
        print("=" * 70 + "\n")

        client = OpenSpielEnv(base_url="http://localhost:8000")
        print("Client created!")
        print("\nWhat just happened:")
        print("   - OpenSpielEnv is an HTTPEnvClient subclass")
        print("   - It knows how to talk to OpenSpiel servers")
        print("   - All communication is type-safe and over HTTP\n")

        # Part 7: Test connection
        print("=" * 70)
        print("   Testing Connection - Playing One Step")
        print("=" * 70 + "\n")

        print("Calling client.reset()...")
        result = client.reset()

        print("Received OpenSpielObservation:")
        print(f"   - info_state: {result.observation.info_state[:10]}... (first 10 values)")
        print(f"   - legal_actions: {result.observation.legal_actions}")
        print(f"   - game_phase: {result.observation.game_phase}")
        print(f"   - done: {result.done}")

        print("\nCalling client.step(OpenSpielAction(action_id=1, game_name='catch'))...")
        action = OpenSpielAction(action_id=1, game_name="catch")
        result = client.step(action)

        print("Received response:")
        print(f"   - Reward: {result.reward}")
        print(f"   - Done: {result.done}")

        state = client.state()
        print(f"\nEpisode state:")
        print(f"   - episode_id: {state.episode_id}")
        print(f"   - step_count: {state.step_count}")
        print(f"   - game_name: {state.game_name}")

        print("\n" + "=" * 70)
        print("IT WORKS! We're using REAL OpenSpiel via HTTP!")
        print("=" * 70 + "\n")

        # Part 8: Create policies and run demo
        policies = create_policies()

        print("=" * 70)
        print("   4 Policies Created for Testing")
        print("=" * 70 + "\n")
        for i, policy in enumerate(policies, 1):
            print(f"   {i}. {policy.name}")
        print()

        # Demo: Watch Smart Policy
        print("=" * 70)
        print("   Watch Smart Policy Play Against OpenSpiel!")
        print("=" * 70)

        smart_policy = policies[2]  # SmartPolicy
        run_episode(client, smart_policy, visualize=True, delay=0.2)

        print("\nYou just watched REAL OpenSpiel Catch being played!")
        print("   - Every action was an HTTP call")
        print("   - Game logic runs in the server")
        print("   - Client only sends actions and receives observations\n")

        # Part 9: Policy competition
        print("Starting the showdown against REAL OpenSpiel...\n")
        evaluate_policies(client, policies, num_episodes=50)

        print("=" * 70)
        print("   Tutorial Complete!")
        print("=" * 70 + "\n")

    finally:
        # Cleanup: stop the server
        print("Stopping OpenSpiel server...")
        server_process.terminate()
        server_process.wait()
        print("Server stopped.\n")


if __name__ == "__main__":
    main()
