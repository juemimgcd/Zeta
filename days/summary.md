# Zeta 累积式学习路线：写一次，持续复用

更新：2026-09-16。基于 GitHub 9359d5f 原版，使用 LangChain 接入，并同步当前工具注册与单次请求接口。八个单元共享同一套代码。每个文件只有一个所属单元；后一天只增加新文件，不替换前一天已经写好的实现。

## 使用规则

第一次接触 LangChain 时，先读 [Day 1 前置知识：从 Python 对象到一次完整的工具调用](prerequisites.md)。其中具体解释消息与片段、调用编号、工具结果、异步语法，以及 Day 1 三个核心函数；这是一篇阅读材料，不增加新的实现任务。

1. 先准备 [固定基础代码](support.md)：app.py、Runtime 接入契约、配置、模型请求、CLI、SQLite 直接提供。
2. 每天复制当天的完整骨架：导包、异常类、数据属性和初始化都已给出，只填标记的核心函数体。
3. 写完后展开当天完整答案核对。已有正确实现保留；不要为了跟上下一天而整文件覆盖它。
4. Day 1 的 run_loop 是唯一循环。Day 2/3 增加各自接入层，Day 7 组装，Day 8 复用；不再出现多个 run_agent 版本。

“天”是学习单元，完成并验收后再继续。基础实现选择可以简化，但已写函数的契约不会被后续课程推翻。

## 类、属性与函数的阅读入口

Day 1–8 的练习骨架前均有对象/函数说明：类的职责、字段含义、函数输入和返回值；没有新类的 Day 6 则说明复用类型和摘要回调。骨架与参考答案共用这份说明，原有练习顺序保留。

公共对象先查 [support.md](support.md#先认识基础代码中的类与函数)，Python 语法查 [prerequisites.md](prerequisites.md)。Day 2 的 callback、context、invoke 修改和决策规则有 [具体示例与分支讲解](hooks-explained.md#9-invoke-的实际回调与逐分支解释)。这些解释描述教学答案，不表示 src 中的练习已经完成。

## 八天主线与文件归属

| 单元 | 今天手写什么 | 今天新增文件 | 复用的已有内容 |
| --- | --- | --- | --- |
| [Day 1](day1.md) | 状态/协议校验、唯一 run_loop | loop_common.py、loop.py | 固定入口、Runtime、模型/read 基础代码 |
| [Day 2](day2.md) | Hooks、事件、异步工具调度 | hooks.py、lifecycle.py、dispatch.py、hook_runtime.py | Day 1 循环原样保留；接入层直接提供 |
| [Day 3](day3.md) | Session 提交与安全恢复 | session.py、session_runtime.py | Day 1/2 原样保留；接入层直接提供 |
| [Day 4](day4.md) | remember/recall/forget | memory.py | 现有 Session 与 SQLite |
| [Day 5](day5.md) | Context 选择、来源和预算 | context.py | 原始历史与 Memory |
| [Day 6](day6.md) | 压缩边界、候选摘要 | compaction.py | Context 类型、无工具摘要请求 |
| [Day 7](day7.md) | ContextRuntime 的组装和重试策略 | integration.py | 前六天全部实现；不新增循环 |
| [Day 8](day8.md) | Manager/Worker 编排与共享预算 | team_budget.py、orchestration.py | 同一个 run_session_task 和 run_loop |

文件归属与完整基础代码详见 [support.md](support.md#文件所有权)。runtime_base.py 的默认行为真实可用，后续扩展只添加行为，不让你先补未来模块的空实现。

## 始终相同的执行链

```text
固定 app.run_agent 或 integration.run_session_task
  → Day 1 run_loop
      → runtime.prepare：默认历史 / Hook / Context + Memory + Compaction
      → ModelIO.request：默认 request_once → ainvoke，返回完整 AIMessage
      → runtime.on_response：内存 / Session 提交 + Hook
      → runtime.execute：基础执行 / Day 2 调度，复用 resolve_tool_call、handler、make_tool_message
      → runtime.on_result + after_turn：配对、保存、事件、停止决策
      → 继续或准确终态
```

Runtime、HookRuntime、SessionRuntime、ContextRuntime 各自负责新增的一层行为；新方法通过已有方法完成原来的职责，不能把前一层源码复制进新文件。共享循环负责请求/工具预算和取消，策略层决定输入、提交和允许的重试。

工具采用普通函数，在 `tools.py` 的 `TOOLS` 中显式维护“工具名 →（参数模型，执行函数）”；函数文档字符串提供描述，具体 read 在 `builtin_tools/read.py`。模型请求统一使用 `request_once`，默认取全部已注册工具，摘要等无工具用途显式传空序列。完整参数约定见 [基础代码](support.md#模型请求中的工具参数)。

## Manager / Worker

Day 8：Manager 生成结构化任务 → 多个隔离 Worker 限并发运行 → 收集证据和失败 → Manager 汇总。每个 Worker 有独立 Session、Memory scope 和只读路径权限，不继承父完整历史，也不能递归委派。

共享预算覆盖 Manager、Worker、摘要和重试；父取消向下传播。Services 首次定义时就有 request/summarizer 字段，Day 8 只传实现，不修改 Day 7。此模式不声称复刻 Codex 内部实现，也不把多 Agent 称作 Pi 默认内置能力。

## 学习重点与边界

LangChain ChatOpenAI.ainvoke 只负责单次模型通信；Loop、Hooks、工具调度、Session、Memory、Context、Compaction、编排由 Zeta 掌握。不使用 LangChain create_agent / AgentExecutor 或 LangGraph 托管核心循环。

Session 是原始事实；Memory 是跨任务记录；Context 是本轮视图；Compaction 缩短视图但保留原始历史。工具调用/result 必须完整配对；权限拒绝不执行；恢复不自动重放不确定副作用。

主线之后再做审批后的 write/edit/bash、Session 树与分支搜索、流式显示、Steering/Follow-up、任务 DAG 与受控返工、插件加载和恢复调度。不提前引入多 Provider、Web/TUI、向量库、递归 Worker、分布式执行或 Pi 文件格式兼容。

Pi 源码只读参考位于 ../pi。Memory 与编排是 Zeta 的设计方向，不假定 Pi 有一一对应的完整模块。

## 当前状态与验证

本路线与答案在 days 中，不能视为 src 已经实现。你已有的 app.py、loop_common.py、storage.py 等练习文件保留；本次不覆盖或迁移它们。若已写某个函数，先保留自己的实现再对照新归属，不删除已完成逻辑。

按天检查骨架、完整答案与累积依赖，核对前一天文件未被后一天替换。静态检查不能代替真实模型、并发、取消、恢复和长会话验收；未观察到的分支标记未验证。不新增或修改测试、mock、fixture、snapshot 或内联自测，不自动 commit/push。
