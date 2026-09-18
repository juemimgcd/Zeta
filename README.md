# Zeta

Zeta 是一个使用 Python 构建的本地 Coding Agent，围绕模型请求、工具调用与会话状态，逐步实现可理解、可控制的 Agent 核心。
项目聚焦本地 CLI、工具执行与运行时状态管理，持续完善从用户输入到模型响应的执行流程。

## 当前实现方向

- 只接入 DeepSeek，先完成本地 CLI 的核心闭环。
- 自己实现 Agent loop、消息历史与事件、Hooks、工具调度和结果回传、运行上限与取消。
- 逐步实现工具权限与审批、Session 持久化与恢复、Memory、Context、Compaction 和有边界的 Multi-Agent 委派。
- 不使用 PydanticAI 等 Agent 框架承载上述核心逻辑。
- 单次模型请求使用 PydanticAI direct API；可以复用 Pydantic 参数校验和 Python 标准库；手写 Agent 功能不要求重写 HTTP 客户端、校验库或数据库。
- 不为未来需求提前建设通用 Provider、插件系统或框架抽象。

待手写的第一条 Agent 闭环：

```text
用户输入 → 请求 DeepSeek → 收到 read 工具调用
        → 校验并读取工作区文件 → 回传工具结果 → 模型最终回答
```

## 当前可运行功能

- CLI 的 help/version、单次 DeepSeek 文本流、配置与请求错误显示。
- app.py 提供单次文本请求；model_io.py 提供保留完整响应、携带 read 定义的 request_once，供后续 Loop 使用。
- tools.py 提供工作区内的 UTF-8 read、参数校验与配对结果构造；当前 CLI 尚未接入工具循环。
- events.py 提供 JSON 事件编码；当前 CLI 尚未接入 JSON 事件模式。

安装与使用：

```zsh
uv sync --locked
uv run zeta --help
uv run zeta --version
```

真实请求需在环境或本地 .env 中配置 DEEPSEEK_API_KEY，然后运行 `uv run zeta -p "介绍一下你自己"`。密钥不提交到 Git。

## 核心学习路线

先读 [Day 1 前置知识](days/prerequisites.md)，从对象、消息片段、工具调用配对和异步语法开始。
[days/summary.md](days/summary.md) 为八个学习单元：状态与 Loop、工具调度与 Hooks/事件、Session、Memory、Context、Compaction、完整串联、Manager/Worker 多 Agent 编排。
[days/support.md](days/support.md) 集中提供基础接入；[target.md](target.md) 定义目标与职责边界。

Loop、Hooks、Session、Memory、Context 和 Compaction 仍待手写，不能把文档草图当作已实现功能。PydanticAI 只承担单次模型通信，不使用 Agent.run() 托管循环。

## 开发检查

```zsh
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright --pythonpath .venv/bin/python
uv build
```
