"""T018 read-only asset metadata: any file type, stat only, never content."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from workspaces.services import Workspace, WorkspaceError


@pytest.fixture
def root(tmp_path: Path) -> Path:
    folder = tmp_path / 'assets'
    folder.mkdir()
    return folder


@pytest.fixture
def ws(root: Path) -> Workspace:
    return Workspace(root)


def assert_code(expected: str, action) -> None:
    with pytest.raises(WorkspaceError) as caught:
        action()
    assert caught.value.code == expected


def test_list_assets_reports_any_type_and_metadata(ws: Workspace, root: Path) -> None:
    (root / 'brief.pdf').write_bytes(b'%PDF-1.4 body')
    (root / 'cover.PNG').write_bytes(b'\x89PNG\r\n\x1a\n')
    (root / 'archive.zip').write_bytes(b'PK')
    (root / 'notes.txt').write_text('text', encoding='utf-8')
    (root / 'folder').mkdir()
    (root / 'empty').write_bytes(b'')

    entries = ws.list_assets()

    names = [entry['name'] for entry in entries]
    assert names[0] == 'folder'
    assert names[1:] == ['archive.zip', 'brief.pdf', 'cover.PNG', 'empty', 'notes.txt']
    by_name = {entry['name']: entry for entry in entries}
    assert by_name['folder']['kind'] == 'dir'
    assert by_name['brief.pdf']['kind'] == 'file'
    assert by_name['brief.pdf']['suffix'] == '.pdf'
    assert by_name['brief.pdf']['size'] == len(b'%PDF-1.4 body')
    assert by_name['brief.pdf']['modified'] is not None
    assert by_name['cover.PNG']['suffix'] == '.png'
    assert by_name['empty']['size'] == 0


def test_list_assets_puts_directories_first_and_caps_at_one_hundred(
    ws: Workspace, root: Path
) -> None:
    for index in range(60):
        (root / f'd{index:02}').mkdir()
    for index in range(60):
        (root / f'f{index:02}.bin').write_bytes(b'x')

    entries = ws.list_assets()

    assert len(entries) == 100
    kinds = [entry['kind'] for entry in entries]
    assert kinds[:60] == ['dir'] * 60
    assert kinds[60:] == ['file'] * 40


def test_list_assets_skips_links_hardlinks_hidden_and_bad_names(
    ws: Workspace, root: Path, tmp_path: Path
) -> None:
    sentinel = tmp_path / 'sentinel.pdf'
    sentinel.write_bytes(b'%PDF do not touch')
    (root / 'ok.pdf').write_bytes(b'%PDF ok')
    (root / '.hidden.pdf').write_bytes(b'%PDF hidden')
    os.link(sentinel, root / 'hardlink.pdf')
    try:
        os.symlink(sentinel, root / 'linked.pdf')
    except OSError:
        pass

    names = [entry['name'] for entry in ws.list_assets()]

    assert names == ['ok.pdf']
    assert sentinel.read_bytes() == b'%PDF do not touch'


def test_list_assets_does_not_read_file_content(ws: Workspace, root: Path) -> None:
    (root / 'secret.pdf').write_bytes(b'%PDF secret')
    (root / 'big.bin').write_bytes(b'x' * (70 * 1024))

    with mock.patch.object(Workspace, '_read_file', side_effect=AssertionError('read')):
        entries = ws.list_assets()

    assert {entry['name'] for entry in entries} == {'secret.pdf', 'big.bin'}


def test_list_assets_does_not_relax_editable_limits(ws: Workspace, root: Path) -> None:
    (root / 'brief.pdf').write_bytes(b'%PDF')
    (root / 'large.txt').write_text('x' * (70 * 1024), encoding='utf-8')

    asset_names = {entry['name'] for entry in ws.list_assets()}
    editable_names = ws.list_files()

    assert {'brief.pdf', 'large.txt'} <= asset_names
    assert editable_names == []
    assert_code('unsupported_type', lambda: ws.read_text('brief.pdf'))
    assert_code('file_too_large', lambda: ws.read_text('large.txt'))


def test_list_assets_rejects_traversal_and_links(root: Path, tmp_path: Path) -> None:
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.pdf').write_bytes(b'%PDF outside')
    ws = Workspace(root)

    for bad in ('..', '../outside', 'sub/../../outside'):
        assert_code('invalid_name', lambda bad=bad: ws.list_assets(bad))

    junction = root / 'junction'
    result = subprocess.run(
        ['cmd', '/c', 'mklink', '/J', str(junction), str(outside)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f'could not create directory junction: {result.stderr!r}')
    try:
        assert os.path.isjunction(junction)
        names = [entry['name'] for entry in ws.list_assets()]
        assert 'junction' not in names
        assert_code('unsafe_path', lambda: ws.list_assets('junction'))
        assert (outside / 'secret.pdf').read_bytes() == b'%PDF outside'
    finally:
        junction.rmdir()
