"""File editor tool module for swe_env.

Provides a ``file_editor`` MCP tool with operations: view, create,
str_replace, insert, undo_edit. Follows the same interface shape as
OpenHands' str_replace_editor so agents trained on that tool work
without modification.
"""

import re
from pathlib import Path
from typing import Any, Callable, Dict, List

from fastmcp import FastMCP

MAX_UNDO_HISTORY = 5


class FileEditorToolModule:
    """Structured file editing with undo support.

    Maintains per-file undo history (stack of previous contents) that
    persists across steps within an episode and is cleared on reset.
    """

    def __init__(self, get_workspace: Callable[[], Path]) -> None:
        self._get_workspace = get_workspace
        self._undo_history: Dict[str, List[str]] = {}

    def register(self, mcp: FastMCP) -> None:
        get_workspace = self._get_workspace
        undo_history = self._undo_history

        def _resolve_path(path_str: str) -> Path:
            p = Path(path_str)
            if not p.is_absolute():
                p = get_workspace() / p
            return p.resolve()

        def _validate_path(command: str, path: Path) -> str | None:
            if command == "create":
                if path.exists():
                    return (
                        f"File already exists at: {path}. "
                        "Cannot overwrite files using command `create`."
                    )
            elif command != "view":
                if not path.exists():
                    return f"The path {path} does not exist."
                if path.is_dir():
                    return (
                        f"The path {path} is a directory and only the "
                        "`view` command can be used on directories."
                    )
            else:
                if not path.exists():
                    return f"The path {path} does not exist."
            return None

        def _save_history(path: Path, content: str) -> None:
            key = str(path)
            if key not in undo_history:
                undo_history[key] = []
            undo_history[key].append(content)
            if len(undo_history[key]) > MAX_UNDO_HISTORY:
                undo_history[key] = undo_history[key][-MAX_UNDO_HISTORY:]

        def _make_output(content: str, path: Path, start_line: int = 1) -> str:
            lines = content.split("\n")
            numbered = "\n".join(
                f"{i + start_line:6}\t{line}" for i, line in enumerate(lines)
            )
            return (
                f"Here's the result of running `cat -n` on {path}:\n" + numbered + "\n"
            )

        def _view(path: Path, view_range: str) -> Dict[str, Any]:
            if path.is_dir():
                entries = []
                for item in sorted(path.iterdir()):
                    if item.name.startswith("."):
                        continue
                    name = item.name + "/" if item.is_dir() else item.name
                    entries.append(name)
                listing = "\n".join(entries)
                return {
                    "output": f"Here's the files and directories up to 1 "
                    f"level deep in {path}:\n{listing}\n",
                    "exit_code": 0,
                }

            content = path.read_text()
            if view_range:
                parts = view_range.split(",")
                if len(parts) != 2:
                    return {
                        "output": "Invalid view_range format. Use 'start,end'.",
                        "exit_code": 1,
                    }
                start = int(parts[0])
                end = int(parts[1])
                lines = content.split("\n")
                num_lines = len(lines)
                if end == -1:
                    end = num_lines
                if start < 1 or start > num_lines:
                    return {
                        "output": f"Invalid view_range: start line {start} "
                        f"is out of range [1, {num_lines}].",
                        "exit_code": 1,
                    }
                if end < start or end > num_lines:
                    return {
                        "output": f"Invalid view_range: end line {end} "
                        f"is out of range [{start}, {num_lines}].",
                        "exit_code": 1,
                    }
                selected = lines[start - 1 : end]
                snippet = "\n".join(selected)
                return {
                    "output": _make_output(snippet, path, start_line=start),
                    "exit_code": 0,
                }

            return {"output": _make_output(content, path), "exit_code": 0}

        def _create(path: Path, file_text: str) -> Dict[str, Any]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(file_text)
            _save_history(path, file_text)
            return {
                "output": f"File created successfully at: {path}",
                "exit_code": 0,
            }

        def _str_replace(path: Path, old_str: str, new_str: str) -> Dict[str, Any]:
            if old_str == new_str:
                return {
                    "output": "No replacement was performed. "
                    "`new_str` and `old_str` must be different.",
                    "exit_code": 1,
                }

            content = path.read_text()
            escaped = re.escape(old_str)
            matches = list(re.finditer(escaped, content))

            if len(matches) == 0:
                return {
                    "output": f"No replacement was performed, old_str "
                    f"`{old_str}` did not appear verbatim in {path}.",
                    "exit_code": 1,
                }

            if len(matches) > 1:
                line_numbers = []
                for m in matches:
                    line_num = content[: m.start()].count("\n") + 1
                    line_numbers.append(line_num)
                line_numbers = sorted(set(line_numbers))
                return {
                    "output": f"No replacement was performed. Multiple "
                    f"occurrences of old_str `{old_str}` in lines "
                    f"{line_numbers}. Please ensure it is unique.",
                    "exit_code": 1,
                }

            _save_history(path, content)
            new_content = content.replace(old_str, new_str, 1)
            path.write_text(new_content)

            replacement_line = content[: matches[0].start()].count("\n") + 1
            start = max(1, replacement_line - 3)
            end_line = replacement_line + new_str.count("\n") + 3
            lines = new_content.split("\n")
            end_line = min(end_line, len(lines))
            snippet = "\n".join(lines[start - 1 : end_line])

            return {
                "output": f"The file {path} has been edited. "
                + _make_output(snippet, path, start_line=start),
                "exit_code": 0,
            }

        def _insert(path: Path, insert_line: int, new_str: str) -> Dict[str, Any]:
            content = path.read_text()
            lines = content.split("\n")
            num_lines = len(lines)

            if insert_line < 0 or insert_line > num_lines:
                return {
                    "output": f"Invalid insert_line: {insert_line}. "
                    f"Must be in range [0, {num_lines}].",
                    "exit_code": 1,
                }

            _save_history(path, content)
            new_lines = new_str.split("\n")
            result_lines = lines[:insert_line] + new_lines + lines[insert_line:]
            path.write_text("\n".join(result_lines))

            start = max(1, insert_line + 1 - 3)
            end_line = min(len(result_lines), insert_line + len(new_lines) + 3)
            snippet = "\n".join(result_lines[start - 1 : end_line])

            return {
                "output": f"The file {path} has been edited. "
                + _make_output(snippet, path, start_line=start),
                "exit_code": 0,
            }

        def _undo_edit(path: Path) -> Dict[str, Any]:
            key = str(path)
            if key not in undo_history or not undo_history[key]:
                return {
                    "output": f"No undo history available for {path}.",
                    "exit_code": 1,
                }
            previous = undo_history[key].pop()
            path.write_text(previous)
            return {
                "output": f"Last edit to {path} undone successfully. "
                + _make_output(previous, path),
                "exit_code": 0,
            }

        @mcp.tool()
        def file_editor(
            command: str,
            path: str,
            file_text: str = "",
            old_str: str = "",
            new_str: str = "",
            insert_line: int = -1,
            view_range: str = "",
        ) -> Dict[str, Any]:
            """Edit files with structured operations.

            Args:
                command: One of view, create, str_replace, insert, undo_edit.
                path: File path (absolute or relative to workspace).
                file_text: File content for create command.
                old_str: String to find for str_replace.
                new_str: Replacement string for str_replace/insert.
                insert_line: Line number for insert (0=before first line).
                view_range: Line range for view as 'start,end' (1-indexed, end=-1 for EOF).

            Returns:
                Dict with output and exit_code.
            """
            resolved = _resolve_path(path)

            err = _validate_path(command, resolved)
            if err:
                return {"output": err, "exit_code": 1}

            if command == "view":
                return _view(resolved, view_range)
            elif command == "create":
                return _create(resolved, file_text)
            elif command == "str_replace":
                return _str_replace(resolved, old_str, new_str)
            elif command == "insert":
                return _insert(resolved, insert_line, new_str)
            elif command == "undo_edit":
                return _undo_edit(resolved)
            else:
                return {
                    "output": f"Unrecognized command: {command}. "
                    "Expected one of: view, create, str_replace, insert, undo_edit.",
                    "exit_code": 1,
                }

    def reset(self) -> None:
        self._undo_history.clear()

    def cleanup(self) -> None:
        self._undo_history.clear()
