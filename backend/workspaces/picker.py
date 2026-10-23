"""Windows native folder picker driven by one fixed PowerShell script.

No user input ever reaches the command line: the script text is a constant in
this file and the only arguments are the fixed PowerShell executable and the
switches below. The dialog runs in an STA thread inside a hidden PowerShell
process so the web request does not spawn a console window.

``pick_folder`` raises :class:`PickerError` with a stable code
(``picker_cancelled``, ``picker_timeout``, ``picker_unavailable``,
``picker_failed``). It is not a sandbox: the chosen path is only a string and
must still pass ``Workspace.validate_root`` before it is authorized.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

PICKER_TIMEOUT_SECONDS = 120

# Fixed script: UTF-8 console output, one modal folder dialog, no extra console.
_SCRIPT = """\
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms | Out-Null
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '选择要授权的工作文件夹'
$dialog.ShowNewFolderButton = $false
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::Out.WriteLine($dialog.SelectedPath)
    exit 0
}
exit 3
"""


class PickerError(Exception):
    """Picker failure carrying a stable code for user-facing translation."""

    def __init__(self, code: str, message: str = '') -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _powershell_path() -> str:
    system_root = os.environ.get('SystemRoot', r'C:\Windows')
    candidate = Path(system_root) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    if candidate.is_file():
        return str(candidate)
    found = shutil.which('powershell.exe')
    if found:
        return found
    raise PickerError('picker_unavailable', 'powershell.exe was not found')


def _run_command(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    """Run the fixed command hidden; separated so tests can replace it."""
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    return subprocess.run(
        args,
        capture_output=True,
        timeout=timeout,
        check=False,
        creationflags=creationflags,
    )


def pick_folder() -> str:
    """Open the native folder dialog and return the chosen absolute path."""
    executable = _powershell_path()
    descriptor, script_name = tempfile.mkstemp(suffix='.ps1')
    with os.fdopen(descriptor, 'w', encoding='utf-8-sig', newline='\r\n') as script_file:
        script_file.write(_SCRIPT)
    try:
        args = [
            executable,
            '-NoProfile',
            '-NonInteractive',
            '-STA',
            '-ExecutionPolicy',
            'Bypass',
            '-File',
            script_name,
        ]
        try:
            completed = _run_command(args, PICKER_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise PickerError('picker_timeout', 'folder dialog timed out') from exc
        except OSError as exc:
            raise PickerError('picker_unavailable', 'cannot start folder dialog') from exc
    finally:
        try:
            os.unlink(script_name)
        except OSError:
            pass

    if completed.returncode == 3:
        raise PickerError('picker_cancelled', 'folder dialog was cancelled')
    if completed.returncode != 0:
        raise PickerError('picker_failed', 'folder dialog failed')
    raw = completed.stdout or b''
    if isinstance(raw, str):
        raw = raw.encode('utf-8', 'replace')
    chosen = raw.decode('utf-8', 'replace').strip()
    if not chosen:
        raise PickerError('picker_failed', 'folder dialog returned no path')
    return chosen
