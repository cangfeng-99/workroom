"""Unit tests for the PowerShell folder picker (command is mocked, not shown)."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest import mock

import pytest

from workspaces import picker


def test_pick_folder_returns_selected_path_and_uses_fixed_command() -> None:
    calls: list[list[str]] = []

    def fake_run(args, timeout):
        calls.append(list(args))
        return SimpleNamespace(returncode=0, stdout=b'D:\\work\\notes\n')

    with mock.patch.object(picker, '_run_command', side_effect=fake_run):
        assert picker.pick_folder() == 'D:\\work\\notes'

    args = calls[0]
    assert args[0].lower().endswith('powershell.exe')
    assert '-STA' in args
    assert '-NoProfile' in args
    assert '-NonInteractive' in args
    assert args[args.index('-File') + 1].endswith('.ps1')
    assert 'D:\\work\\notes' not in ' '.join(args[1:-1])


def test_pick_folder_cancel_is_reported_as_cancelled() -> None:
    fake = SimpleNamespace(returncode=3, stdout=b'')
    with mock.patch.object(picker, '_run_command', return_value=fake), pytest.raises(
        picker.PickerError
    ) as caught:
        picker.pick_folder()
    assert caught.value.code == 'picker_cancelled'


def test_pick_folder_timeout_is_reported_and_script_removed() -> None:
    removed: list[str] = []
    real_unlink = picker.os.unlink

    def spy_unlink(path):
        removed.append(path)
        return real_unlink(path)

    with (
        mock.patch.object(
            picker, '_run_command', side_effect=subprocess.TimeoutExpired('powershell', 120)
        ),
        mock.patch.object(picker.os, 'unlink', side_effect=spy_unlink),
        pytest.raises(picker.PickerError) as caught,
    ):
        picker.pick_folder()

    assert caught.value.code == 'picker_timeout'
    assert removed and all(path.endswith('.ps1') for path in removed)


def test_pick_folder_failure_and_empty_output() -> None:
    failure = SimpleNamespace(returncode=1, stdout=b'')
    with mock.patch.object(picker, '_run_command', return_value=failure), pytest.raises(
        picker.PickerError
    ) as failed:
        picker.pick_folder()
    assert failed.value.code == 'picker_failed'

    blank = SimpleNamespace(returncode=0, stdout=b'  \r\n')
    with mock.patch.object(picker, '_run_command', return_value=blank), pytest.raises(
        picker.PickerError
    ) as empty:
        picker.pick_folder()
    assert empty.value.code == 'picker_failed'


def test_missing_powershell_is_reported() -> None:
    unavailable = picker.PickerError('picker_unavailable')
    with (
        mock.patch.object(picker, '_powershell_path', side_effect=unavailable),
        pytest.raises(picker.PickerError) as caught,
    ):
        picker.pick_folder()
    assert caught.value.code == 'picker_unavailable'


def test_script_is_fixed_and_has_no_user_input_placeholders() -> None:
    assert 'FolderBrowserDialog' in picker._SCRIPT
    assert 'ShowDialog' in picker._SCRIPT
    assert '{0}' not in picker._SCRIPT and '%s' not in picker._SCRIPT
