"""Read-only folder metadata for the in-page folder picker.

The browser dialog can only list directory names and paths. Nothing here opens
a file, writes to disk, or touches the session. Every accepted path is checked
with :meth:`workspaces.services.Workspace.validate_root`, so the same rules
that protect authorization (absolute local plain directories, no links/reparse
on the path, no UNC/device roots) also apply to browsing.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path, PureWindowsPath

from workspaces.services import Workspace, WorkspaceError

MAX_BROWSE_ENTRIES = 100


class PickerError(Exception):
    """Picker failure carrying a stable code for the JSON response."""

    def __init__(self, code: str, message: str = '') -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def drives() -> list[dict[str, str]]:
    """Return available local drive roots (or the platform root) as entries."""
    lister = getattr(os, 'listdrives', None)
    if lister is not None:
        try:
            roots = [str(item) for item in lister()]
        except OSError:
            roots = []
    elif os.name == 'nt':
        roots = [
            f'{letter}:\\'
            for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
            if os.path.exists(f'{letter}:\\')
        ]
    else:
        roots = [os.sep]
    return [
        {'name': root.rstrip('\\/') or root, 'path': root}
        for root in roots
    ]


def _validated_path(raw: str) -> Path:
    if not isinstance(raw, str) or len(raw) > 1024:
        raise PickerError('invalid_path', 'path must be a short text value')
    if any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise PickerError('invalid_path', 'path contains a control character')

    pure = PureWindowsPath(raw)
    if (
        not pure.is_absolute()
        or not pure.drive
        or pure.drive.startswith('\\\\')
        or raw.startswith(('\\\\', '//'))
        or any(part in {'.', '..'} for part in pure.parts)
    ):
        raise PickerError('invalid_path', 'path must be a local absolute directory')

    target = Path(raw)
    try:
        workspace = Workspace(target)
    except WorkspaceError as exc:
        raise PickerError('invalid_path', str(exc)) from exc
    try:
        info = os.lstat(target)
    except FileNotFoundError as exc:
        raise PickerError('not_found', 'directory does not exist') from exc
    except OSError as exc:
        raise PickerError('unreadable', 'cannot inspect directory') from exc
    if workspace._is_link_or_reparse(info):
        raise PickerError('unsafe_path', 'links and reparse points are not browsable')
    if not stat.S_ISDIR(info.st_mode):
        raise PickerError('not_a_directory', 'path is not a directory')
    try:
        workspace.validate_root()
    except WorkspaceError as exc:
        raise PickerError('unsafe_path', str(exc)) from exc
    return target


def _parent_of(target: Path) -> str:
    parent = target.parent
    return '' if parent == target else str(parent)


def browse(raw: str = '') -> dict[str, object]:
    """Return ``path, parent, drives, directories, truncated`` for ``raw``.

    An empty path returns the drive starting point without browsing anything.
    Only plain, visible child directories are listed; files are never opened.
    """
    if raw == '':
        return {
            'path': '',
            'parent': '',
            'drives': drives(),
            'directories': [],
            'truncated': False,
        }

    target = _validated_path(raw)
    workspace = Workspace(target)
    directories: list[dict[str, str]] = []
    try:
        with os.scandir(target) as scan:
            for entry in scan:
                if entry.name.startswith('.'):
                    continue
                try:
                    info = os.lstat(entry.path)
                except OSError:
                    continue
                if not stat.S_ISDIR(info.st_mode):
                    continue
                if workspace._is_link_or_reparse(info) or workspace._is_hidden(info):
                    continue
                directories.append({'name': entry.name, 'path': str(Path(entry.path))})
    except OSError as exc:
        raise PickerError('unreadable', 'cannot list directory') from exc

    directories.sort(key=lambda item: item['name'].casefold())
    truncated = len(directories) > MAX_BROWSE_ENTRIES
    return {
        'path': str(target),
        'parent': _parent_of(target),
        'drives': drives(),
        'directories': directories[:MAX_BROWSE_ENTRIES],
        'truncated': truncated,
    }
