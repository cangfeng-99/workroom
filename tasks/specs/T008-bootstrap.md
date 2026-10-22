# T008 Django 开发骨架

状态：APPROVED，来源为用户直接要求现在开 Django 项目。基线 PLAN-r2 / RULES-r4。

目标：已有环境中创建可运行 Django 后端，明天投简历后无需重建工程即可开始首个功能。

- 工作根不变。backend/manage.py，backend/config 配置，backend/core 基础应用；Django 使用现有5.2.x，不新增依赖。
- 首页仅展示真实的服务已启动状态和健康接口链接；不伪装业务看板。使用简单 Django 模板，不锁定前端框架。
- GET /api/health/ 返回稳定 JSON 状态，表示服务存活，不表示数据库或AI连通。POST拒绝。
- Django 内置admin/auth保持标准骨架，不实现自定义登录、项目、任务或AI业务。
- 默认SQLite开发库在 .tools/，仅本机开发启动和测试；不代替未来MySQL决定。生成的本机Django key也存忽略目录，不进源码。
- 只绑定127.0.0.1，给出明确启动命令；Run-Backend.cmd 从任意当前目录可双击启动，关闭窗口或Ctrl+C停止。不部署常驻服务。
- 实际检查 Django system check、必要测试、迁移及HTTP首页和health；启动验证后停止测试进程。
- 使用现有锁定依赖与工具，禁止联网下载、推送、创建账号或读取API key。

验收后记录启动入口、结果与明天第一个小任务草案；业务阶段不自动跨越。
