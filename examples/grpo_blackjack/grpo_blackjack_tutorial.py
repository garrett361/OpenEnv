#!/usr/bin/env python3
"""
GRPO BlackJack Tutorial - Training LLMs in ANY Environment with OpenEnv

This script is a port of grpo_blackjack_tutorial.ipynb.

Usage:
    # Start the server first (in another terminal):
    export OPENENV_PATH=$PWD
    export PYTHONPATH="${OPENENV_PATH}:${PYTHONPATH}"
    OPENSPIEL_GAME=blackjack uvicorn envs.openspiel_env.server.app:app --host 0.0.0.0 --port 8004

    # Then run this script:
    python grpo_blackjack_tutorial.py
"""

import sys
import os
import random
from pathlib import Path

# ==============================================================================
# Environment Setup
# ==============================================================================

# Fix for Monarch/Torchstore Rust bindings
conda_prefix = os.environ.get('CONDA_PREFIX', sys.prefix)
lib_path = f"{conda_prefix}/lib"

if 'LD_LIBRARY_PATH' in os.environ:
    if lib_path not in os.environ['LD_LIBRARY_PATH']:
        os.environ['LD_LIBRARY_PATH'] = f"{lib_path}:{os.environ['LD_LIBRARY_PATH']}"
else:
    os.environ['LD_LIBRARY_PATH'] = lib_path

# Add OpenEnv to path
openenv_path = os.environ.get('OPENENV_PATH', '/proj/data-eng/goon/garrett361/openenv/')
if openenv_path not in sys.path:
    sys.path.insert(0, openenv_path)

print("Environment configured")


# ==============================================================================
# Part 1: Exploring OpenEnv
# ==============================================================================

def show_openenv_observation(observation):
    """Pretty print an OpenEnv observation."""
    print("Observation:")
    print(f"  Game phase: {observation.game_phase}")
    print(f"  Legal actions: {observation.legal_actions}")
    print(f"  Info state shape: {len(observation.info_state)}")
    print(f"  Info state (first 10): {observation.info_state[:10]}")


def explore_openenv(server_url: str = "http://localhost:8004"):
    """Connect to OpenEnv and explore the interface."""
    from envs.openspiel_env import OpenSpielEnv, OpenSpielAction

    print("\n" + "=" * 60)
    print("Part 1: Exploring OpenEnv")
    print("=" * 60)

    env = OpenSpielEnv(base_url=server_url)
    print("\nConnected to BlackJack environment")
    print("\nResetting environment...\n")

    # Reset and observe
    result = env.reset()
    show_openenv_observation(result.observation)

    env.close()
    print("\nOpenEnv interface exploration complete!")


# ==============================================================================
# Part 2: Benchmarking Baseline Policies
# ==============================================================================

def play_random_policy(server_url: str, num_games: int = 100):
    """
    Benchmark random policy on OpenEnv environment.

    Args:
        server_url: OpenEnv server URL
        num_games: Number of games to play

    Returns:
        dict with statistics
    """
    from envs.openspiel_env import OpenSpielEnv, OpenSpielAction

    env = OpenSpielEnv(base_url=server_url)
    wins = losses = pushes = 0

    for _ in range(num_games):
        result = env.reset()
        done = False
        step_count = 0

        while not done and step_count < 10:
            # Random action
            action = random.choice(result.observation.legal_actions)
            result = env.step(OpenSpielAction(action_id=action, game_name="blackjack"))
            done = result.done
            step_count += 1

        # Count outcome
        if result.reward > 0:
            wins += 1
        elif result.reward < 0:
            losses += 1
        else:
            pushes += 1

    env.close()

    return {
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": wins / num_games,
        "total_games": num_games
    }


def benchmark_random_policy(server_url: str = "http://localhost:8004"):
    """Run random policy benchmark."""
    print("\n" + "=" * 60)
    print("Part 2: Benchmarking Baseline Policies")
    print("=" * 60)

    print("\nRunning random policy baseline...\n")

    # Play 100 games with random actions
    stats = play_random_policy(server_url, num_games=100)

    print("Random Policy Results:")
    print(f"   Games played: {stats['total_games']}")
    print(f"   Wins: {stats['wins']}")
    print(f"   Losses: {stats['losses']}")
    print(f"   Pushes: {stats['pushes']}")
    print(f"   Win rate: {stats['win_rate']:.1%}")
    print("\nNote: Optimal BlackJack strategy achieves ~43% win rate")


# ==============================================================================
# Part 3: GRPO Training (requires Forge infrastructure)
# ==============================================================================

async def run_grpo_training(config_path: str = "blackjack.yaml", steps: int = 100):
    """
    Run GRPO training with Forge.

    This requires the full Forge infrastructure (GPU cluster, vLLM, etc).
    Only runs if Forge is available and properly configured.
    """
    print("\n" + "=" * 60)
    print("Part 3: GRPO Training with Forge")
    print("=" * 60)

    try:
        # These imports trigger the heavy dependencies
        from grpo_utils import setup_forge_training

        print("\nInitializing Forge infrastructure...")
        print("This will:")
        print("  - Load the Qwen 1.5B model")
        print("  - Initialize vLLM inference servers")
        print("  - Setup distributed training (TorchTitan)")
        print("  - Create replay buffer and reference model")
        print("\nThis may take 1-2 minutes...\n")

        # Initialize everything with one function call
        trainer = await setup_forge_training(config_path)
        print("\nReady to train!")

        print("\nStarting GRPO training!\n")
        print("Watch the logs to see:")
        print("  - Games being played (with actions and outcomes)")
        print("  - Win rate improving over time")
        print("  - Training steps updating the policy")
        print("\n" + "=" * 60 + "\n")

        # Run training
        results = await trainer.run(steps=steps)

        print("\n" + "=" * 60)
        print("\nTraining complete!")

        # Shutdown
        await trainer.shutdown()
        print("Shutdown complete")

        return results

    except ImportError as e:
        print(f"\nSkipping GRPO training - Forge dependencies not available: {e}")
        print("To run training, ensure you have:")
        print("  - torchstore")
        print("  - monarch")
        print("  - forge")
        print("  - A properly configured GPU cluster")
        return None
    except Exception as e:
        print(f"\nError during training: {e}")
        raise


# ==============================================================================
# Main Entry Point
# ==============================================================================

def main():
    """Run the tutorial."""
    server_url = "http://localhost:8004"

    print("=" * 60)
    print("GRPO BlackJack Tutorial")
    print("Training LLMs in ANY Environment with OpenEnv")
    print("=" * 60)

    # Part 1: Explore OpenEnv
    explore_openenv(server_url)

    # Part 2: Benchmark random policy
    benchmark_random_policy(server_url)

    # Part 3: GRPO Training (optional - requires Forge)
    # Uncomment to run training if you have Forge infrastructure:
    #
    # import asyncio
    # asyncio.run(run_grpo_training("blackjack.yaml", steps=100))

    print("\n" + "=" * 60)
    print("Tutorial Complete!")
    print("=" * 60)
    print("\nKey Takeaways:")
    print("  1. OpenEnv is a universal spec for RL environments")
    print("  2. One training loop works everywhere - switch environments by changing a URL")
    print("  3. Forge abstracts distributed RL complexity")
    print("  4. GRPO enables stable LLM training with group-relative advantages")
    print("\nNext Steps:")
    print("  - Try different OpenSpiel games: tic_tac_toe, connect_four, go")
    print("  - Explore other OpenEnv backends: Atari, FinRL")
    print("  - Run full training with: python -m apps.grpo.blackjack_main_fixed")


if __name__ == "__main__":
    main()
