# T015：样稿设计接入真实业务

2026-10-23，PLAN-r6 / RULES-r9，基线fabe03f，开工git干净。用户查看T014后连续要求“继续”，按此前建议迁移现有真实界面，不进入P3团队或AI业务。

## 目标与工作根

D:\Users\28369\Desktop\AgentWorkspace。登录/注册、首页、项目列表/创建/详情、真实文件工作区共用T014的深色侧栏、暖灰底、白色内容、蓝色强调与统一控件，并加载本地Tabler/Motion。全程使用服务端真实数据；禁止复制样稿虚构账号/项目/成员/任务/状态或内存新建替代后端表单。

## 实现顺序与边界

1. 新增backend/core/templates/core/base.html、core/static/core/app.css、app.js；app.css复用样稿设计变量/结构，补齐现有.card/.field/.actions/.dir/.status/.alert、表单输入/textarea等实际类名兼容；全局样式作用于工作台自身，避免破坏原生dialog。共享base提供导航、真实用户名、POST登出、消息/error/notice、heading/content/scripts等块与减弱动效开关。匿名账号页保持窄表单与清晰品牌，登录用户能进入已有页面。
2. accounts/base、projects/base、core/home改用共享base。账号子模板保留字段和中文按钮；项目模板保留全部当前授权/关联文案、POST接口与服务端判断。列表可加基于已加载本人项目的搜索与授权状态筛选，默认HTML完整可见，JS禁用仍可操作真实链接/表单。筛选只控制展示，不计算或修改权限。
3. workspace.html最后迁移为extends，去除重复shell/导航/全局样式，保留目录/编辑/新建/授权及picker的真实结构、ID、表单字段与语义；原picker inline脚本可原样放scripts block，不必重写/搬出/改协议。JS中若有模板URL不可直接移到无模板的静态文件。workspace专用CSS可留extra_css块，不复制旧body/main等全局规则来覆盖新布局。
4. 开源文件由Codex预先按哈希复制至core/static/core/vendor，禁止联网、改vendor/许可/manifest或另装前端框架。通过load static加载，不引用docs目录或CDN；不加载Bootstrap JS。未实现能力只在导航明确置为规划中或禁用，无虚假统计/模拟进度。
5. Motion只是渐进增强：可做内容/消息短时渐入与小幅位移；CSS处理hover/focus；不动画dialog本体，不延迟/吞掉POST或picker请求，不做泛用submit拦截/禁用造成表单字段丢失。系统prefers-reduced-motion必须跳过；可存非敏感动效偏好，严禁存账号/密钥/授权token/路径等信息；动画或JS失败内容仍可见。

## 不可改变

后端views/models/grants/services/picker逻辑、路由、settings、迁移、依赖与真实用户数据不改。GET不授予文件访问；关联显式POST且旋转grant_id；同目录不同项目不自动共享；旧页写入拒绝；退出POST；所有CSRF、自动转义、next校验、保存冲突保留编辑、链接/硬链/越界拒绝、64KiB/100项边界都保留。所有表单name/action/method和picker ID原样；禁止表单嵌套、重复登出按钮。首页原health链接与契约文案可保留为低优先信息。

## 分工与验证

WorkBuddy唯一业务写入者，不派其它agent。允许改上述模板、app.css/js与必要模板相关测试；不改rules/plan/spec、vendor或docs预览，不启动/重启服务、迁移、操作开发DB、创建真实账号或commit。每片完成跑相关现有测试，最终pytest全测、ruff、manage.py check，不弱化测试或安全规则；记录tasks/logs/T015.log与reports/T015.md，简短回填current。Codex之后独立审阅与浏览器验收。

Codex验收真实注册登录→新建项目→picker授权→明确关联→项目内读/写/新建→保存冲突保留内容→撤销/退出；另账号不能访问、CSRF拒绝、GET登出拒绝。临时测试账号/目录独立，精准清理，不改用户admin/开发项目。检查390/768/1440布局、键盘/ESC/焦点返回、消息可见、系统减弱动效、Motion缺失降级、静态资源200/哈希、无应用外部资源。已知本机Kaspersky注入单列并在隔离会话拦截外部网络，不弱化未知请求断言，不改安全软件设置。

当前8000未监听，Codex在资源/模板完成后单独启动已有runserver(不重置DB、不重复启动)，必要时实际验证静态finder；不把样稿8030地址当作真实业务。技术通过后交用户体验，不自动推进P3。
