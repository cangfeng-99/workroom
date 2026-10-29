# WorkRoom 个人版

一个人用的本地项目工作台：立项 → 拆任务 → 执行 → 验收 → 沉淀记忆。
不开服务器、不注册账号、数据全在本机。

---

## 一、快速开始

### 方式 A：双击启动（推荐）

```
WorkRoom个人版.cmd
```

双击后浏览器会自动打开 `http://127.0.0.1:8021/`。

### 方式 B：命令行

```bash
# 在仓库根目录
.venv/Scripts/python.exe tools/run_workroom.py --port 8021
```

| 参数 | 说明 |
|---|---|
| `--port 8021` | 监听端口，被占用就换一个 |
| `--no-browser` | 不自动开浏览器 |
| `--host` | 默认只监听 127.0.0.1，不要改成 0.0.0.0 |

### 停止

`Ctrl+C`，或直接关闭那个命令行窗口。

---

## 二、第一次用做什么

1. 打开首页 → **新建项目**（填项目名、目标）
2. 左栏 → **接入 AI**：填厂商、模型名、API Key（Key 加密存本机）
3. 左栏 → **工作区与长期记忆**：填一个绝对路径并授权，生成 `.workroom/MEMORY.md`
4. 对话页发一句需求 → 选「拆任务」→ 生成任务草案 → 应用
5. 任务页用时间线看阶段，点节点改状态

**没有 AI 也能用**：任务、时间线、记忆、备份都不依赖模型。

---

## 三、核心概念

| 概念 | 说明 |
|---|---|
| 项目 | 一个目标 + 一棵任务树 + 一份记忆 |
| 任务树 | 横轴阶段（立项→设计→开发→测试→发布→复盘），每个阶段下挂具体任务 |
| 成员 | 内置 AI、外部 Agent（Codex/Cursor 走 MCP）、真人 |
| 交付 | 外部 Agent 提交的变更+测试证据，验收后任务才置完成 |
| 记忆 | `.workroom/MEMORY.md` + 每日记录，AI 每轮自动读取 |

---

## 四、接入外部 Agent（MCP）

WorkRoom 自带 MCP 服务，Codex / Cursor / Claude Code 可以：

- `list_tasks` / `claim_task` 领任务
- `submit_result` 提交交付（带 changed_files、测试命令、退出码）
- `post_message` 在对话里发言
- `read_memory` / `append_memory` 读写项目记忆

配置入口：左栏 **Codex / Cursor / WorkBuddy** 页，按页面提示把配置粘到对应客户端。

单人模式下，交付只要证据完整（变更文件 + 测试命令 + 退出码 0）就自动验收。

---

## 五、数据放在哪

```
workroom/data/           SQLite 数据库、附件、生成的静态文件
<授权工作区>/.workroom/   MEMORY.md 与每日记录
```

**备份**：访问 `/backups/` 一键导出 zip；恢复也在这个页面。

`data/` 不进版本控制，换机器时单独拷。

---

## 六、开发

```bash
# 安装依赖
.venv/Scripts/python.exe -m pip install -r requirements-dev.in

# 迁移
.venv/Scripts/python.exe manage.py migrate

# 跑测试（务必用临时数据目录，别写进 data/）
WORKROOM_DATA_DIR=$(mktemp -d) .venv/Scripts/python.exe -m pytest tests -q

# 代码检查
.venv/Scripts/python.exe -m ruff check .
```

### 目录结构

```
workroom/
├─ apps/projects/        模型、视图、MCP、讨论、交付、备份
├─ config/               Django 配置
├─ templates/            页面模板
├─ static/workroom/      样式与脚本
├─ tests/                测试（400+ 条）
├─ deploy/               部署与本地预览
├─ tool_schema.py        MCP 工具契约
└─ manage.py
```

### 约定

- 改样式改 `static/workroom/app.css`，主题覆盖放 `theme-*.css`
- 新增 MCP 工具要同时改 `tool_schema.py` 和 `apps/projects/mcp.py`
- 交付类改动必须补测试，`pytest` 全绿再提交

---

## 七、常见问题

**端口被占用**
换端口：`--port 8032`。

**页面打不开 / 一直转圈**
先看命令行窗口有没有报错；再确认没开两个实例（会抢同一个数据目录）。

**AI 回复超时**
模型服务慢或 Key 失效。检查成员设置里的 Key，换模型试。

**改了 CSS 没生效**
浏览器缓存，`Ctrl+F5`。

**任务树看不到历史节点**
旧团队路线的节点默认归档隐藏，`?view=all` 可以看全部。

---

## 八、已知边界

- 只支持单人使用，多人协作（登录/邀请/角色）已暂停
- 内置 AI 只能读写记忆，不能改代码；改代码要靠外部 Agent
- Windows 打包版在 `packaging/`，构建需 PyInstaller
