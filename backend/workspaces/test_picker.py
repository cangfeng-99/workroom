"""Tests for the in-page folder browser metadata service.

Only directory names and paths are read; file contents are never opened and
nothing is written. Every accepted path must also pass ``Workspace.validate_root``
so a picked folder is safe to authorize afterwards.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from workspaces import picker
from workspaces.picker import PickerError


def _names(data: dict) -> list[str]:
    return [item['name'] for item in data['directories']]


def _snapshot(root: Path) -> set[str]:
    return {str(item.relative_to(root)) for item in root.rglob('*')}


def _assert_code(code: str, func) -> None:
    with pytest.raises(PickerError) as caught:
        func()
    assert caught.value.code == code


def _make_junction(link: Path, target: Path) -> None:
    result = subprocess.run(
        ['cmd', '/c', 'mklink', '/J', str(link), str(target)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f'could not create directory junction: {result.stderr!r}')


def test_empty_path_starts_at_drives_without_directories() -> None:
    data = picker.browse('')

    assert data['path'] == ''
    assert data['parent'] == ''
    assert data['directories'] == []
    assert data['truncated'] is False
    assert data['drives']
    for drive in data['drives']:
        assert set(drive) == {'name', 'path'}
        assert drive['path'].endswith(('\\', '/'))
    if os.name == 'nt':
        assert any(drive['path'].upper().startswith('C:') for drive in data['drives'])


def test_browse_returns_folder_metadata_without_touching_files(tmp_path: Path) -> None:
    root = tmp_path / '工作区 & 1'
    root.mkdir()
    (root / 'sub-b').mkdir()
    (root / 'Sub-a').mkdir()
    (root / '空目录').mkdir()
    (root / 'note.txt').write_text('DO-NOT-READ', encoding='utf-8')
    (root / '.hidden-dir').mkdir()
    before = _snapshot(root)

    data = picker.browse(str(root))

    assert data['path'] == str(root)
    assert data['parent'] == str(tmp_path)
    assert data['truncated'] is False
    assert _names(data) == ['Sub-a', 'sub-b', '空目录']
    for item in data['directories']:
        assert set(item) == {'name', 'path'}
        assert Path(item['path']).is_absolute()
        assert Path(item['path']).parent == root
    assert data['drives']
    assert _snapshot(root) == before
    assert (root / 'note.txt').read_text(encoding='utf-8') == 'DO-NOT-READ'


def test_browse_never_opens_file_contents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / 'folder').mkdir()
    (tmp_path / 'private.txt').write_text('not needed for folder selection', encoding='utf-8')

    def unexpected_open(*args, **kwargs):
        raise AssertionError('Folder browsing must only inspect directory metadata')

    with monkeypatch.context() as guard:
        guard.setattr('builtins.open', unexpected_open)
        guard.setattr(os, 'open', unexpected_open)
        guard.setattr(Path, 'open', unexpected_open)
        data = picker.browse(str(tmp_path))

    assert _names(data) == ['folder']


def test_root_of_drive_has_no_parent_and_lists_child_directories() -> None:
    data = picker.browse(os.environ.get('SystemDrive', 'C:') + '\\')

    assert data['path'].endswith(('\\', '/'))
    assert data['parent'] == ''
    assert isinstance(data['directories'], list)


def test_lists_at_most_100_directories_and_flags_truncation(tmp_path: Path) -> None:
    root = tmp_path / 'many'
    root.mkdir()
    for index in range(105):
        (root / f'dir-{index:03d}').mkdir()

    data = picker.browse(str(root))

    assert len(data['directories']) == 100
    assert data['truncated'] is True
    assert _names(data)[0] == 'dir-000'
    assert _names(data)[-1] == 'dir-099'


def test_junction_child_and_junction_root_are_hidden_or_rejected(tmp_path: Path) -> None:
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'sentinel.txt').write_text('DO-NOT-TOUCH', encoding='utf-8')
    root = tmp_path / 'root'
    root.mkdir()
    _make_junction(root / 'junction', outside)
    try:
        data = picker.browse(str(root))
        assert 'junction' not in _names(data)

        _assert_code('unsafe_path', lambda: picker.browse(str(root / 'junction')))
    finally:
        (root / 'junction').rmdir()


@pytest.mark.skipif(os.name != 'nt', reason='hidden attribute is Windows-specific')
def test_hidden_directory_is_not_listed(tmp_path: Path) -> None:
    import ctypes

    root = tmp_path / 'hidden-root'
    root.mkdir()
    hidden = root / 'secret'
    hidden.mkdir()
    kernel32 = ctypes.windll.kernel32
    assert kernel32.SetFileAttributesW(str(hidden), 0x2) != 0
    try:
        assert 'secret' not in _names(picker.browse(str(root)))
    finally:
        kernel32.SetFileAttributesW(str(hidden), 0x80)


def test_rejects_relative_unc_device_dotdot_and_control_paths(tmp_path: Path) -> None:
    for bad in (
        'relative-folder',
        '\\\\server\\share',
        '//server/share',
        '\\\\?\\C:\\Windows',
        '\\\\.\\C:\\Windows',
        str(tmp_path / '..'),
        str(tmp_path) + '\\bad\x00name',
        str(tmp_path) + '\x01',
        '   ',
    ):
        _assert_code('invalid_path', lambda bad=bad: picker.browse(bad))


def test_missing_file_and_drive_relative_inputs_report_stable_errors(tmp_path: Path) -> None:
    _assert_code('not_found', lambda: picker.browse(str(tmp_path / 'missing')))

    target = tmp_path / 'file.txt'
    target.write_text('x', encoding='utf-8')
    _assert_code('not_a_directory', lambda: picker.browse(str(target)))

    _assert_code('invalid_path', lambda: picker.browse('C:relative'))


def test_module_no_longer_uses_powershell_or_subprocess() -> None:
    assert not hasattr(picker, 'pick_folder')
    assert not hasattr(picker, 'PICKER_TIMEOUT_SECONDS')
    assert not hasattr(picker, '_SCRIPT')
    source = Path(picker.__file__).read_text(encoding='utf-8')
    assert 'subprocess' not in source
    assert 'powershell' not in source.lower()
    assert 'ShowDialog' not in source
