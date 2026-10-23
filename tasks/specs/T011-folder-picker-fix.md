# T011 修复“选择文件夹”一直等待

APPROVED，用户报障授权；PLAN-r3 / RULES-r6，基线e53b058。仍为第一步修复。Codex规划/复核，WorkBuddy唯一实施者。

## 根因与决定

旧按钮POST action=pick，同步等待后台PowerShell ShowDialog，120秒才超时。用户端无弹窗，实机发现对应后台进程无可见主窗口。该调用没有在浏览器内创建选择界面，且之前只有mock测试。当前本机网页改用页面内目录选择器，去掉对系统弹窗进程的依赖，不通过延长超时掩盖问题。

## 用户闭环

- 点击“选择文件夹…”立即打开网页dialog，显示驱动器/目录浏览器。只查询目录名称、路径等选择所需元数据，不读取文件内容，不写文件，不授权。
- 支持驱动器起点、进入子目录、返回上级，以及在弹窗中直接输入绝对目录路径后“打开目录”。列表最多100项，截断清楚提示；无子目录也能“使用此文件夹”。
- “使用此文件夹”把实际绝对路径填入原grant-path，关闭弹窗；若当前已有授权则展开“更换文件夹”。原“授权此文件夹”仍单独点击才生效。取消/ESC不改路径或授权。
- 弹窗内有正在加载、可重试错误、空目录；网络请求8秒AbortController超时，不造成整页导航/无限等待；加载中防重复导航，关闭后中止请求，过期响应不得覆盖新选择。
- 目录名用textContent，禁止拼innerHTML；HTML dialog有可访问名称、表单标签、键盘关闭，390px可用。保留手动路径入口。无JS时仍可输入路径授权，不提交旧action=pick。

## 服务契约与边界

- 重用picker.py为纯文件夹元数据服务，移除PowerShell/subprocess/temp ps1代码；独立测试实际临时目录和拒绝情况。Python3.12本机os.listdrives可用则列drive，非Windows可仅平台根；不新增库。
- 新POST /workspace/folders/，CSRF + never_cache + require_POST；表单path空串返回drive起点，非空校验绝对、本地普通既有目录（复用Workspace.validate_root逐级拒绝reparse/symlink）。拒绝UNC/设备/相对/..点段/控制字符，不resolve跟随链接；只列普通非隐藏目录，跳过文件/隐藏/link/reparse；返回path,parent,drives,directories[{name,path}],truncated。
- 输入错误/不可访问目录返回稳定JSON error与400，GET405，CSRF403；不读取文件内容、不写盘、不改session授权。仅本机单用户开发服务中提供选择元数据，未建远程成员权限。
- 旧action=pick需快速给出友好提示或回到当前页面，不再调用原生窗口；保留CSRF且不得新授权。现有读写/root+grant_id权限、越界、冲突规则不变。

## 允许范围、验证与停止

backend/workspaces/{picker,views,urls,tests,templates,static}及tasks/current.md、tasks/logs/T011.log。保留现有服务/授权安全用例；按明确替代边界更新6个原生mock测试与旧pick页面断言，不保留dead subprocess代码，也不删除其它测试掩盖失败。

先写失败回归再实现。验证目录元数据不会读文件或改session/写盘、空目录/Unicode/目录返回/非目录/缺失/相对/UNC/..、根/子目录junction拒绝、目录列表过滤、100项、POST/GET/CSRF与旧pick快速返回；完整pytest+ruff backend/tools+Django check。日志记实际命令退出码；原生窗口不再作为未验证主入口。

不联网/装依赖/派agent/commit/重启或新增服务；当前8000 autoreload。目标180秒、240秒到可验收点停并写current，剩余如实报告。最终TASK_RESULT标记简报。Codex真实Chrome点击选择→浏览实际测试夹→选择填路径→授权→读写→取消/错误/移动视图后交用户体验。
