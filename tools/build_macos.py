"""Build a macOS .app and .dmg on a Mac.

PyInstaller cannot cross-compile: a Mac bundle has to be produced on macOS.
Run this from the repository root on the target machine:

    python3 -m venv .venv && .venv/bin/pip install -r workroom/requirements-server.in pyinstaller
    .venv/bin/python tools/build_macos.py

The GitHub workflow in .github/workflows/build-macos.yml does the same thing on
a hosted runner, which is the practical route when no Mac is available.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform != "darwin":
        raise SystemExit(
            "macOS 包必须在 macOS 上构建：PyInstaller 不支持交叉编译。\n"
            "没有 Mac 时用 .github/workflows/build-macos.yml（GitHub Actions 的 macos runner）。"
        )

    import PyInstaller

    version = (ROOT / "workroom/VERSION").read_text().strip()
    stage = ROOT / ".tools/macos-build"
    stage.mkdir(parents=True, exist_ok=True)

    build_data = stage / "sandbox-data"
    env = {k: v for k, v in environ_items() if not k.startswith("WORKROOM_")}
    env.update(
        DJANGO_SETTINGS_MODULE="config.settings",
        WORKROOM_MODE="local",
        WORKROOM_DATA_DIR=str(build_data),
        WORKROOM_DB_PATH=str(build_data / "db.sqlite3"),
        PYTHONPATH=str(ROOT / "workroom"),
        PYTHONIOENCODING="utf-8",
    )

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--workpath", str(stage / "analysis"),
        "--distpath", str(ROOT / "dist"),
        str(ROOT / "packaging/workroom.spec"),
    ]
    if "--package-only" not in sys.argv[1:]:
        result = subprocess.run(command, cwd=ROOT, env=env, check=False)
        if result.returncode:
            return result.returncode

    app = ROOT / "dist" / ("WorkRoom-" + version) / "WorkRoom.app"
    if not app.is_dir():
        raise SystemExit("找不到已构建的 WorkRoom.app。")

    shutil.copyfile(ROOT / "packaging/README-用户说明.txt", app.parent / "使用说明.txt")
    sys.path.insert(0, str(ROOT / "workroom"))
    from guide_content import render_markdown

    (app.parent / "使用指南.md").write_text(render_markdown(), encoding="utf-8")

    manifest = {
        "product": "WorkRoom",
        "version": version,
        "platform": "macos",
        "built_at": datetime.now(UTC).isoformat(),
        "pyinstaller": PyInstaller.__version__,
        "python": sys.version,
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ["Django", "waitress", "whitenoise", "cryptography", "tzdata"]
        },
        "signed": False,
        "notarized": False,
    }
    (app.parent / "build-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    dmg = ROOT / "dist" / (f"WorkRoom-{version}-macos.dmg")
    if dmg.exists():
        dmg.unlink()
    staged = stage / "dmg"
    if staged.exists():
        shutil.rmtree(staged)
    staged.mkdir(parents=True)
    shutil.copytree(app, staged / "WorkRoom.app", symlinks=True)
    for extra in ("使用说明.txt", "使用指南.md"):
        shutil.copyfile(app.parent / extra, staged / extra)

    built = subprocess.run(
        ["hdiutil", "create", "-volname", "WorkRoom", "-srcfolder", str(staged),
         "-ov", "-format", "UDZO", str(dmg)],
        capture_output=True, text=True,
    )
    if built.returncode:
        raise SystemExit("hdiutil 生成 dmg 失败：" + built.stderr.strip())

    digest = hashlib.sha256(dmg.read_bytes()).hexdigest()
    (dmg.parent / (dmg.name + ".sha256")).write_text(
        f"{digest}  {dmg.name}\n", encoding="utf-8"
    )

    # 附加一份 zip，方便不走 dmg 的场景
    archive = ROOT / "dist" / (f"WorkRoom-{version}-macos.zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(staged.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(staged))

    print(json.dumps(
        {"dmg": str(dmg), "sha256": digest, "zip": str(archive),
         "bytes": dmg.stat().st_size},
        ensure_ascii=False,
    ))
    return 0


def environ_items():
    import os

    return os.environ.items()


if __name__ == "__main__":
    raise SystemExit(main())
