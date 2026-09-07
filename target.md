# Zeta：Agent 核心能力实施目标

更新：2026-09-07。学习顺序以 [days/summary.md](days/summary.md) 为准。本文件描述目标，不是完成功能清单。

## 目标与职责

用 Python 理解并实现 Pi 风格的本地 Coding Agent，只接入 DeepSeek。模型接入和 CLI 直接提供，核心运行策略自己手写；不逐文件翻译 Pi，不兼容其内部存储格式。

| 部分 | 分工 |
| --- | --- |
| 单次模型请求与流式协议 | PydanticAI direct，复用消息、调用、usage 和错误类型 |
| 参数 schema 与校验 | Pydantic；direct 不会自动执行 Python 工具 |
| Agent 状态与 Loop | Zeta 决定请求、执行、继续、停止；不用 Agent.run() |
| Hooks 与事件 | Zeta 定义调用时机、返回契约、修改权限、异常边界和通知顺序 |
| 工具调度与运行控制 | Zeta 处理授权、配对结果、预算、取消和失败 |
| Session | Zeta 定义记录和恢复语义，SQLite 配套层承担存储细节 |
| Memory | Zeta 定义显式写入、来源、scope、召回、冲突与遗忘 |
| Context 与 Compaction | Zeta 定义输入选择、预算、摘要覆盖范围和保留边界 |

## 核心生命周期

```text
恢复 Session → 保存用户输入 → 召回允许作用域的 Memory
→ Context 构建视图，必要时 Compaction
→ before_model → 输入复核 → 单次请求 → 响应校验与保存 → after_model
→ 有工具：预检 → before_tool → 执行/拒绝 → after_tool → 配对结果提交
→ turn_end → after_turn → 下一轮或保存终态 → run_end
```

Hook 在固定边界参与处理与决策，Event 发布状态变化。权限拒绝不执行；观察性监听器失败不触发工具重放。完整契约见 [Day 2](days/day2.md)。

## 必须保持的约束

- 完整 assistant 响应与工具结果按 tool_call_id 配对，参数尚未完整或响应截断时不执行工具。
- 发下一次模型请求前全批结果齐备；次数不足时不启动无法完成的批次。
- Session 是原始事实；Memory 是跨任务记录；Context 是本轮模型视图，不能混用。
- before_model 修改视图后重新检查预算和协议，不能绕过固定指令或权限。
- after_tool 不得改写结果 ID、工具名或把失败/拒绝变成功；保留原始结果。
- Compaction 保留近期完整交互和原始历史，摘要记录来源；估算 token 与实际 usage 分开。
- 取消不伪装成可重试工具错误。数据库事务不能保证外部副作用恰好执行一次；恢复时不自动重放不确定的副作用。
- read 限当前工作区、敏感路径与输出量。这是可信本地工作区限制，不是对恶意并发文件系统的沙箱。

## 主线与扩展

七个核心单元：状态/Loop → 工具/Hooks/事件/运行控制 → Session → Memory → Context → Compaction → 串联。

完成主线后，按依赖补充审批后的 write/edit/bash、Session 树与 fork/搜索、流式显示、Steering/Follow-up、扩展注册，以及隔离 Worker。
Worker 最多一层，先单个只读再限并发，共享预算和取消；不能把这些学习目标当作 Pi 默认内置的多 Agent 功能。长期 Memory 也是 Zeta 的增强方向。

暂不做多 Provider、Web/TUI、FastAPI、向量库、递归 Worker、分布式执行、MCP 或 Pi 格式兼容。不预先创建未使用的空模块。

## 技术栈与交付状态

Python 3.14、uv、PydanticAI slim 的 openai extra、Pydantic、dotenv、argparse、asyncio；已有 Ruff、Pyright 和 uv_build 检查。
SQLite 是后续 Session/Memory 的统一存储目标，JSON Lines 仅用于可选事件输出。

当前提供单次文本请求/流、CLI、单次完整响应适配、read 和事件编码。工具 Loop、Hooks、Session、Memory、Context、Compaction 尚未实现；SQLite 配套层进入对应单元再补齐。

文档代码草图与运行结果分开报告。使用已有检查和真实手动任务验证，不新增或修改测试、fixture、mock、snapshot 或内联自测。检查命令见 [README](README.md)。
