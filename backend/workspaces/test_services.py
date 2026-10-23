"""Contract tests for the local demo workspace file service."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest
from django.conf import settings

from workspaces.services import (
    MAX_FILE_BYTES,
    WELCOME_NAME,
    WELCOME_TEXT,
    Workspace,
    WorkspaceError,
)

INVALID_NAMES = [
    '',
    '.',
    '..',
    '../escape.txt',
    '..\\escape.txt',
    'sub\\escape.txt',
    'sub/../../escape.txt',
    'sub//escape.txt',
    'sub/escape.txt/',
    '/absolute.txt',
    '\\absolute.txt',
    'C:\\absolute.txt',
    'C:relative.txt',
    '\\\\server\\share\\escape.txt',
    'name.txt:stream',
    'CON',
    'con.txt',
    'AUX.md',
    'NUL.txt',
    'COM1.txt',
    'LPT9.md',
    'CONIN$.txt',
    'CONOUT$.txt',
    'trailing.txt ',
    'trailing.txt.',
    '.hidden.txt',
    'bad\x00name.txt',
    'bad?name.txt',
]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / 'demo'


@pytest.fixture
def ws(root: Path) -> Workspace:
    return Workspace(root)


@pytest.fixture
def sentinel(tmp_path: Path) -> Path:
    outside = tmp_path / 'outside'
    outside.mkdir()
    marker = outside / 'sentinel.bin'
    marker.write_bytes(b'DO-NOT-TOUCH')
    return marker


def assert_code(expected: str, action) -> None:
    with pytest.raises(WorkspaceError) as caught:
        action()
    assert caught.value.code == expected


def test_settings_points_at_project_demo_directory() -> None:
    assert Path(settings.WORKSPACE_ROOT) == Path(settings.PROJECT_ROOT) / '.tools' / 'workspaces' / 'demo'


def test_initialize_demo_creates_root_and_welcome(ws: Workspace, root: Path) -> None:
    created = ws.initialize_demo()

    assert created == [WELCOME_NAME]
    assert root.is_dir()
    assert (root / WELCOME_NAME).read_text(encoding='utf-8') == WELCOME_TEXT
    assert ws.list_files() == [WELCOME_NAME]


def test_initialize_demo_never_overwrites_existing_files(ws: Workspace, root: Path, sentinel: Path) -> None:
    root.mkdir()
    (root / WELCOME_NAME).write_text('custom welcome', encoding='utf-8')
    (root / 'kept.md').write_text('keep me', encoding='utf-8')

    created = ws.initialize_demo()

    assert created == []
    assert (root / WELCOME_NAME).read_text(encoding='utf-8') == 'custom welcome'
    assert (root / 'kept.md').read_text(encoding='utf-8') == 'keep me'
    assert sentinel.read_bytes() == b'DO-NOT-TOUCH'


def test_list_files_filters_names_and_kinds(ws: Workspace, root: Path) -> None:
    ws.initialize_demo()
    (root / 'a.txt').write_text('a', encoding='utf-8')
    (root / 'b.md').write_text('b', encoding='utf-8')
    (root / 'upper.TXT').write_text('u', encoding='utf-8')
    (root / 'notes.py').write_text('n', encoding='utf-8')
    (root / 'archive.zip').write_text('z', encoding='utf-8')
    (root / '.hidden.txt').write_text('h', encoding='utf-8')
    (root / 'folder.txt').mkdir()

    names = ws.list_files()

    assert names == sorted(
        [WELCOME_NAME, 'a.txt', 'b.md', 'upper.TXT', 'notes.py'],
        key=str.casefold,
    )


def test_list_files_is_capped_at_one_hundred(ws: Workspace, root: Path) -> None:
    ws.initialize_demo()
    for index in range(105):
        (root / f'f{index:03}.txt').write_text('x', encoding='utf-8')

    names = ws.list_files()

    assert len(names) == 100


def test_create_then_read_round_trip_on_disk(ws: Workspace, root: Path) -> None:
    ws.initialize_demo()
    content = '你好，工作区\nsecond line 🙂\n'

    returned = ws.create_text('note.md', content)

    assert returned == 'note.md'
    assert ws.read_text('note.md') == content
    assert (root / 'note.md').read_bytes() == content.encode('utf-8')
    assert 'note.md' in ws.list_files()


def test_create_accepts_exactly_sixty_four_kib(ws: Workspace) -> None:
    ws.initialize_demo()
    content = 'a' * MAX_FILE_BYTES

    ws.create_text('limit.txt', content)

    assert ws.read_text('limit.txt') == content


def test_create_rejects_oversized_content_without_writing(ws: Workspace, root: Path) -> None:
    ws.initialize_demo()

    assert_code('content_too_large', lambda: ws.create_text('big.txt', 'a' * (MAX_FILE_BYTES + 1)))

    assert not (root / 'big.txt').exists()


def test_create_rejects_non_text_content(ws: Workspace) -> None:
    ws.initialize_demo()

    assert_code('invalid_content', lambda: ws.create_text('bad.txt', b'bytes'))


def test_create_never_overwrites_existing_file(ws: Workspace, root: Path, sentinel: Path) -> None:
    ws.initialize_demo()
    target = root / 'taken.txt'
    target.write_text('original', encoding='utf-8')

    assert_code('already_exists', lambda: ws.create_text('taken.txt', 'replacement'))

    assert target.read_text(encoding='utf-8') == 'original'
    assert sentinel.read_bytes() == b'DO-NOT-TOUCH'


@pytest.mark.parametrize('name', INVALID_NAMES)
def test_invalid_names_are_rejected_without_side_effects(ws: Workspace, root: Path, name: str) -> None:
    ws.initialize_demo()
    before = set(os.listdir(root))

    assert_code('invalid_name', lambda: ws.create_text(name, 'payload'))
    assert_code('invalid_name', lambda: ws.read_text(name))

    assert set(os.listdir(root)) == before


@pytest.mark.parametrize('name', ['image.png', 'archive.zip', 'no_suffix', 'name.txt.exe'])
def test_unsupported_suffixes_are_rejected(ws: Workspace, name: str) -> None:
    ws.initialize_demo()

    assert_code('unsupported_type', lambda: ws.create_text(name, 'x'))
    assert_code('unsupported_type', lambda: ws.read_text(name))


def test_read_missing_file(ws: Workspace) -> None:
    ws.initialize_demo()

    assert_code('not_found', lambda: ws.read_text('missing.txt'))


def test_read_directory_with_text_suffix(ws: Workspace, root: Path) -> None:
    ws.initialize_demo()
    (root / 'folder.txt').mkdir()

    assert_code('not_a_file', lambda: ws.read_text('folder.txt'))


def test_read_rejects_oversized_existing_file(ws: Workspace, root: Path) -> None:
    ws.initialize_demo()
    (root / 'huge.txt').write_bytes(b'a' * (MAX_FILE_BYTES + 1))

    assert_code('file_too_large', lambda: ws.read_text('huge.txt'))


def test_read_rejects_invalid_utf8(ws: Workspace, root: Path) -> None:
    ws.initialize_demo()
    (root / 'latin1.txt').write_bytes(b'caf\xe9')

    assert_code('invalid_encoding', lambda: ws.read_text('latin1.txt'))


def test_operations_before_initialize_are_rejected(ws: Workspace, root: Path) -> None:
    assert_code('workspace_not_initialized', ws.list_files)
    assert_code('workspace_not_initialized', lambda: ws.read_text('note.txt'))
    assert_code('workspace_not_initialized', lambda: ws.create_text('note.txt', 'x'))
    assert not root.exists()


def test_root_that_is_a_regular_file_is_rejected(tmp_path: Path) -> None:
    file_root = tmp_path / 'not-a-directory'
    file_root.write_text('x', encoding='utf-8')
    ws = Workspace(file_root)

    assert_code('invalid_root', ws.list_files)
    assert_code('invalid_root', ws.initialize_demo)


def test_relative_root_is_rejected() -> None:
    with pytest.raises(WorkspaceError) as caught:
        Workspace(Path('relative-demo'))

    assert caught.value.code == 'invalid_root'


def test_file_symlink_is_rejected_if_supported(ws: Workspace, root: Path, sentinel: Path) -> None:
    ws.initialize_demo()
    link = root / 'linked.txt'
    try:
        os.symlink(sentinel, link)
    except OSError as exc:
        pytest.skip(f'file symlinks unavailable in this environment: {exc}')

    assert_code('unsafe_path', lambda: ws.read_text('linked.txt'))
    assert 'linked.txt' not in ws.list_files()
    assert sentinel.read_bytes() == b'DO-NOT-TOUCH'


def test_hardlinked_file_is_rejected(ws: Workspace, root: Path, sentinel: Path) -> None:
    ws.initialize_demo()
    link = root / 'hardlink.txt'
    os.link(sentinel, link)
    assert os.stat(link).st_nlink == 2

    assert_code('unsafe_path', lambda: ws.read_text('hardlink.txt'))
    assert 'hardlink.txt' not in ws.list_files()
    assert_code('already_exists', lambda: ws.create_text('hardlink.txt', 'payload'))
    assert sentinel.read_bytes() == b'DO-NOT-TOUCH'


def test_junction_root_is_rejected(tmp_path: Path, sentinel: Path) -> None:
    target = sentinel.parent
    junction = tmp_path / 'junction-root'
    result = subprocess.run(
        ['cmd', '/c', 'mklink', '/J', str(junction), str(target)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f'could not create directory junction: {result.stderr!r}')
    try:
        assert os.path.isjunction(junction)
        ws = Workspace(junction)
        assert_code('invalid_root', ws.list_files)
        assert_code('invalid_root', ws.initialize_demo)
        assert sentinel.read_bytes() == b'DO-NOT-TOUCH'
        assert not (target / WELCOME_NAME).exists()
    finally:
        junction.rmdir()
    assert sentinel.exists()


def test_junction_inside_root_is_rejected(ws: Workspace, root: Path, sentinel: Path) -> None:
    ws.initialize_demo()
    junction = root / 'junction.txt'
    result = subprocess.run(
        ['cmd', '/c', 'mklink', '/J', str(junction), str(sentinel.parent)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f'could not create directory junction: {result.stderr!r}')
    try:
        assert_code('unsafe_path', lambda: ws.read_text('junction.txt'))
        assert 'junction.txt' not in ws.list_files()
        assert sentinel.read_bytes() == b'DO-NOT-TOUCH'
    finally:
        junction.rmdir()
    assert sentinel.exists()


def _make_junction(link: Path, target: Path) -> None:
    result = subprocess.run(
        ['cmd', '/c', 'mklink', '/J', str(link), str(target)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f'could not create directory junction: {result.stderr!r}')


def test_initialize_demo_rejects_junction_parent_without_creating_new_root(
    tmp_path: Path, sentinel: Path
) -> None:
    outside = sentinel.parent
    junction = tmp_path / 'linked-parent'
    _make_junction(junction, outside)
    try:
        ws = Workspace(junction / 'newroot')
        assert_code('invalid_root', ws.initialize_demo)
        assert not (outside / 'newroot').exists()
        assert sentinel.read_bytes() == b'DO-NOT-TOUCH'
    finally:
        junction.rmdir()
    assert sentinel.exists()


def test_every_operation_rejects_junction_parent(tmp_path: Path, sentinel: Path) -> None:
    junction = tmp_path / 'linked-parent'
    _make_junction(junction, sentinel.parent)
    try:
        ws = Workspace(junction / 'sub')
        assert_code('invalid_root', ws.initialize_demo)
        assert_code('invalid_root', ws.list_files)
        assert_code('invalid_root', lambda: ws.read_text('note.txt'))
        assert_code('invalid_root', lambda: ws.create_text('note.txt', 'x'))
        assert not (sentinel.parent / 'sub').exists()
        assert sentinel.read_bytes() == b'DO-NOT-TOUCH'
    finally:
        junction.rmdir()
    assert sentinel.exists()


def test_read_text_rejects_lstat_symlink_before_opening(
    ws: Workspace, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws.initialize_demo()
    target = root / 'pretend-link.txt'
    real_lstat = os.lstat
    open_calls: list[object] = []

    def fake_lstat(path, *args, **kwargs):
        if Path(path) == target:
            return os.stat_result((stat.S_IFLNK | 0o777, 1, 1, 1, 0, 0, 0, 0, 0, 0))
        return real_lstat(path, *args, **kwargs)

    def fake_open(*args, **kwargs):
        open_calls.append(args)
        raise AssertionError('os.open must not be called for a link')

    monkeypatch.setattr(os, 'lstat', fake_lstat)
    monkeypatch.setattr(os, 'open', fake_open)

    assert_code('unsafe_path', lambda: ws.read_text('pretend-link.txt'))
    assert open_calls == []


def test_validate_root_accepts_existing_directory_without_writing(ws: Workspace, root: Path) -> None:
    root.mkdir()
    (root / 'keep.md').write_text('keep', encoding='utf-8')
    before = set(os.listdir(root))

    ws.validate_root()

    assert set(os.listdir(root)) == before
    assert (root / 'keep.md').read_text(encoding='utf-8') == 'keep'


def test_validate_root_rejects_missing_directory_without_creating_it(tmp_path: Path) -> None:
    missing = tmp_path / 'never-created'

    assert_code('invalid_root', Workspace(missing).validate_root)

    assert not missing.exists()


def test_validate_root_rejects_junction_root(tmp_path: Path, sentinel: Path) -> None:
    junction = tmp_path / 'junction-root'
    _make_junction(junction, sentinel.parent)
    try:
        assert_code('invalid_root', Workspace(junction).validate_root)
        assert sentinel.read_bytes() == b'DO-NOT-TOUCH'
    finally:
        junction.rmdir()


@pytest.mark.parametrize('bad', ['\\\\server\\share\\root', '\\\\?\\C:\\temp'])
def test_unc_and_device_roots_are_rejected(bad: str) -> None:
    with pytest.raises(WorkspaceError) as caught:
        Workspace(Path(bad))

    assert caught.value.code == 'invalid_root'


def test_list_directory_returns_dirs_then_editable_files(ws: Workspace, root: Path) -> None:
    ws.initialize_demo()
    (root / 'src').mkdir()
    (root / 'src' / 'main.py').write_text('print(1)\n', encoding='utf-8')
    (root / 'image.png').write_text('x', encoding='utf-8')
    (root / '.hidden').mkdir()

    entries = ws.list_directory()

    assert [(entry['kind'], entry['name']) for entry in entries] == [
        ('dir', 'src'),
        ('file', WELCOME_NAME),
    ]
    assert [entry['path'] for entry in entries] == ['src', WELCOME_NAME]
    assert ws.list_files('src') == ['main.py']
    assert ws.list_directory('src') == [
        {'name': 'main.py', 'path': 'src/main.py', 'kind': 'file', 'size': 10}
    ]


def test_list_directory_skips_links_and_hardlinks(ws: Workspace, root: Path, sentinel: Path) -> None:
    ws.initialize_demo()
    (root / 'sub').mkdir()
    os.link(sentinel, root / 'sub' / 'hard.txt')
    junction = root / 'jump'
    _make_junction(junction, sentinel.parent)
    try:
        assert [entry['name'] for entry in ws.list_directory('sub')] == []
        assert 'jump' not in [entry['name'] for entry in ws.list_directory()]
        assert_code('unsafe_path', lambda: ws.read_text('sub/hard.txt'))
        assert_code('unsafe_path', lambda: ws.read_text('jump/note.txt'))
        assert sentinel.read_bytes() == b'DO-NOT-TOUCH'
    finally:
        junction.rmdir()


def test_list_directory_is_capped(ws: Workspace, root: Path) -> None:
    ws.initialize_demo()
    for index in range(105):
        (root / f'd{index:03}').mkdir()

    assert len(ws.list_directory()) == 100


def test_list_directory_rejects_traversal(ws: Workspace) -> None:
    ws.initialize_demo()

    for bad in ['..', '../outside', 'sub/../../outside', 'C:/Windows', 'sub\\win']:
        assert_code('invalid_name', lambda bad=bad: ws.list_directory(bad))


def test_subdirectory_round_trip_on_disk(ws: Workspace, root: Path) -> None:
    ws.initialize_demo()
    (root / 'src').mkdir()

    ws.create_text('src/app.py', 'x = 1\n')
    content, revision = ws.read_document('src/app.py')

    assert content == 'x = 1\n'
    assert isinstance(revision, str) and len(revision) == 64
    assert (root / 'src' / 'app.py').read_text(encoding='utf-8') == 'x = 1\n'

    new_revision = ws.save_text('src/app.py', 'x = 2\n', revision)

    assert new_revision != revision
    assert (root / 'src' / 'app.py').read_text(encoding='utf-8') == 'x = 2\n'
    assert ws.read_document('src/app.py') == ('x = 2\n', new_revision)


def test_create_into_missing_subdirectory_does_not_create_it(ws: Workspace, root: Path) -> None:
    ws.initialize_demo()

    assert_code('not_found', lambda: ws.create_text('missing/app.py', 'x'))

    assert not (root / 'missing').exists()


def test_save_rejects_external_change_and_keeps_disk_content(ws: Workspace, root: Path) -> None:
    ws.initialize_demo()
    ws.create_text('doc.md', 'v1')
    _, revision = ws.read_document('doc.md')
    (root / 'doc.md').write_text('external', encoding='utf-8')

    assert_code('conflict', lambda: ws.save_text('doc.md', 'mine', revision))

    assert (root / 'doc.md').read_text(encoding='utf-8') == 'external'
    assert [p.name for p in root.iterdir() if p.name.startswith('.') and p.name.endswith('.tmp')] == []


def test_save_after_delete_is_rejected_without_recreating(ws: Workspace, root: Path) -> None:
    ws.initialize_demo()
    ws.create_text('doc.md', 'v1')
    _, revision = ws.read_document('doc.md')
    os.unlink(root / 'doc.md')

    assert_code('not_found', lambda: ws.save_text('doc.md', 'mine', revision))

    assert not (root / 'doc.md').exists()


def test_save_failure_keeps_original_and_cleans_temp(
    ws: Workspace, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws.initialize_demo()
    ws.create_text('doc.md', 'original')
    _, revision = ws.read_document('doc.md')

    def failing_replace(source, destination):
        raise OSError('replace failed')

    monkeypatch.setattr(os, 'replace', failing_replace)

    assert_code('save_failed', lambda: ws.save_text('doc.md', 'new', revision))

    assert (root / 'doc.md').read_text(encoding='utf-8') == 'original'
    assert [p.name for p in root.iterdir() if p.name.startswith('.')] == []


def test_save_rejects_oversized_content_without_touching_file(ws: Workspace, root: Path) -> None:
    ws.initialize_demo()
    ws.create_text('doc.md', 'original')
    _, revision = ws.read_document('doc.md')

    assert_code('content_too_large', lambda: ws.save_text('doc.md', 'a' * (MAX_FILE_BYTES + 1), revision))

    assert (root / 'doc.md').read_text(encoding='utf-8') == 'original'


def test_save_requires_expected_revision(ws: Workspace) -> None:
    ws.initialize_demo()
    ws.create_text('doc.md', 'original')

    assert_code('invalid_revision', lambda: ws.save_text('doc.md', 'new', ''))
    assert_code('invalid_revision', lambda: ws.save_text('doc.md', 'new', None))


def test_read_document_rejects_binary_and_oversized(ws: Workspace, root: Path) -> None:
    ws.initialize_demo()
    (root / 'latin1.txt').write_bytes(b'caf\xe9')
    (root / 'huge.md').write_bytes(b'a' * (MAX_FILE_BYTES + 1))
    (root / 'blob.py').write_bytes(b'print(1)\x00print(2)')

    assert_code('invalid_encoding', lambda: ws.read_document('latin1.txt'))
    assert_code('file_too_large', lambda: ws.read_document('huge.md'))
    assert_code('binary_content', lambda: ws.read_document('blob.py'))


def test_read_document_requires_regular_file(ws: Workspace, root: Path) -> None:
    ws.initialize_demo()
    (root / 'folder.txt').mkdir()

    assert_code('not_a_file', lambda: ws.read_document('folder.txt'))
    assert_code('not_found', lambda: ws.read_document('src/welcome.md'))
