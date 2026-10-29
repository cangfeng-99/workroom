# 小服务器上的多人 WorkRoom

本版面向用户现有的 Linux 2 核 / 2GB / 40GB / 2M 带宽服务器。共享账号、项目、任务、规则、对话、交付都保存在服务器；成员电脑上的编程工具通过 HTTPS + 项目令牌接入。浏览器关闭不会删除排队任务。成员电脑关机后，其本地编程工具不会继续执行；服务器上的 AI 讨论/审核 Worker 可独立运行。

默认一个 Web 进程、两个请求线程、一个串行任务 Worker，SQLite 同机持久卷，不启动 Redis、向量数据库或本地模型。适合小团队起步；这不是高并发容量承诺。出现持续 SQLite 锁等待、排队增长或资源不足时，应先测量再迁移数据库/增加 Worker，不要直接把 SQLite 放到网络共享盘或多机使用。

## 运行模式

- `local`：保留原本的本机工作台，匿名访问/DPAPI 仅用于本机。**不能对公网开放。**
- `server`：真实账号、项目 owner/editor/viewer、邀请、权限隔离、数据库队列与项目令牌。缺少生产密钥或 HTTPS 配置会拒绝启动。
- 当前 Windows 的 8000 本机入口不会因为生成部署文件而自动变成公网服务器。

## Linux + Docker Compose

先准备域名解析和服务器 80/443 入站，确认没有与现有服务冲突。以下操作需在你自己的服务器执行，本轮未远程执行。

1. 把 `workroom/` 源码放到服务器独立目录，例如 `/opt/workroom`。不上传 `.venv/`、`.secret_key`、本机 `.env`、缓存或任意个人文件。
2. 进入该目录生成专用配置，密钥只保存在 `.env`，不显示在终端：

   ```sh
   python3 deploy/init_env.py workroom.your-domain.com
   ```

   没有 Python、但已有 Docker 时也可使用：

   ```sh
   docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/app" -w /app python:3.12-slim python deploy/init_env.py workroom.your-domain.com
   ```

3. 检查 `.env` 中域名、HTTPS 来源、ALLOWED_HOSTS。保留 `127.0.0.1,localhost` 供容器健康检查。把 `.env` 另外备份到安全位置。
4. 启动带 HTTPS 代理的版本：

   ```sh
   docker compose --profile tls up -d --build
   docker compose ps
   docker compose logs --tail=60 web worker
   docker compose exec web python manage.py createsuperuser
   ```

   第一次下载基础镜像、安装依赖的速度取决于小服务器带宽。Compose 会先迁移与收集静态文件，再启动 Web/Worker；Caddy 等 Web 健康后提供 HTTPS。域名无法申请证书时，应先修复域名/端口/现有代理，不关闭证书校验。

5. 用新账号登录域名，创建项目。超级用户也不会自动读取其它人的项目，项目权限仍以成员关系为准。

已有 Nginx/Caddy 时，可不启用 `tls` profile，只运行 `docker compose up -d --build`，由现有代理转发 `127.0.0.1:8080`。按实际代理地址配置 `WORKROOM_TRUSTED_PROXY_IPS`。不要把 Web 的 8080 改成公开端口并信任任意转发头。

## 无 Docker 的方式

使用 Python 3.12 虚拟环境，安装 `requirements-server.lock`；创建专用低权限 `workroom` 用户，程序放 `/opt/workroom`，可写数据放 `/var/lib/workroom`。配置 `/etc/workroom.env`（权限600），其中把 `WORKROOM_DATA_DIR` 改为 `/var/lib/workroom`，可信代理设为实际 loopback/代理IP。

```sh
.venv/bin/pip install -r requirements-server.lock
# 通过受保护的进程环境加载 /etc/workroom.env 后执行：
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser
```

把 `deploy/workroom-web.service`、`deploy/workroom-worker.service` 安装为 systemd 服务，确认用户、工作目录和环境文件正确，再 `systemctl enable --now workroom-web workroom-worker`。Web 使用 Gunicorn，Worker 使用 `manage.py workroom_worker`；HTTPS 交给现有可信反向代理。systemd 服务启动的环境文件格式不能写 `export`。

## 团队协作与工具接入

当前推荐从项目「工具连接」添加本人实例并复制HTTP MCP配置，无需本机Python桥；Claude Code直接复制页面生成的连接命令。详见[CONNECTIONS.md](CONNECTIONS.md)。任务包与审查流程见[COLLABORATION.md](COLLABORATION.md)，Mac/鸿蒙使用见[CROSS_PLATFORM.md](CROSS_PLATFORM.md)。下方stdio配置保留兼容用途。

1. 所有者进入项目的「团队与接入」，生成只读/编辑者邀请。邀请一次使用、到期失效、可撤销。关闭公开注册时，有效邀请仍可用于注册；已有账号可登录后确认加入。链接不要贴到公开群。
2. owner 管理成员、模型 Key、工具令牌和验收。editor 参与任务/对话/资料；viewer 仅读。项目权限不会自动授予任何成员电脑或云主机文件权限。
3. 在团队页添加 Codex/WorkBuddy/Cursor 等外部执行成员，再生成绑定它的执行令牌。只读令牌可不绑定执行成员。数据库只存令牌哈希，原值只显示一次；可撤销，最近成功调用时间会记录。
4. 如需使用旧stdio桥，成员电脑保留 `mcp_server.py`、`remote_bridge.py`、`tool_schema.py` 和 Python。客户端 MCP 配置使用该电脑上的解释器和脚本路径；不要使用云服务器上的绝对路径：

   ```json
   {
     "mcpServers": {
       "workroom": {
         "command": "你电脑上的python路径",
         "args": ["你电脑上的mcp_server.py路径"],
         "env": {
           "WORKROOM_SERVER_URL": "https://workroom.your-domain.com",
           "WORKROOM_ACCESS_TOKEN": "在本机填入项目令牌"
         }
       }
     }
   }
   ```

   Codex 使用同名 `[mcp_servers.workroom]` TOML 段和 `[mcp_servers.workroom.env]` 环境段。配置文件包含凭据，应保存在客户端本机受保护配置中；不要提交版本库。重载客户端连接后先调用 `whoami`、`get_project` 验证真实调用；配置存在不代表在线。

