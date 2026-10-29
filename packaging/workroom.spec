# Build with the independent environment via tools/build_windows.py or tools/build_macos.py.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
APP = ROOT / 'workroom'
ICON_DIR = APP / 'static' / 'workroom'
IS_MAC = sys.platform == 'darwin'

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

# Pillow 只用来生成图标，运行时不 import，别打进包里（约 6–8 MB）
excludes = ['pytest', 'playwright', 'MySQLdb', 'pip_audit', 'PIL', 'numpy']

a = Analysis(
    [str(ROOT / 'tools/desktop_entry.py')], pathex=[str(APP)],
    binaries=[], datas=datas, hiddenimports=hidden,
    hookspath=[str(ROOT / 'packaging/hooks')], runtime_hooks=[], excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

# macOS 的 .app 若保留控制台会带一个终端窗口，双击体验很差；日志照旧写 desktop.log
exe_options = dict(
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    icon=str(ICON_DIR / ('app.icns' if IS_MAC else 'app.ico')),
)
if IS_MAC:
    exe = EXE(
        pyz, a.scripts, [], exclude_binaries=True, name='WorkRoom',
        console=False, **exe_options,
    )
else:
    exe = EXE(
        pyz, a.scripts, [], exclude_binaries=True, name='WorkRoom',
        console=True, hide_console='hide-early',
        version=str(ROOT / 'packaging/version_info.txt'),
        **exe_options,
    )

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               name='WorkRoom-' + (APP / 'VERSION').read_text().strip())

if IS_MAC:
    app = BUNDLE(
        coll,
        name='WorkRoom.app',
        icon=str(ICON_DIR / 'app.icns'),
        bundle_identifier='com.workroom.desktop',
        info_plist={
            'CFBundleName': 'WorkRoom',
            'CFBundleDisplayName': 'WorkRoom',
            'CFBundleShortVersionString': (APP / 'VERSION').read_text().strip(),
            'NSHighResolutionCapable': True,
        },
    )
