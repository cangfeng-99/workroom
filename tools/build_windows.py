"""Build a private-data-free Windows directory ZIP using the isolated build env."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _git(*args):
    """Return a short piece of git state, or "" outside a work tree."""
    try:
        done = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def main():
    if sys.platform != "win32":
        raise SystemExit("Windows 包必须在 Windows x64 Python 上构建。")
    import PyInstaller

    version = (ROOT / "workroom/VERSION").read_text().strip()
    stage = ROOT / ".tools/windows-build"
    stage.mkdir(exist_ok=True)
    # --noconfirm can recursively replace outputs, so check their boundaries.
    for target in [
        ROOT / "dist",
        ROOT / "dist" / ("WorkRoom-" + version),
        stage,
        stage / "analysis",
    ]:
        if not target.resolve().is_relative_to(ROOT.resolve()):
            raise SystemExit("构建目录越出项目范围，未清理或构建。")
        if target.exists() and (
            target.is_symlink() or target.stat().st_file_attributes & 0x400
        ):
            raise SystemExit("构建目录不能是链接，未清理或构建。")
    build_data = stage / "sandbox-data"
    env = {k: v for k, v in os.environ.items() if not k.startswith("WORKROOM_")}
    env.update(
        DJANGO_SETTINGS_MODULE="config.settings",
        WORKROOM_MODE="local",
        WORKROOM_DATA_DIR=str(build_data),
        WORKROOM_DB_PATH=str(build_data / "db.sqlite3"),
        PYTHONPATH=str(ROOT / "workroom"),
        PYTHONIOENCODING="utf-8",
    )
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--workpath",
        str(stage / "analysis"),
        "--distpath",
        str(ROOT / "dist"),
        str(ROOT / "packaging/workroom.spec"),
    ]
    if "--package-only" not in sys.argv[1:]:
        result = subprocess.run(command, cwd=ROOT, env=env, check=False)
        if result.returncode:
            return result.returncode
    package = ROOT / "dist" / ("WorkRoom-" + version)
    if not (package / "WorkRoom.exe").is_file():
        raise SystemExit("找不到已构建的 WorkRoom.exe。")
    shutil.copyfile(ROOT / "packaging/README-用户说明.txt", package / "使用说明.txt")
    sys.path.insert(0, str(ROOT / "workroom"))
    from guide_content import render_markdown

    (package / "使用指南.md").write_text(render_markdown(), encoding="utf-8")
    versions = {
        n: importlib.metadata.version(n)
        for n in [
            "Django",
            "waitress",
            "whitenoise",
            "cryptography",
            "tzdata",
            "pyinstaller",
        ]
    }
    manifest = {
        "product": "WorkRoom",
        "version": version,
        "platform": "windows-x64",
        "built_at": datetime.now(UTC).isoformat(),
        "pyinstaller": PyInstaller.__version__,
        "python": sys.version,
        "dependencies": versions,
        "signed": False,
        "commit": _git("rev-parse", "--short", "HEAD"),
        "dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
    }
    (package / "build-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    notices = [
        "WorkRoom bundles the following third-party runtime components.",
        "Installed licenses are included under _internal/*dist-info/.",
        "PyInstaller bootloader: GPL-2.0-or-later with the bootloader exception; https://pyinstaller.org/en/stable/license.html.",
        "Python: PSF License; Tcl/Tk: included license.terms files.",
        "",
    ]
    for name in [
        "Django",
        "asgiref",
        "sqlparse",
        "whitenoise",
        "waitress",
        "cryptography",
        "cffi",
        "pycparser",
        "tzdata",
    ]:
        metadata = importlib.metadata.metadata(name)
        license_text = (
            metadata.get("License-Expression")
            or metadata.get("License")
            or "See distribution license files"
        )
        notices.append(f"{name} {importlib.metadata.version(name)}: {license_text}")
    (package / "THIRD_PARTY_NOTICES.txt").write_text(
        "\n".join(notices), encoding="utf-8"
    )
    licenses = package / "licenses"
    licenses.mkdir(exist_ok=True)
    for source, name in [
        (Path(sys.base_prefix) / "LICENSE.txt", "Python-LICENSE.txt"),
        (Path(sys.base_prefix) / "tcl/tcl8.6/license.terms", "Tcl-license.terms"),
        (Path(sys.base_prefix) / "tcl/tk8.6/license.terms", "Tk-license.terms"),
        (ROOT / "packaging/licenses/Tcl-license.terms", "Tcl-license.terms"),
        (ROOT / "packaging/licenses/SOURCES.json", "SOURCES.json"),
    ]:
        if source.is_file():
            shutil.copyfile(source, licenses / name)
    distribution = importlib.metadata.distribution("pyinstaller")
    for record in distribution.files or []:
        if record.name == "COPYING.txt" and "licenses" in record.parts:
            shutil.copyfile(
                distribution.locate_file(record), licenses / "PyInstaller-COPYING.txt"
            )
    # Only explicit bundle output is archived, never the repository or DATA_DIR.
    forbidden = {
        ".env",
        ".secret_key",
        "config.local.json",
        "db.sqlite3",
        "desktop-instance.json",
    }
    files = sorted(p for p in package.rglob("*") if p.is_file())
    for path in files:
        if (
            path.name in forbidden
            or path.suffix in {".sqlite3", ".db"}
            or any(
                x in path.parts
                for x in [".codex", ".workbuddy", "node_modules", ".venv"]
            )
        ):
            raise SystemExit(
                "拒绝打包疑似个人数据文件：" + str(path.relative_to(package))
            )
    output = ROOT / "dist" / f"WorkRoom-{version}-windows-x64.zip"
    temporary = output.with_name(output.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "x", zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, Path(package.name) / path.relative_to(package))
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(
        digest + "  " + output.name + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "zip": str(output),
                "sha256": digest,
                "bytes": output.stat().st_size,
                "files": len(files),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
