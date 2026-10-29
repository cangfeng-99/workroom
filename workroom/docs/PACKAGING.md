# 打包成 Windows 安装包（计划，未实测）

2026-10-25：项目当前优先交付服务器多人版，部署见 [SERVER.md](SERVER.md)。本文保留原本机安装包路线；它不承担服务器常驻服务或多用户隔离。

目标：一个 `WorkRoom.exe`，双击起界面，同时能被 Codex / Cursor / WorkBuddy 以 `--mcp` 拉起。

## 已经为打包做的改动

| 项 | 开发时 | 打包后 |
|---|---|---|
| 模板/静态 | `workroom/templates`、`static` | `sys._MEIPASS` 下的同名目录 |
| 数据库 | `workroom/db.sqlite3` | `%LOCALAPPDATA%\WorkRoom\db.sqlite3` |
| SECRET_KEY | `workroom/.secret_key` | `%LOCALAPPDATA%\WorkRoom\.secret_key` |
| 启动 | `manage.py runserver` | `launcher.py`（有 waitress 用它，没有退回 runserver） |
| MCP 命令 | `python mcp_server.py` | `WorkRoom.exe --mcp`（`mcp_clients.mcp_command()` 已按 frozen 分支） |

`launcher.py` 已支持 `--mcp`，打包后一键接入写进客户端的命令会自动变成 exe 自身。

## 打包步骤（PyInstaller）

```bash
pip install pyinstaller waitress
pyinstaller --noconfirm --clean --windowed --name WorkRoom ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --collect-submodules django ^
  --hidden-import config.settings ^
  launcher.py
```

产物在 `dist/WorkRoom/WorkRoom.exe`。安装包再用 Inno Setup 或 NSIS 包一层即可。

## 打包后必须验证

1. 双击能起界面，数据写在 `%LOCALAPPDATA%\WorkRoom\`，卸载不丢。
2. 静态文件能加载（`DEBUG=False` 时需要 waitress + 静态目录；当前 `DEBUG` 由环境变量控制，打包时应设 `WORKROOM_DEBUG=0`）。
3. 一键接入写出的命令是 `WorkRoom.exe --mcp`，重启 Codex/Cursor 后能列出 `workroom` 工具。
4. 首次运行自动 `migrate`（launcher 已调用）。

## 已知风险

- PyInstaller 对 Django 的 hidden import 较多，首次打包可能需要补 `--hidden-import`。
- `DEBUG=0` 时 Django 不再自动服务静态文件，必须用 waitress/WhiteNoise；这份文档用的是 waitress 方案，尚未实测。
- 单文件模式（`--onefile`）启动慢、杀软误报多，优先用目录模式 + 安装包。
