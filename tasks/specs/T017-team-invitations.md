# T017 团队邀请闭环

2026-10-23，PLAN-r8 / RULES-r11，基线9398e51，根D:\Users\28369\Desktop\AgentWorkspace。用户“你先继续做”授权原待做的团队邀请；已有账号/成员/画布保留，不将本次继续写为T016视觉认可或全路线批准。

## 目标与范围

owner在团队面板进入“邀请成员”→生成一次性链接/分工角色/有效期→复制链接→受邀者注册或登录→返回邀请确认页→明确POST加入→本人参与项目和画布可见。撤销、过期、已使用/篡改链接不可让新用户加入。角色仅用于任务分工，不授予owner权限或本机文件访问。

仍用Django5.2/SQLite/现有模板与CSS/JS；不装库，不发邮件/聊天、不购买/发布、不改监听/ALLOWED_HOSTS，不调用AI。当前localhost链接只针对同一服务测试，跨设备服务部署另做。

## 写入范围与分工

WorkBuddy唯一代码写入者：projects/models.py追加ProjectInvitation、migration0003、invite_forms.py/invite_views.py/invitations.py(按需小工具)、urls.py、templates/projects/invitations.html/invitation_join.html、static/projects/invites.js/css（小文件仅复制反馈/必要样式）、test_invitations.py；board.html团队面板增加owner邀请入口并移除“邀请链接后续”旧文案；projects/views.py项目列表只增加joined_memberships，list.html追加参与项目卡片（不改owner列表契约与文件授权）；accounts/views.py安全signup next和登录/注册模板互链保留next，accounts/tests.py加相应回归。可写tasks/logs/T017.log和reports/T017.md。

另允许projects/apps.py及invitation_logging.py的小型专用日志过滤器：只对django.server/django.request中的/projects/join/<token>/及其编码next参数脱敏，防止开发访问日志记录可用邀请。保留其它日志和状态信息，不改全局settings/关闭logger。用实际logging测试确认明文token不出现、普通请求日志不受影响。

不改rules/plan/spec、旧测试断言、vendor、画布渲染逻辑、file/grants/picker、settings/依赖，不操作真实用户DB、不运行真实migrate/服务/commit、不派agent/广播。Codex审查并备份后实际增量迁移，独立浏览器验收。超时不重复派发，完成小片立即回报退出。

## 数据和接口

1. ProjectInvitation：UUID主键(default uuid.uuid4, editable=False)、project CASCADE related_name invitations、created_by User SET_NULL nullable、role CharField80 blank、expires_at DateTimeField、created_at auto、revoked_at nullable、used_at nullable、used_by User SET_NULL nullable。有效期1/7/30天选项，默认7；一次使用。不要持久化原始签名token，URL由django.core.signing.Signer(salt固定projects.invite.v1).sign_object({'id': str(invitation.pk)})生成，校验unsign_object/BadSignature、payload类型/UUID；可再次展示有效链接。expiry/used/revoked以数据库判断，不以客户端状态为准。
2. URL projects命名空间：invitation_list GET /<pk>/invitations/（owneronly）；invitation_create POST /<pk>/invitations/new/；invitation_revoke POST /<pk>/invitations/<uuid:invite_pk>/revoke/（须同项目owner）；invitation_join GET/POST /join/<str:token>/。owner管理401/匿名重定向/非owner404，所有POST CSRF，GET不创建邀请/加入/消费，不允许客户端改project/created_by/used_by/kind。
3. 邀请管理页显示角色、到期日、有效/撤销/已用/过期文字状态；有效链接可手动选中和复制（成功后才提示已复制，clipboard不可用选中输入提示Ctrl+C），实际POST撤销和生成。只owner可见签名链接；普通成员无管理入口/链接内容。生成后PRG，400保留输入。邀请列表最多最近50条（生成不限制总量），不把过往所有链接无限加载。用request.build_absolute_uri生成链接，现有Host校验不变。
4. 加入页公开只显示有效邀请的项目名/分工角色和确认说明，不显示任务/成员列表、owner本机路径或任何授权。恶意token/不存在404；过期/撤销/被他人使用410，页面可恢复返回首页/项目。POST加入须登录（匿名显示登录/注册入口而不加入）；同一用户已加入或重复接受不改原角色、不重复行、不把链接消耗给已是成员的owner；已被当前用户接受可回画布，不能二次消费或转让给另一用户。
5. 加入事务必须覆盖邀请消费与ProjectMember创建：对有效、未用行进行条件update(used_at为空/revoked_at为空/expiry>now)，只有更新成功才创建真人成员，失败重读返回合适结果。get_or_create与现有(project,user)唯一约束配合；成员创建失败整笔回滚，不能留下已消费但未加入。SQLite select_for_update不能单独当并发保护；无需夸称已压力测试。保存role来自Invite；不接客户端角色/owner/user/path/grant。已加入前后会话file grant不凭邀请增加/转移。
6. 注册登录返回：SignupView只接受url_has_allowed_host_and_scheme(allowed_hosts={request.get_host()},require_https=request.is_secure())认可的next，非法退回既有默认，不放开外站；注册成功保留clear_grant。signup/login互链和hidden next保留安全目的地，失败表单仍带next。登录已有Django安全next不削弱。只为邀请补安全返回，不改密码规则/账号权限/已有默认跳转。
7. 项目列表owner集合及原授权渲染不变；额外joined_memberships=本人human成员且project.owner不是本人，select_related('project')，展示“参与的项目”、分工角色、链接board；不显示文件夹位置、关联/授权按钮或owner设置。owner/member画布可见性沿用现有规则，加入后可刷新看见项目，退出重新登录仍保留成员。

## 测试和验收

先RED→GREEN：非owner/跨项目管理拒绝；POST/CSRF；签名被改/无签名UUID拒绝、过期/撤销/已用410、GET不产生行或消耗、首次加入真人role、重复加入幂等/已有成员role不改、第二用户拒绝、失败创建回滚、不接受伪造role/user/owner/path；成员看不到owner目录与管理链接且原文件/workspace仍404；signup内部next/外站与//外站拒绝/账号grant清除；登录注册互链保留next、参与项目只显示本人、拒绝外人。重要输入/项目名HTML保持转义。

命令：.venv\Scripts\python.exe -m pytest -q backend/projects/test_invitations.py backend/accounts/tests.py；最终pytest -q、ruff check backend tools、backend\manage.py check、makemigrations --check --dry-run。生成迁移可makemigrations但不要migrate真实库。已有199项回归保持，不删/skip/弱化。

Codex Chrome双/三临时账号：owner生成链接→匿名打开→从登录跳注册→注册后返回→GET无成员→确认加入→画布/参与列表→owner分配任务→成员更新本人状态；另测撤销/到期/已使用与外站next拒绝，复制反馈/390布局/JS异常/降级。测试URL/token/密码不写普通日志/报告明文；只记录脱敏路径/结果，勿打印HTTP完整token。实际外网仍阻断已知环境注入单列。

本轮完成后交用户体验；当前服务仍127.0.0.1:8000，未远程部署，不把邀请当本机文件或AI执行授权。