5. 工具工作顺序：`get_inbox/next_task` → `get_task_context` → `claim_task` → 定期 `heartbeat_task` → `submit_result`。读取规则后若版本变化，用 `confirm_task_context` 明确确认当前版本。交付提供变更文件、基准/commit、测试命令/退出码/输出、证据引用与幂等键。
6. 交付进入待验收，AI 按证据给建议，项目所有者到任务的「交付与验收记录」通过/退回。执行者自报的测试不会被服务器执行，也不自动等于独立验证；负责人需核对证据。

## 本机体验多人版

在当前 Windows 项目根目录双击 `Preview-Server.cmd`，打开 http://127.0.0.1:8011/register/ 。已运行时直接访问；使用 Ctrl+C 关闭预览及其 Worker。

预览使用 `workroom/data/local-preview/` 独立持久数据及私有密钥；不预置账号，不自动导入或分配旧项目。先注册自己的账号，再新建项目。在「项目设置」修改目标，在「成员 / 邀请 / 工具令牌」添加真人或外部 AI 工具。失败的模型任务在对话页可手动重试；重试会重新调用供应商。

`deploy/local_preview.py` 强制只绑定 `127.0.0.1`，为本机 HTTP 体验单独关闭 HTTPS 跳转和 secure cookie，采用独立 cookie 名。它不是公开部署入口；生产 `server_wsgi.py`、Compose 和 systemd 仍要求严格 server 配置及 HTTPS。局域网/云端使用上面的正式部署方式。

## 历史数据与模型 Key

旧项目没有账号归属，不能让第一个注册者自动领走。先迁移，再显式指定项目负责人：

```sh
python manage.py assign_project_owner 36 your-account --confirm
```

该命令保留任务/成员/消息，记录归属变更。批量迁移前先备份，再逐项目核对归属。

Windows DPAPI Key 绑定旧 Windows 账号，Linux 无法直接解密。旧密文保留；在服务器项目中由所有者重新填写模型 Key，使用独立 `WORKROOM_ENCRYPTION_KEY` 加密。不要把新加密密钥丢掉、换成临时随机值或与 Django SECRET_KEY 混用。

## 备份、升级和恢复

```sh
docker compose exec web python manage.py workroom_backup before-upgrade.sqlite3
```

命令使用 SQLite 在线备份 API，包含 WAL 中已提交内容，拒绝覆盖已有备份。备份位于持久数据目录 `backups/`；应定期复制到另一处安全存储，同时单独保管 `.env`。仅备份数据库而丢失加密密钥，模型 Key 将无法恢复。

升级前备份、记录源码版本与依赖锁，保留旧版本文件。恢复时先停 Web 和 Worker，等 Worker 旧心跳过期（默认120秒），再以同一数据卷运行离线恢复：

```sh
docker compose stop web worker
docker compose run --rm --no-deps web python manage.py workroom_restore before-upgrade.sqlite3 --offline-confirm
docker compose up -d web worker
```

恢复前会再次备份当前库，只允许恢复应用 backups/ 内的合法数据库。恢复使用匹配的代码版本及原 `.env`，不要把新数据库强行交给旧代码。

## 运行边界与验证

- `/healthz` 公开只返回最小存活状态；项目详情、队列轮询和工具接口有会话/令牌权限。
- 排队任务持久化；Worker 消失后，租约过期的运行会标记失败，手动重试。供应商已经处理的部分可能计费，本系统不声称能接续其内部流或免费重跑。
- 页面隐藏时暂停轮询，服务器模式降低流式轮询频率；项目变更提示不会强制刷新正在填写的表单。静态文件压缩缓存，日志按大小轮转；本版不添加大文件上传。
- 默认部署资源上限用于控制占用，不是容量测试结果。关注服务器内存、磁盘、排队时长和 SQLite 锁等待。
- 本机 Windows 已运行 Python/权限/接口/浏览器验证；当前机器无 Docker，本轮不声称 Docker 镜像、Linux systemd 或真实云服务器已运行通过。上线前仍需在目标机验证镜像构建、HTTPS、重启、备份恢复和真实供应商连接。
- `check --deploy` 保留 W005/W021 两个警告：尚未决定整个域名及所有子域是否一律 HTTPS，也未申请浏览器 HSTS preload。不关闭这些检查；确认域名管理范围后再决定，不能为消除提示而直接启用。

参考：[Django部署检查](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)、[SQLite并发边界](https://docs.djangoproject.com/en/5.2/ref/databases/#sqlite-notes)、[Compose启动顺序](https://docs.docker.com/compose/how-tos/startup-order/)、[WhiteNoise静态文件哈希与压缩](https://whitenoise.readthedocs.io/en/stable/django.html)。
