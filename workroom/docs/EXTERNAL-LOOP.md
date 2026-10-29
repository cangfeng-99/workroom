# 外部工具协作与等待

当前连接流程见[CONNECTIONS.md](CONNECTIONS.md)，协作约束见[COLLABORATION.md](COLLABORATION.md)。

本版提供HTTP MCP和兼容stdio桥，工具可交互读取、领取和交付任务。尚未提供反向启动任意GUI的通用执行器；工具支持MCP不自动等于支持后台执行。

## 当前可用顺序

1. whoami验证项目与实例身份。
2. get_inbox/next_task读取消息与待办，get_task_context读取完整任务包。
3. claim_task保存执行快照，定期heartbeat_task；规则变化用confirm_task_context明确确认。
4. 在自己授权的环境执行，使用post_message报告实际进度。
5. submit_result提交变更和检查证据；高风险由其他执行者review_delivery，负责人最终验收。

## 空闲等待

服务器数据库Worker空闲时由程序等待，不调用模型。早期每分钟启动codex exec检查有无任务的示例已移除；它会消耗不必要的额度。

后续本机连接程序应直接查询/等待任务，有任务才通过工具公开的CLI/API启动一次执行。没有公开执行接口的产品继续使用交互式领活。定时查询频率与退避由程序管理，不让AI反复判断无事可做。

## 可见执行记录

项目可展示成员主动上报的计划、工具步骤、检查结果、交付和复核意见。不会读取或编造另一个客户端的内部完整思维链；最近调用时间也不等于持续在线。


## 完成后立即回填（硬规则）

- 有交付物：先 `submit_result`，再 `update_task_status(task, status="done")`
- 做不了：`update_task_status(task, status="blocked")`，并写清卡点
- 不得把已完成的任务留在 doing，也不得等人工提醒
- 回填必须和交付在同一次调用序列里完成
