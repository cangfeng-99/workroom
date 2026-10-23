"""Minimal file service for the local demo workspace.

The root directory is supplied by server-side configuration only; HTTP input
may select a file name, never a directory. Existing ancestors of the root are
checked for links/reparse points before every operation, and the root itself
must be a plain directory. This module is still not an OS sandbox and does not
protect against a hostile local process replacing paths between the checks and
the actual read/write.

Stable error codes (``WorkspaceError.code``), for the HTTP layer to translate:
invalid_root, workspace_not_initialized, invalid_name, unsupported_type,
not_found, not_a_file, unsafe_path, file_too_large, content_too_large,
invalid_content, invalid_encoding, already_exists, create_failed, read_failed.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

MAX_FILE_BYTES = 64 * 1024
MAX_LISTED_FILES = 100
ALLOWED_SUFFIXES = frozenset({'.txt', '.md'})
WELCOME_NAME = 'welcome.md'
WELCOME_TEXT = (
    '这是本机演示工作区。\n\n'
    '授权后可以读取或创建 .txt、.md 文本文件。\n'
    '文件只保存在本机项目目录中，不会上传或执行。\n'
)

_RESERVED_NAMES = frozenset(
    {'con', 'prn', 'aux', 'nul', 'conin$', 'conout$'}
    | {f'com{index}' for index in range(1, 10)}
    | {f'lpt{index}' for index in range(1, 10)}
)
_INVALID_NAME_CHARS = frozenset('<>:"|?*')


class WorkspaceError(Exception):
    """Domain error carrying a stable code for user-facing translation."""

    def __init__(self, code: str, message: str = '') -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


class Workspace:
    """Fixed-root file operations for .txt/.md files directly under ``root``."""

    def __init__(self, root: Path) -> None:
        try:
            self.root = Path(root)
        except TypeError as exc:
            raise WorkspaceError('invalid_root', 'workspace root must be a path') from exc
        if not self.root.is_absolute():
            raise WorkspaceError('invalid_root', 'workspace root must be absolute')

    def initialize_demo(self) -> list[str]:
        """Create the root and welcome file once; never overwrite anything."""
        self._require_plain_ancestors()
        if os.path.lexists(self.root):
            self._require_ready_root()
        else:
            try:
                self.root.mkdir(parents=True)
            except OSError as exc:
                raise WorkspaceError('invalid_root', 'cannot create workspace root') from exc
            self._require_ready_root()

        welcome = self.root / WELCOME_NAME
        if os.path.lexists(welcome):
            try:
                existing = os.lstat(welcome)
            except OSError as exc:
                raise WorkspaceError('read_failed', 'cannot inspect welcome file') from exc
            self._check_file_stat(existing)
            return []
        try:
            self.create_text(WELCOME_NAME, WELCOME_TEXT)
        except WorkspaceError as exc:
            if exc.code == 'already_exists':
                return []
            raise
        return [WELCOME_NAME]

    def list_files(self) -> list[str]:
        """Return at most 100 safe .txt/.md file names, sorted by name."""
        self._require_plain_ancestors()
        self._require_ready_root()
        names: list[str] = []
        try:
            with os.scandir(self.root) as entries:
                for entry in entries:
                    if not self._is_listable_name(entry.name):
                        continue
                    try:
                        info = os.lstat(entry.path)
                    except OSError:
                        continue
                    if self._is_listable_stat(info):
                        names.append(entry.name)
        except OSError as exc:
            raise WorkspaceError('read_failed', 'cannot list workspace') from exc
        names.sort(key=str.casefold)
        return names[:MAX_LISTED_FILES]

    def read_text(self, name: str) -> str:
        """Read one file, rejecting unsafe paths, large files, and bad UTF-8."""
        self._validate_name(name)
        self._require_plain_ancestors()
        self._require_ready_root()
        path = self.root / name
        try:
            before = os.lstat(path)
        except FileNotFoundError as exc:
            raise WorkspaceError('not_found', 'file does not exist') from exc
        except OSError as exc:
            raise WorkspaceError('read_failed', 'cannot inspect file') from exc
        self._check_file_stat(before)
        if before.st_size > MAX_FILE_BYTES:
            raise WorkspaceError('file_too_large', 'file exceeds 64 KiB')

        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError as exc:
            raise WorkspaceError('not_found', 'file does not exist') from exc
        except OSError as exc:
            raise WorkspaceError('read_failed', 'cannot open file') from exc

        try:
            opened = os.fstat(descriptor)
            self._check_file_stat(opened)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise WorkspaceError('unsafe_path', 'file changed while opening')
            if opened.st_size > MAX_FILE_BYTES:
                raise WorkspaceError('file_too_large', 'file exceeds 64 KiB')
            chunks: list[bytes] = []
            remaining = MAX_FILE_BYTES + 1
            while remaining > 0:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b''.join(chunks)
        except WorkspaceError:
            raise
        except OSError as exc:
            raise WorkspaceError('read_failed', 'cannot read file') from exc
        finally:
            os.close(descriptor)

        if len(data) > MAX_FILE_BYTES:
            raise WorkspaceError('file_too_large', 'file exceeds 64 KiB')
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise WorkspaceError('invalid_encoding', 'file is not valid UTF-8') from exc

    def create_text(self, name: str, content: str) -> str:
        """Atomically create a new file; an existing name is never replaced."""
        self._validate_name(name)
        if not isinstance(content, str):
            raise WorkspaceError('invalid_content', 'content must be text')
        try:
            data = content.encode('utf-8')
        except UnicodeEncodeError as exc:
            raise WorkspaceError('invalid_content', 'content is not valid Unicode text') from exc
        if len(data) > MAX_FILE_BYTES:
            raise WorkspaceError('content_too_large', 'content exceeds 64 KiB')

        self._require_plain_ancestors()
        self._require_ready_root()
        path = self.root / name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError as exc:
            raise WorkspaceError('already_exists', 'file already exists') from exc
        except OSError as exc:
            raise WorkspaceError('create_failed', 'cannot create file') from exc

        try:
            self._check_file_stat(os.fstat(descriptor))
            with os.fdopen(descriptor, 'wb') as handle:
                descriptor = -1
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException as exc:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(path)
            except OSError:
                pass
            if isinstance(exc, WorkspaceError):
                raise
            if isinstance(exc, OSError):
                raise WorkspaceError('create_failed', 'cannot write file') from exc
            raise
        return name

    def _require_ready_root(self) -> None:
        try:
            info = os.lstat(self.root)
        except FileNotFoundError as exc:
            raise WorkspaceError('workspace_not_initialized', 'workspace is not initialized') from exc
        except OSError as exc:
            raise WorkspaceError('invalid_root', 'cannot inspect workspace root') from exc
        if stat.S_ISLNK(info.st_mode) or self._is_reparse(info) or not stat.S_ISDIR(info.st_mode):
            raise WorkspaceError('invalid_root', 'workspace root must be a plain directory')

    def _require_plain_ancestors(self) -> None:
        """Reject any existing link/reparse point on the way to the root."""
        current = self.root.parent
        while True:
            try:
                info = os.lstat(current)
            except FileNotFoundError:
                if current.parent == current:
                    return
                current = current.parent
                continue
            except OSError as exc:
                raise WorkspaceError('invalid_root', 'cannot inspect workspace parent') from exc
            if stat.S_ISLNK(info.st_mode) or self._is_reparse(info) or not stat.S_ISDIR(info.st_mode):
                raise WorkspaceError('invalid_root', 'workspace parent must be a plain directory')
            if current.parent == current:
                return
            current = current.parent

    def _validate_name(self, name: str) -> None:
        if not isinstance(name, str) or not name or len(name) > 255:
            raise WorkspaceError('invalid_name', 'file name is missing or too long')
        if name in {'.', '..'} or name[0] == '.':
            raise WorkspaceError('invalid_name', 'hidden file names are not allowed')
        if any(char in _INVALID_NAME_CHARS or char == '/' or char == '\\' for char in name):
            raise WorkspaceError('invalid_name', 'file name contains a forbidden character')
        if any(ord(char) < 32 for char in name):
            raise WorkspaceError('invalid_name', 'file name contains a control character')
        if name[-1] in ' .':
            raise WorkspaceError('invalid_name', 'file name cannot end with a space or dot')
        if name.split('.', 1)[0].lower() in _RESERVED_NAMES:
            raise WorkspaceError('invalid_name', 'file name is reserved by Windows')
        if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
            raise WorkspaceError('unsupported_type', 'only .txt and .md files are allowed')

    def _is_listable_name(self, name: str) -> bool:
        try:
            self._validate_name(name)
        except WorkspaceError:
            return False
        return True

    def _is_listable_stat(self, info: os.stat_result) -> bool:
        return (
            not stat.S_ISLNK(info.st_mode)
            and not self._is_reparse(info)
            and stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and not self._is_hidden(info)
            and info.st_size <= MAX_FILE_BYTES
        )

    def _check_file_stat(self, info: os.stat_result) -> None:
        if stat.S_ISLNK(info.st_mode) or self._is_reparse(info):
            raise WorkspaceError('unsafe_path', 'links and reparse points are not allowed')
        if not stat.S_ISREG(info.st_mode):
            raise WorkspaceError('not_a_file', 'path is not a regular file')
        if info.st_nlink != 1:
            raise WorkspaceError('unsafe_path', 'hard-linked files are not allowed')
        if self._is_hidden(info):
            raise WorkspaceError('unsafe_path', 'hidden files are not allowed')

    @staticmethod
    def _is_reparse(info: os.stat_result) -> bool:
        attributes = getattr(info, 'st_file_attributes', 0)
        return bool(attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))

    @staticmethod
    def _is_hidden(info: os.stat_result) -> bool:
        attributes = getattr(info, 'st_file_attributes', 0)
        return bool(attributes & getattr(stat, 'FILE_ATTRIBUTE_HIDDEN', 0))
