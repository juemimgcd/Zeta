# Zeta 学习路线：手写 Agent 核心

更新：2026-09-07。新编号按核心能力重新排列，不再对应旧版 Day 1–7。

目标是理解换框架后仍然成立的机制：Agent 怎样行动、记住信息、选择上下文、压缩历史、恢复工作。无需先背完 CLI、SDK 和流式事件 API，也无需逐文件翻译 Pi。

## 怎么学

先用 [配套基础代码](support.md)，再从 Day 1 写循环。已有模型调用和 read 的部分可以复用，不必重做旧版前三天。
每天只看“核心问题 → 手写入口 → 验收”，卡住再展开参考思路。参考思路是算法说明，不是整套可以覆盖源码的答案；support.md 明确区分已落地的 model_io.py 与待核心入口完成后接入的 CLI。

“天”表示一个学习单元，不要求一天完成。前 7 个单元构成主线，后续内容按需要扩展，不再强制凑满 30 天。

## 哪些直接提供，哪些自己写

| 直接提供或复用 | 你手写的决策 |
| --- | --- |
| CLI 参数、环境变量、错误显示 | Loop 什么时候请求、执行、继续、停止 |
| 单次模型请求、连接、消息类型、流式拼接 | 工具批次校验、权限、错误回传、预算和取消 |
| 事件排版与 JSON 编码 | Hook 调用顺序、修改权限、拒绝与异常处理；事件发布时机 |
| 文件读取、Pydantic 参数校验、数据库连接和消息序列化 | Session 保存什么、何时提交、从哪里恢复 |
| SQLite CRUD、检索底层实现 | Memory 写入、作用域、召回、冲突、遗忘策略 |
| token 估算器、摘要所需的一次模型调用 | Context 选择与排序、预算分配、Compaction 时机和保留边界 |

PydanticAI direct 继续负责一次模型通信；不使用 `Agent.run()` 托管核心循环。第一版直接复用它的消息类型，不先造通用框架。以后换 SDK 时替换接入层，核心状态和策略仍由你掌握；消息类型迁移仍然需要适配，不能声称零成本切换。

## 核心主线

| 单元 | 手写主题 | 当日闭环 |
| --- | --- | --- |
| [Day 1](day1.md) | Agent 状态、消息与 Loop | 模型提出 read → 执行 → 回传 → 最终回答 |
| [Day 2](day2.md) | 工具调度、Hooks、事件与运行控制 | Hook 可拒绝与处理结果，事件顺序明确，预算和取消能停止 |
| [Day 3](day3.md) | Session 与恢复边界 | 完整消息可保存，重启后从安全位置继续 |
| [Day 4](day4.md) | Memory | 显式记住 → 跨 Session 召回 → 遗忘 |
| [Day 5](day5.md) | Context | 按来源与预算选择本轮输入 |
| [Day 6](day6.md) | Compaction | 压缩旧历史，保留近期完整交互与原始记录 |
| [Day 7](day7.md) | 串联核心生命周期 | 召回、行动、压缩、恢复，并核对 Hook 时序和失败边界 |

```text
Session 原始记录 + Memory + 项目指令
  → Context 选择本轮输入（必要时 Compaction）
  → before_model → 校验输入 → 请求一次 → 校验并保存响应 → after_model
  → 有工具：校验 → before_tool → 执行/拒绝 → after_tool → 保存配对结果
  → turn_end → after_turn → 下一轮或保存终态 → run_end
```

Session 是发生过什么；Memory 是跨任务值得记住什么；Context 是这次实际发给模型什么；Compaction 是怎样缩短旧历史的模型视图。四者不要合成一个不断增长的 messages 列表。

## 主线之后再选修

按依赖推进，不必同时做：

1. 安全 Coding 工具：先审批策略，再接现成 write/edit/bash 实现；副作用默认串行，拒绝也留下对应结果。
2. Session 分支与搜索：parent_id、active leaf、fork、FTS；分支摘要记录来源。
3. 流式显示：复用请求适配层，只在完整响应后执行工具，同一套 Loop 保留全部决策。
4. Worker：复用已完成的 Loop，先单个只读 Worker，再限并发；隔离上下文和工具权限，共享预算与取消，最多一层。
5. Steering/Follow-up、扩展注册与崩溃恢复：在安全边界注入消息，识别不确定的副作用，不自动重放。

Hook 的最小机制与事件生命周期已经在 Day 2；选修只扩展插件加载、工具注册等工程能力。事件排版可直接提供，决策与生命周期顺序由你手写。

SQLite 继续作为计划中的 Session、Memory 统一存储；JSON Lines 仅用于可选事件输出。数据库连接、SQL 拼装和终端排版不单独占学习日，进入对应单元时由配套实现承担。暂不做多 Provider、Web/TUI、向量库、递归 Worker 或 Pi 格式兼容。

## 本地参考与当前状态

Pi 在 `/Users/jquery/python_files/pi`，只读参考。每天最多追一条相关调用链，不要求通读源码。Memory 是 Zeta 的学习设计，不假定 Pi 存在同名长期记忆模块。

当前 `src/zeta/app.py` 已有单次请求和文本流，`tools.py` 已有 read 和分派；CLI 仍接单次文本流，不能当成已完成工具 Loop。model_io.py 已提供完整响应的单次请求适配。Loop、Hooks、Session、Memory、Context、Compaction 是待手写目标；README 和 target.md 采用相同分工。

## 验收约定

每个单元检查一次实际状态变化，不以“回答看起来正确”代替工具或持久化证据。未观察到的分支标记未验证。
完成源码修改后按相关范围运行项目已有 Ruff、Pyright 和 build；通用命令见 [support.md](support.md#完成源码练习后的检查)。文档更新不代表这些功能已实现或真实模型调用通过。
不新增或修改测试、用例、mock、fixture、snapshot、内联自测。真实模型验收使用本地密钥，不写入文档和日志；不自动 commit/push。
