"""Workspace lifecycle manager for swe_env.

Manages a temporary directory that persists for the life of an environment
instance. Contents are cleared on reset(); the directory itself is deleted
on close(). Uses tempfile.TemporaryDirectory for automatic cleanup if
close() is never called (e.g. due to an unhandled exception).
"""

import shutil
import tempfile
from pathlib import Path


class Workspace:
    """Manages a temporary workspace directory for an SWEEnvironment instance.

    The directory is created eagerly in __init__ and persists across episode
    resets. ``reset()`` clears the contents; ``close()`` removes the directory.
    TemporaryDirectory's __del__ ensures cleanup even if close() is missed.
    """

    def __init__(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="swe_workspace_")
        self._path = Path(self._tmpdir.name)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def is_active(self) -> bool:
        return self._path.exists()

    def reset(self) -> Path:
        """Clear workspace contents for a new episode, keeping the directory.

        Returns:
            Path to the (now empty) workspace directory.
        """
        for child in self._path.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        return self._path

    def close(self) -> None:
        """Remove the workspace directory and all its contents."""
        self._tmpdir.cleanup()
