# T014 开源参考与快速开发方案

调研日期：2026-10-23。基线916035d，PLAN-r5 / RULES-r8。本轮按用户要求学习GitHub同类项目，并交付界面样稿。没有把参考产品安装运行，也没有把它们的README能力计为本项目已实现；检查的是官方README、架构、部分模型/执行器源码及许可证。

## 与本项目最相关的参考

| 项目 | 本轮实际查看 | 可学到什么 | 本项目采用方式 |
|---|---|---|---|
| [Plane](https://github.com/makeplane/plane) | README、COPYRIGHT、apps/api/plane/db/models/project.py与issue.py | Django项目/任务建模；负责人、日期、状态、任务层级与筛选展示的组织 | 参考领域边界，自己实现当前最小模型；不把复杂企业版代码整体并入。源码标注AGPL-3.0-only，本轮未复制其代码。 |
| [OpenHands Agent Canvas](https://github.com/OpenHands/OpenHands) | docs/architecture.md、docs/ACP_AGENTS.md、src/constants/acp-providers.ts、package.json与LICENSE | UI与Agent Server分工；本地/远程后端；外部Agent注册与适配 | 参考后端适配器与事件展示设计。当前主线为React/TypeScript控制台，MIT；其后端与运行隔离不是单靠界面提供的，不是现有Django应用的即插即用模块。 |
| [Vibe Kanban](https://github.com/BloopAI/vibe-kanban) | README、crates/executors/src/executors/mod.rs、local-web/package.json与LICENSE | 看板任务进入工作区执行、统一不同Agent能力/错误、查看差异与反馈 | 参考Task→Run→Events→Artifacts→Review流程，暂不移植Rust后端或整套React前端。Apache-2.0；原公司已公告关闭、项目转社区维护。 |

Vibe Kanban的[官方公告](https://www.vibekanban.com/blog/shutdown)日期为2026-04-10：公司关闭，项目继续开源和社区维护，公告描述远程服务退场与本地工作区延续。不能把当前仓库有提交或状态页在线推断为原商业服务持续承诺。它仍有设计参考价值，不作为本项目远程团队服务的依赖。

OpenHands的ACP文档描述经Agent Server启动外部协议适配器；这不证明WorkBuddy已经支持同一协议，也不代表本项目已经接通Codex。当前开发中使用的A2A Hub与未来产品连接器属于不同层。后续先验证一个工具的真实输入、事件、产物、退出和失败，再扩工具数量。

## 界面与动效取舍

| 方案 | 核实结果 | 本轮用途 |
|---|---|---|
| [Tabler](https://github.com/tabler/tabler) | Bootstrap 5上的HTML/CSS工作台组件，MIT；有Django集成文档 | 隔离样稿用1.7.0 core CSS，复用按钮、表单、卡片、徽标等；不安装整仓库，不加载可选插件或Bootstrap JS。 |
| [Motion](https://github.com/motiondivision/motion) | 核心MIT，支持普通JavaScript、React、Vue；[官方快速开始](https://motion.dev/docs/quick-start)说明全局脚本与固定版本 | 样稿用14.6.0本地JS，仅做短时淡入/位移和操作反馈。Motion+付费内容未使用。 |
| [AutoAnimate](https://github.com/formkit/auto-animate) | MIT，可用于普通JS/多框架DOM子元素进出/移动 | 暂留候选；与Motion不同时堆入样稿。待真实看板有DOM重排时再评估。 |
| [React Bits](https://github.com/DavidHDev/react-bits/blob/main/LICENSE.md) | 当前MIT + Commons Clause；条款允许用于商业应用，但对组件、工具及导出物本身的转售等附加限制 | 本轮未引入，也不把其组件称作普通MIT组件。 |
| [Animate.css](https://github.com/animate-css/animate.css/blob/main/LICENSE) | 当前Hippocratic License 2.1 | 本轮未引入，不依据旧列表将其误写为MIT。 |

许可按本轮实际读取版本记录；可见源码、免费和MIT是不同事实。复制时需随文件保留对应署名和许可证。项目整体商业化方案仍待产品验证，本轮不作许可证兼容性的全面审计。

Tabler原生HTML/CSS可配合当前Django模板；因此现阶段建议先统一模板与组件，避免维护两套前端和两套认证流程。React/TypeScript作为复杂交互增长后的候选，正式前端/桌面框架仍未锁定。Tabler与Motion在此处的采用仅限隔离样稿。

## 如何把开发提速

1. **把界面基线一次定清楚。** 先确认项目总览、文件工作区与任务详情的布局、按钮、表单、提示与状态语言。将字号、颜色、间距、圆角和动效写成共享变量；后续页面复用同一套组件。
2. **先统一已有页面。** 由core提供共享base模板与静态CSS；账号页保留窄布局，项目页用统一导航，文件工作区最后迁移，保留picker ID、字段name/action、CSRF和原生dialog。每次迁移后验证一条真实流程，避免每页重新写样式。
3. **按既定阶段做可演示闭环。** P2继续体验验收；后续P3成员邀请，再P4计划任务，再P5运行时模型配置/AI结构化拆任务。每次交付都连真实后端，错误、空状态和加载状态一起完成。
4. **先打通一个外部AI工具。** P6用一个已批准任务验证Task→AgentRun→RunEvent→Artifact→Review：能记录开始/步骤/心跳/失败、查看真实文件差异、核对固定测试并人工验收。断连显示陈旧/失败，不能靠动画或AI自报伪造完成。
5. **再扩角色和工具。** 规划、执行、复核使用统一任务与执行契约。以适配器隔离不同工具的CLI/API，不同时复制多套聊天、凭据和进度实现。跨平台外部写入依既定P7范围另行形成规格。
6. **复用成熟小部件。** 后续确有需求再加入编辑器、看板拖拽、终端等组件；优先选能与当前架构合用、许可清楚、依赖可控且有实测的模块。

这些是依赖顺序与工程判断，不是固定工期保证；完整功能的时间取决于接入工具、授权、运行隔离和验收结果。对当前求职目标，优先交付一条能够演示并解释实现的完整流程。

## 界面样稿与“完善”的验收含义

样稿：docs/previews/workbench.html。它展示候选视觉与交互，不连接真实账号、数据库、文件或AI，不把任务/AI规划入口伪装成可用功能；示例新建仅存在本页内存。固定依赖及SHA256见previews/assets/vendor/SOURCES.json。所有资源本地保存，首次准备下载后运行样稿无需第三方CDN。

后续真实界面按以下方向验收，具体阶段再写可执行检查：

- 用户看得懂当前项目、授权目录、权限范围和下一步；界面状态来自同一后端判断。
- 同一种按钮/输入/错误/成功/空状态有同一视觉与文字规则，控件行为完整。
- 保存失败保留输入、过期状态可恢复、加载可结束且提供重试；状态变化有短时反馈。
- 桌面、平板宽度、窄屏可用；键盘焦点、标签、ESC和焦点返回可用。
- 尊重系统减弱动效；动画失败内容仍显示，动画不阻塞提交或授权。
- 每条声称可用的功能都经过真实浏览器与后端验证；功能尚未实现时明确标记。

没有仓库或组件能保证组合后的产品“完美”。这里把目标转成能逐项验证和修正的结果。

## 当前与下一步

本轮已完成源码调研、WorkBuddy只读审计，并制作隔离样稿供视觉评估。正式业务页仍沿用现有实现，P2整体用户验收尚未确认。候选下一项是把认可的视觉基线接入现有项目列表/详情，随后迁移工作区；它与P3团队业务实现分开跟踪。

精确来源URL与Git blob SHA记录在OPEN_SOURCE_SOURCES.json；第三方样稿文件固定版本与实际字节哈希另见vendor/SOURCES.json。未使用参考项目名称/商标冒充本产品品牌。
