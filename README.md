# WorkRoom

一个人用的本地项目工作台：立项 → 拆任务 → 执行 → 验收 → 沉淀记忆。

不开服务器、不注册账号、数据全在这台电脑上。

---

## 下载即用（Windows x64）

到 [Releases](../../releases) 下载最新的 `WorkRoom-*-windows-x64.zip`：

1. 解压到任意一个普通文件夹（`WorkRoom.exe` 和 `_internal` 必须在一起）
2. 双击 `WorkRoom.exe`
3. 控制窗口出现，浏览器自动打开工作台

不需要预装 Python、不需要装数据库、不需要管理员权限。

首次运行会在 `%LOCALAPPDATA%\WorkRoom` 建好数据目录，之后换新版本直接解压覆盖程序文件夹即可，个人数据不受影响。

> 这个包没有代码签名，Windows 可能提示「已保护你的电脑」。点「更多信息 → 仍要运行」。校验包是否完整，可以对照 Release 里的 SHA256。

## 数据存在哪

| 内容 | 位置 |
|---|---|
| 项目、任务、交付、聊天记录 | `%LOCALAPPDATA%\WorkRoom\db.sqlite3` |
| 工作区授权与长期记忆 | `%LOCALAPPDATA%\WorkRoom\.workroom` |
| 日志 | `%LOCALAPPDATA%\WorkRoom\logs\desktop.log` |

**关于数据库**：用的是 SQLite，它是嵌入式的，整个数据库就是一个文件，随程序一起走。不用单独安装 MySQL/Postgres，也不用起服务。第一次启动时程序自己建表。

要备份就复制整个 `%LOCALAPPDATA%\WorkRoom` 目录；要在另一台电脑接着用，把目录拷过去即可。应用内的「备份与恢复」页面也能导出和导入 ZIP。

## 从源码运行

需要 Python 3.12+。

```bash
python -m venv .venv
.venv/Scripts/pip install -r workroom/requirements-server.in   # macOS/Linux 用 .venv/bin/pip
python tools/run_workroom.py --port 8021
```

打开 http://127.0.0.1:8021/ 。开发模式使用 `workroom/data` 作为数据目录，和 exe 的 `%LOCALAPPDATA%\WorkRoom` 是分开的两套。

## 构建安装包

```bash
# Windows：产出 dist/WorkRoom-<版本>-windows-x64.zip
python tools/build_windows.py

# macOS：产出 dist/WorkRoom-<版本>-macos.dmg
python tools/build_macos.py
```

PyInstaller 不能交叉编译，Windows 包只能在 Windows 上打，macOS 包只能在 macOS 上打。没有 Mac 时用 `.github/workflows/build-macos.yml`，在 GitHub Actions 的 macOS runner 上构建。

## 它是怎么工作的

- **任务树**：X 轴是项目阶段（立项 → 设计 → 开发 → 测试 → 发布 → 复盘），Y 轴是阶段下的具体任务
- **状态向上聚合**：子任务变了，阶段状态立刻重算，不用手动改
- **交付验收**：执行者提交结果和证据，由你自己核对确认；工具说「做完了」不等于完成
- **外部工具接入**：Codex、Cursor、WorkBuddy 通过 MCP 读取任务、认领、回报和交付，共 24 个工具
- **长期记忆**：项目内的规则、决策和结论会作为上下文带进每次对话

## 目录结构

```
workroom/      Django 工程（应用、模板、静态资源、测试）
tools/         启动器与打包脚本
packaging/     PyInstaller 配置、图标、许可
.github/       跨平台构建流水线
```

## 许可

第三方组件许可见 `packaging/licenses/` 与打包产物内的 `THIRD_PARTY_NOTICES.txt`。
