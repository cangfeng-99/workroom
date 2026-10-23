# T012 P2账号与项目最小闭环

APPROVED：P1用户验收后说“开始下一步”。PLAN-r5 / RULES-r8，基线3be613c。Codex规格/复核，WorkBuddy实现；一次一个写入者。沿用Django5.2、本机开发SQLite、服务端session、服务器渲染页面，无新依赖；增量迁移保留已有数据，不重置DB。最后Codex真实Chrome验收，再交用户，不跨到团队/AI。

## 先行任务T012A：账号与文件权限归属

- 新accounts app：GET/POST /accounts/signup/ 使用Django UserCreationForm与现有密码验证器，username/password1/password2，创建普通用户并登录；GET/POST /accounts/login/ 继承LoginView；POST /accounts/logout/ 使用LogoutView，GET405。登录next须Django安全校验，外站next不能跳转。注册无需邮箱/短信，无密码重置/第三方登录/用户资料/管理员预置。
- 不改AUTH_USER_MODEL，不定制密码算法，不存明文密码或打印密码。中文标签/错误/密码提示、未登录入口与已登录用户名/退出按钮；模板自动转义，所有POST保留CSRF，账号/私有页面no-store。首页保持原服务/健康链接兼容。A阶段LOGIN_REDIRECT_URL先首页，B阶段改projects:list。
- 新workspaces/grants.py统一SESSION_KEY/LEGACY_SESSION_KEY、get_grant(request)与clear_grant(request)；原views可导入常量供旧测试兼容。get_grant只接受已登录且session user_id字符串与当前用户PK匹配的root/grant_id，旧匿名/缺失user_id授权失效；可预留project_id空串。grant POST保存user_id。成功注册/登录清除原文件授权，退出flush session；失败登录不授予权限。
- /workspace/所有页面操作要求登录（login_required，匿名跳登录）；POST /workspace/folders/匿名返回401 JSON {error:authentication_required}，GET405，CSRF403，登录后原目录选择保护不变。选择器错误字典加“请先登录后再选择文件夹”。/api/health/继续公开只读，不改变CSRF策略。
- 旧workspaces HTTP测试为主client及FolderBrowserEndpoint client添加真实User+force_login；“另一浏览器无目录授权”用同账号另一Client登录但无grant，继续403。保留原CSRF/越界/链接/跨会话/撤销/冲突/文件名断言，不改服务单测。不为新增门禁删除安全用例。
- A验证：注册哈希/成功登录、重复用户名/弱密码/密码不符、登录错误、外站next拒绝、POST退出+GET405、CSRF、匿名文件页/目录API拒绝、登录/退出清除旧grant、账号不匹配grant拒绝；保留P1全套。最少模板复用可用accounts/base.html，不做无关界面重构。
- A允许backend/accounts/**、workspaces/grants.py、workspaces/views.py/test_views.py/workspace.html最少登录联动、config设置/路由、首页导航及A测试/log/current；不写projects业务代码，不迁移/重启服务/commit。先失败测试再实现，完成pytest+ruff+check后停。报告不超过500汉字，详细证据tasks/logs/T012A.log。

## 后续任务T012B：本人项目与工作区关联（A验收后才派发）

- 新projects app与Project模型：默认整数PK、owner FK(settings.AUTH_USER_MODEL)、name(120)、description(2000，可空)、workspace_path(1024，可空)、created_at/updated_at；ModelForm仅name/description，不接收客户端owner或任意workspace_path。项目列表按本人与更新时间筛选；详情/所有POST均owner过滤，别人的/不存在项目404。保留数据的0001增量迁移。
- 路由：GET /projects/（本人列表与空状态），GET/POST /projects/new/（新建），GET /projects/<int:pk>/，POST /projects/<int:pk>/workspace/（关联当前已授权文件夹），GET /projects/<int:pk>/open/（进入工作区）。全部需登录，CSRF/no-store。没有项目编辑/删除/邀请/成员/任务。
- 创建页可选“关联当前已授权文件夹”；没有当前有效grant则禁用/提示先到工作区选择授权。创建/关联POST只取服务端get_grant.root，校验既有目录后保存workspace_path，不相信提交的路径/owner。展示当前可关联路径，详情可直接“选择并授权文件夹”跳独立工作区，再返回项目关联。创建时不勾选也可先建空项目。
- 持久化关联只是记住位置；重新登录/新浏览器打开项目仍要显式授权。项目无关联open跳详情提示；有关联open跳/workspace/?project=<pk>。query project必须合法正整数且项目属当前用户，别人的/无效404且不触碰文件系统。
- 项目上下文进入workspace后，只使用对应project_id的grant。绑定当前已授权文件夹是显式POST，可将现有grant绑定该项目并刷新grant_id（旧页写入失效）；独立工作区只接受project_id空的grant。授权项目目录时根必须等于该Project.workspace_path，不能用客户端root篡改关联。项目页未授权时仅预填已关联根，仍需点授权，不在GET授予/撤销权限。
- workspace所有链接/成功重定向保留project query；可使用request.workspace_project作为本次已校验上下文与一个URL helper集中处理。模板显示项目名/返回项目；项目上下文只授权其已关联目录，更换关联从项目详情完成。避免把项目path存在当作文件权限。目录选择器元数据只要求登录，不获得文件内容权限。
- B允许projects/**、config app/routes/redirect、首页导航及workspaces的project上下文/URL/grant最少联动与测试。不要重构文件系统服务。测试owner伪造忽略/跨账号404/匿名/表单校验/CSRF/持久化、无grant不能关联、旧grant拒绝、project切换隔离、保存重定向项目保留、重新登录项目存在但需要授权。完整pytest/ruff/check/makemigrations --check；本机真实迁移由Codex审阅后执行。

## 执行约定

分A/B小任务，目标各180秒、最晚240秒写checkpoint/log/current并停，未完成如实报告；不自行派发下一项、不联网/安装/起服务/commit。先记RED关键错误和GREEN实际退出码，命令使用.venv/Scripts/python.exe。每个检查只跑需要的范围，最终完整一次即可；输出简短，不全量打印current历史，不输出密钥/密码。timeout不重复派发，Codex核对实际任务/进程后收口。默认开发库仍SQLite，最终MySQL/桌面技术与模型连接未锁定。

官方依据（Context7本轮不可用，已查官方）：https://docs.djangoproject.com/en/5.2/topics/auth/default/ ，https://docs.djangoproject.com/en/5.2/topics/http/sessions/ 。用户已明确授权本阶段的认证流，无需再次申请同一授权。
