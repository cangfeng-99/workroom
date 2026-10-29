# Build with the independent environment via tools/build_windows.py.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
APP = ROOT / 'workroom'
datas = [
    (str(APP / 'templates'), 'templates'),
    (str(APP / 'static'), 'static'),
    (str(APP / 'VERSION'), '.'),
    (str(APP / 'connection_setup.py'), '.'),
    (str(APP / 'remote_bridge.py'), '.'),
]
datas += collect_data_files('tzdata')
for distribution in ['Django', 'asgiref', 'sqlparse', 'whitenoise', 'waitress', 'cryptography', 'cffi', 'pycparser', 'tzdata']:
    datas += copy_metadata(distribution)
hidden = collect_submodules('apps.projects')
hidden += collect_submodules('whitenoise')
for package in ['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions']:
    hidden += collect_submodules(package)
hidden += ['config.settings', 'config.urls', 'config.wsgi', 'mcp_server', 'tool_schema', 'connection_setup', 'remote_bridge', 'django.db.backends.sqlite3', 'tzdata']
a = Analysis(
    [str(ROOT / 'tools/desktop_entry.py')], pathex=[str(APP)],
    binaries=[], datas=datas, hiddenimports=hidden,
    hookspath=[str(ROOT / 'packaging/hooks')], runtime_hooks=[], excludes=['pytest', 'playwright', 'MySQLdb', 'pip_audit'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='WorkRoom',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=True, hide_console='hide-early',
    icon=str(APP / 'static/workroom/app.ico'),
    version=str(ROOT / 'packaging/version_info.txt'),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='WorkRoom-' + (APP / 'VERSION').read_text().strip())
