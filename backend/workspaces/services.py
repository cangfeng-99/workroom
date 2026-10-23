"""File service for an explicitly authorized local folder.

The root is always supplied by the server side; browser input can only choose a
path inside it. Every relative path is split on ``/`` and each segment is
validated and ``lstat``-checked level by level: no links/reparse points, no
hard-linked files, no hidden entries, no traversal. ``validate_root`` only
checks a folder, it never creates anything.

This module is still not an OS sandbox and cannot stop a hostile local process
from swapping paths between the checks and the actual read/write.

Stable error codes (``WorkspaceError.code``):
invalid_root, workspace_not_initialized, invalid_name, unsupported_type,
not_found, not_a_file, not_a_directory, unsafe_path, file_too_large,
content_too_large, invalid_content, invalid_encoding, binary_content,
invalid_revision, already_exists, create_failed, save_failed, read_failed.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path

MAX_FILE_BYTES = 64 * 1024
MAX_LISTED_FILES = 100
MAX_DIRECTORY_ENTRIES = MAX_LISTED_FILES
ALLOWED_SUFFIXES = frozenset(
    {
        '.txt',
        '.md',
        '.py',
        '.js',
        '.mjs',
        '.ts',
        '.jsx',
        '.tsx',
        '.json',
        '.html',
        '.htm',
        '.css',
        '.scss',
        '.vue',
        '.java',
        '.c',
        '.h',
        '.cpp',
        '.hpp',
        '.cs',
        '.go',
        '.rs',
        '.rb',
        '.php',
        '.kt',
        '.swift',
        '.lua',
        '.sql',
        '.sh',
        '.toml',
        '.yaml',
        '.yml',
        '.xml',
        '.ini',
    }
)
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
    """Root-bound file operations restricted to plain files and directories."""

    def __init__(self, root: Path) -> None:
        try:
            self.root = Path(root)
        except TypeError as exc:
            raise WorkspaceError('invalid_root', 'workspace root must be a path') from exc
        if not self.root.is_absolute():
            raise WorkspaceError('invalid_root', 'workspace root must be absolute')
        if str(self.root).startswith('\\\\'):
            raise WorkspaceError('invalid_root', 'UNC and device paths are not supported')

    # -- authorization -------------------------------------------------

    def validate_root(self) -> None:
        """Check that the root is an existing plain directory; never writes."""
        self._check_root('invalid_root')

    def initialize_demo(self) -> list[str]:
        """Create the demo root and welcome file once; never overwrite anything."""
        self._require_plain_ancestors()
        if os.path.lexists(self.root):
            self._check_root('invalid_root')
        else:
            try:
                self.root.mkdir(parents=True)
            except OSError as exc:
                raise WorkspaceError('invalid_root', 'cannot create workspace root') from exc
            self._check_root('invalid_root')

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

    # -- listing -------------------------------------------------------

    def list_directory(self, directory: str = '') -> list[dict[str, object]]:
        """List plain directories and editable files, at most 100 entries.

        ``directory`` is a relative path using ``/``; an empty string means the
        authorized root. Directories are listed before files, each sorted by
        case-insensitive name. Hidden, linked, hard-linked, oversized, and
        unsupported entries are skipped rather than reported.
        """
        folder = self._resolve_directory(directory)
        directories: list[dict[str, object]] = []
        files: list[dict[str, object]] = []
        try:
            with os.scandir(folder) as scan:
                for entry in scan:
                    try:
                        self._check_segment(entry.name)
                    except WorkspaceError:
                        continue
                    try:
                        info = os.lstat(entry.path)
                    except OSError:
                        continue
                    relative = f'{directory}/{entry.name}' if directory else entry.name
                    if stat.S_ISDIR(info.st_mode):
                        if self._is_link_or_reparse(info) or self._is_hidden(info):
                            continue
                        directories.append(
                            {'name': entry.name, 'path': relative, 'kind': 'dir'}
                        )
                    elif self._is_editable_file(info) and self._has_allowed_suffix(entry.name):
                        files.append(
                            {
                                'name': entry.name,
                                'path': relative,
                                'kind': 'file',
                                'size': info.st_size,
                            }
                        )
        except OSError as exc:
            raise WorkspaceError('read_failed', 'cannot list directory') from exc
        directories.sort(key=lambda item: str(item['name']).casefold())
        files.sort(key=lambda item: str(item['name']).casefold())
        return (directories + files)[:MAX_DIRECTORY_ENTRIES]

    def list_files(self, directory: str = '') -> list[str]:
        """Legacy helper: editable file names only, at most 100, sorted."""
        return [
            str(entry['name'])
            for entry in self.list_directory(directory)
            if entry['kind'] == 'file'
        ]

    # -- reading -------------------------------------------------------

    def read_document(self, path: str) -> tuple[str, str]:
        """Return ``(content, revision)`` for one editable UTF-8 file."""
        target = self._resolve(path)
        data = self._read_file(target)
        return self._decode(data), self._revision(data)

    def read_text(self, path: str) -> str:
        """Legacy helper: return content only."""
        return self.read_document(path)[0]

    # -- writing -------------------------------------------------------

    def create_text(self, path: str, content: str) -> str:
        """Atomically create a new file; an existing name is never replaced."""
        target = self._resolve(path)
        data = self._encode(content)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
        try:
            descriptor = os.open(target, flags, 0o600)
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
                os.unlink(target)
            except OSError:
                pass
            if isinstance(exc, WorkspaceError):
                raise
            if isinstance(exc, OSError):
                raise WorkspaceError('create_failed', 'cannot write file') from exc
            raise
        return path

    def save_text(self, path: str, content: str, expected_revision: str) -> str:
        """Atomically replace an existing file after a revision check.

        The original file is only replaced when its current revision still
        matches ``expected_revision``; a changed or deleted file raises
        ``conflict`` / ``not_found`` and is left untouched. The new content is
        written to a temporary file in the same directory and swapped in with
        ``os.replace``; on failure the temporary file is removed.
        """
        target = self._resolve(path)
        data = self._encode(content)
        if not isinstance(expected_revision, str) or not expected_revision:
            raise WorkspaceError('invalid_revision', 'expected revision is required')
        if len(expected_revision) > 128:
            raise WorkspaceError('invalid_revision', 'expected revision is malformed')

        try:
            before = os.lstat(target)
        except FileNotFoundError as exc:
            raise WorkspaceError('not_found', 'file does not exist') from exc
        except OSError as exc:
            raise WorkspaceError('read_failed', 'cannot inspect file') from exc
        self._check_file_stat(before)
        if before.st_size > MAX_FILE_BYTES:
            raise WorkspaceError('file_too_large', 'file exceeds 64 KiB')

        current = self._read_file(target)
        if self._revision(current) != expected_revision:
            raise WorkspaceError('conflict', 'file changed since it was read')

        temp_path: str | None = None
        try:
            descriptor, temp_path = tempfile.mkstemp(
                prefix=f'.{target.name}.',
                suffix='.tmp',
                dir=str(target.parent),
            )
            with os.fdopen(descriptor, 'wb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temp_path, stat.S_IMODE(before.st_mode))
            except OSError:
                pass
            try:
                now = os.lstat(target)
            except FileNotFoundError as exc:
                raise WorkspaceError('not_found', 'file disappeared before save') from exc
            if (now.st_dev, now.st_ino) != (before.st_dev, before.st_ino):
                raise WorkspaceError('conflict', 'file changed while saving')
            if self._revision(self._read_file(target)) != expected_revision:
                raise WorkspaceError('conflict', 'file changed while saving')
            os.replace(temp_path, target)
            temp_path = None
        except WorkspaceError:
            raise
        except OSError as exc:
            raise WorkspaceError('save_failed', 'cannot save file') from exc
        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
        return self._revision(data)

    # -- root and path checks ------------------------------------------

    def _check_root(self, missing_code: str) -> None:
        self._require_plain_ancestors()
        try:
            info = os.lstat(self.root)
        except FileNotFoundError as exc:
            raise WorkspaceError(missing_code, 'workspace root is missing') from exc
        except OSError as exc:
            raise WorkspaceError('invalid_root', 'cannot inspect workspace root') from exc
        if self._is_link_or_reparse(info) or not stat.S_ISDIR(info.st_mode):
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
            if self._is_link_or_reparse(info) or not stat.S_ISDIR(info.st_mode):
                raise WorkspaceError('invalid_root', 'workspace parent must be a plain directory')
            if current.parent == current:
                return
            current = current.parent

    def _resolve(self, relative: str) -> Path:
        """Validate a relative file path and return its absolute location."""
        segments = self._split(relative)
        self._check_root('workspace_not_initialized')
        current = self.root
        for segment in segments[:-1]:
            current = current / segment
            try:
                info = os.lstat(current)
            except FileNotFoundError as exc:
                raise WorkspaceError('not_found', 'directory does not exist') from exc
            except OSError as exc:
                raise WorkspaceError('read_failed', 'cannot inspect directory') from exc
            self._check_directory_stat(info)
        target = current / segments[-1]
        if not self._has_allowed_suffix(segments[-1]):
            raise WorkspaceError('unsupported_type', 'file type is not editable')
        return target

    def _resolve_directory(self, directory: str) -> Path:
        if directory == '':
            self._check_root('workspace_not_initialized')
            return self.root
        segments = self._split(directory)
        self._check_root('workspace_not_initialized')
        current = self.root
        for segment in segments:
            current = current / segment
            try:
                info = os.lstat(current)
            except FileNotFoundError as exc:
                raise WorkspaceError('not_found', 'directory does not exist') from exc
            except OSError as exc:
                raise WorkspaceError('read_failed', 'cannot inspect directory') from exc
            self._check_directory_stat(info)
        return current

    def _split(self, relative: str) -> list[str]:
        if not isinstance(relative, str):
            raise WorkspaceError('invalid_name', 'path must be text')
        if relative == '':
            raise WorkspaceError('invalid_name', 'path is missing')
        if '\\' in relative:
            raise WorkspaceError('invalid_name', 'path must use "/" separators')
        segments = relative.split('/')
        for segment in segments:
            self._check_segment(segment)
        return segments

    def _check_segment(self, segment: str) -> None:
        if not isinstance(segment, str) or not segment or len(segment) > 255:
            raise WorkspaceError('invalid_name', 'path segment is missing or too long')
        if segment in {'.', '..'} or segment[0] == '.':
            raise WorkspaceError('invalid_name', 'hidden or relative segments are not allowed')
        if any(char in _INVALID_NAME_CHARS or char == '/' or char == ':' for char in segment):
            raise WorkspaceError('invalid_name', 'path segment contains a forbidden character')
        if any(ord(char) < 32 for char in segment):
            raise WorkspaceError('invalid_name', 'path segment contains a control character')
        if segment[-1] in ' .':
            raise WorkspaceError('invalid_name', 'path segment cannot end with a space or dot')
        if segment.split('.', 1)[0].lower() in _RESERVED_NAMES:
            raise WorkspaceError('invalid_name', 'path segment is reserved by Windows')

    # -- file inspection ------------------------------------------------

    def _read_file(self, target: Path) -> bytes:
        try:
            before = os.lstat(target)
        except FileNotFoundError as exc:
            raise WorkspaceError('not_found', 'file does not exist') from exc
        except OSError as exc:
            raise WorkspaceError('read_failed', 'cannot inspect file') from exc
        self._check_file_stat(before)
        if before.st_size > MAX_FILE_BYTES:
            raise WorkspaceError('file_too_large', 'file exceeds 64 KiB')

        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0)
        try:
            descriptor = os.open(target, flags)
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
        return data

    @staticmethod
    def _decode(data: bytes) -> str:
        if b'\x00' in data:
            # A NUL byte never occurs in editable text; treat it as binary.
            raise WorkspaceError('binary_content', 'file contains NUL bytes')
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise WorkspaceError('invalid_encoding', 'file is not valid UTF-8') from exc

    @staticmethod
    def _encode(content: str) -> bytes:
        if not isinstance(content, str):
            raise WorkspaceError('invalid_content', 'content must be text')
        try:
            data = content.encode('utf-8')
        except UnicodeEncodeError as exc:
            raise WorkspaceError('invalid_content', 'content is not valid Unicode text') from exc
        if len(data) > MAX_FILE_BYTES:
            raise WorkspaceError('content_too_large', 'content exceeds 64 KiB')
        return data

    @staticmethod
    def _revision(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _check_file_stat(self, info: os.stat_result) -> None:
        if self._is_link_or_reparse(info):
            raise WorkspaceError('unsafe_path', 'links and reparse points are not allowed')
        if not stat.S_ISREG(info.st_mode):
            raise WorkspaceError('not_a_file', 'path is not a regular file')
        if info.st_nlink != 1:
            raise WorkspaceError('unsafe_path', 'hard-linked files are not allowed')
        if self._is_hidden(info):
            raise WorkspaceError('unsafe_path', 'hidden files are not allowed')

    @staticmethod
    def _check_directory_stat(info: os.stat_result) -> None:
        if Workspace._is_link_or_reparse(info):
            raise WorkspaceError('unsafe_path', 'links and reparse points are not allowed')
        if not stat.S_ISDIR(info.st_mode):
            raise WorkspaceError('not_a_directory', 'path is not a directory')
        if Workspace._is_hidden(info):
            raise WorkspaceError('unsafe_path', 'hidden directories are not allowed')

    def _is_editable_file(self, info: os.stat_result) -> bool:
        return (
            not self._is_link_or_reparse(info)
            and stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and not self._is_hidden(info)
            and info.st_size <= MAX_FILE_BYTES
        )

    @staticmethod
    def _has_allowed_suffix(name: str) -> bool:
        return Path(name).suffix.lower() in ALLOWED_SUFFIXES

    @staticmethod
    def _is_link_or_reparse(info: os.stat_result) -> bool:
        if stat.S_ISLNK(info.st_mode):
            return True
        attributes = getattr(info, 'st_file_attributes', 0)
        return bool(attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))

    @staticmethod
    def _is_hidden(info: os.stat_result) -> bool:
        attributes = getattr(info, 'st_file_attributes', 0)
        return bool(attributes & getattr(stat, 'FILE_ATTRIBUTE_HIDDEN', 0))
