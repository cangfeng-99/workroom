# T014：开源参考调研与界面样稿

2026-10-23，PLAN-r5 / RULES-r8，基线916035d。用户要求在GitHub学习同类项目、加快开发，并使用开源界面和动画效果。本任务不将P2视为用户已整体验收，不进入P3业务实现。

- T014A：WorkBuddy只读审计已完成；现有accounts/projects/workspaces/core四套独立shell，重复样式多。候选共享模板放core/templates/base.html，静态资源core/static/core/；须保留POST/CSRF/字段/目录dialog与服务端授权语义。尚未改业务页面。
- Codex：查阅GitHub原始README/架构/许可证及官方UI文档，落盘参考选择、直接复用与学习边界、开发顺序。当前参考Plane、OpenHands Agent Canvas、Vibe Kanban；后者原公司宣布关闭并转社区维护，不能将商业维护视作持续承诺。
- T014B：WorkBuddy只在docs/previews/做可交互样稿：workbench.html、assets/workbench.css、assets/workbench.js。只使用已落盘的vendor/tabler-1.7.0.min.css与vendor/motion-14.6.0.js；无npm/全局安装/外部请求/新服务/用户库/API/文件访问，不改backend、rules或plan、不commit，不派额外agent。
- 样稿是桌面工作台：清晰侧栏、顶部工具栏、项目列表/卡片、文件夹关联/授权状态与详情面板。暖灰底、白色内容、深色侧栏、克制蓝色强调、统一密度与图形。不要营销hero、大字渐变或满屏粒子。真实未实现的任务/AI入口置为规划中；顶部明显标注“界面样稿 · 示例数据，不连接账号、文件或AI”。
- 可操作：本页示例项目搜索/状态筛选、打开项目详情dialog、演示新建项目（内存中添加，清楚说明不入库）、切换减弱动效、通知反馈。原项目名与状态不会被改写。所有显示文本用textContent等安全方式，不用用户输入拼innerHTML。
- 使用Tabler组件的布局/按钮/徽标样式，Motion vanilla做短时淡入/小幅位移与反馈；hover/focus用CSS。避免布局/height无限动画，尊重系统prefers-reduced-motion；动画或JS加载失败时内容仍可见。dialog保留原生键盘/ESC/焦点返回，不动画dialog本体。
- 响应式至少390/768/1440可用无横向溢出，焦点清楚，对比可读，按钮有明确标签，无外部字体/图片/遥测。
- 完成后WorkBuddy停止写入，仅返回简短结果；Codex浏览器实测交互/系统减弱动效/资源离线/布局并保存证据。已有业务全测基线沿用T013，不把样稿当作已接入真实功能。
- 规格与当前进度由Codex维护；依赖许可证、固定版本、下载地址和SHA256在docs/previews/assets/vendor/SOURCES.json记录。正式前端/桌面架构仍为候选，后续按用户反馈把同一套组件逐页接现有功能。
