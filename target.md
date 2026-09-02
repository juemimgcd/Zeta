# Zeta：Pi 的 Python 重写目标与实施计划

> 状态：架构基线 1.0  
> 日期：2026-09-02  
> 目标目录：`/Users/jquery/python_files/Zeta`

## 1. 项目目标

Zeta 是一个使用 Python 独立实现的本地 Coding Agent。它参考 Pi 的核心行为和交互方式，但不逐文件翻译 TypeScript，也不在首版兼容 Pi 的内部插件、远程协议或会话文件。

首个可用版本必须完成一条真实闭环：

```text
用户输入
  -> 模型流式响应
  -> 模型请求工具
  -> 参数验证与权限确认
  -> 工具执行
  -> 工具结果回传模型
  -> 最终回答
  -> 会话持久化
```

Zeta 的核心价值是掌握 Agent loop、工具执行、消息规范化、会话恢复和终端交互。不得使用会接管这些核心能力的 Agent 框架来代替实现。

## 2. Python 版本决策

### 2.1 正式选择

- 语言基线：**CPython 3.14**。
- 本地开发版本：`.python-version` 固定为 `3.14`，由 uv 解析当前最新的 3.14.x 补丁版本。
- 包声明：`requires-python = ">=3.14,<3.15"`。
- 解释器形态：首版使用普通 GIL 构建，不使用 free-threaded 构建。

截至 2026-09-02：

- Python 3.14 是最新稳定 feature release，处于 bugfix 支持期。
- Python 3.15 仍是预发布版本，不作为项目基线。
- 当前可由 uv 安装的稳定版本为 CPython 3.14.7（macOS Apple Silicon）。

官方依据：

- [Python 版本状态](https://devguide.python.org/versions/)
- [Python 3.14 发布说明](https://www.python.org/downloads/release/python-3144/)

### 2.2 为什么不继续使用 3.12

Zeta 是全新项目，没有旧环境兼容负担。选择 3.14 可以直接使用当前语言和标准库能力，并获得更长的上游支持周期。Pydantic 当前项目元数据也已列出 Python 3.14 支持。

### 2.3 为什么不选 3.15 RC

Agent CLI 依赖终端 UI、模型 SDK、网络库和 Pydantic。使用预发布解释器会把依赖兼容问题混入 Zeta 自身问题，降低排查效率。Python 3.15 正式发布并且所有直接依赖通过兼容验证后，再单独升级。

### 2.4 为什么首版不用 free-threaded Python

Zeta 的主要负载是网络流式传输和子进程 I/O，`asyncio` 已能覆盖。free-threaded 构建会扩大第三方二进制依赖的兼容面，却不会直接改善首版的主要瓶颈。只有性能数据证明 CPU 并行受 GIL 限制时再评估。

## 3. 重写边界

### 3.1 首版必须具备

- `zeta` 交互式终端模式。
- `zeta -p "..."` 单次文本模式。
- `zeta --mode json -p "..."` JSON 事件流模式。
- OpenAI Responses API Provider。
- Anthropic Provider，用于验证 Provider 抽象。
- 统一的消息、内容块、工具调用、工具结果和 usage 模型。
- 流式文本、思考块和工具调用事件。
- `read`、`write`、`edit`、`bash` 四个内置工具。
- 工具参数验证、路径边界、命令确认、超时、取消和输出截断。
- `AGENTS.md` 上下文发现与加载。
- JSONL 会话保存和继续。
- 模型切换、基础配置和错误展示。
- Textual 终端 UI。

### 3.2 首版明确不做

- 不支持 Pi 的全部模型 Provider。
- 不兼容 Pi 的 TypeScript extensions。
- 不兼容 Pi 的 JSONL session 格式。
- 不实现 RPC、Client、Server 或 CBOR 远程协议。
- 不实现 SQLite session backend。
- 不实现遥测平台或 exporter。
- 不自动刷新远端模型目录。
- 不做 session tree、lane、fork、branch summary。
- 不做工具并行执行。
- 不做 Web UI。
- 不拆成 Python monorepo。
- 不实现自有终端底层渲染器。
- 不使用 LangChain、LangGraph、CrewAI、PydanticAI 或 LiteLLM 代理 Agent loop。

## 4. 技术栈定案

| 领域 | 选择 | 决策说明 |
| --- | --- | --- |
| Python | CPython 3.14 | 使用稳定版，不追 3.15 预发布版 |
| 项目与环境 | uv | 管理解释器、虚拟环境、依赖和锁文件 |
| 构建后端 | `uv_build` | 满足 src layout、wheel 和 CLI 发布 |
| CLI 参数 | 标准库 `argparse` | 命令规模不足以引入 Typer/Click |
| 异步运行时 | 标准库 `asyncio` | 统一模型流、工具、取消和 UI 后台任务 |
| 边界校验 | Pydantic 2 | 校验 Provider 数据、工具参数、配置和持久化记录 |
| TUI | Textual | 提供组件、事件、焦点、快捷键、滚动和异步 worker |
| OpenAI | 官方 `openai` SDK | 使用异步 Responses API 和流式事件 |
| Anthropic | 官方 `anthropic` SDK | 第二个 Provider 实现 |
| 会话存储 | 标准库 JSONL | 追加写、可审计、可恢复 |
| 配置读取 | `tomllib` + JSON | TOML 读取无需依赖；用户状态采用 JSON |
| 日志 | 标准库 `logging` | 首版不引入 structlog |
| 格式与 lint | Ruff | 单工具覆盖格式和静态规则 |
| 类型检查 | Pyright | 严格检查公共边界和异步接口 |
| 测试候选 | pytest + pytest-asyncio | 仅锁定选择；未获明确授权前不创建测试文件 |

依赖版本策略：

- `pyproject.toml` 对直接依赖使用兼容的 major 范围。
- `uv.lock` 固定实际安装版本，并提交到 Git。
- 不依赖未声明的传递依赖。
- 不为了一个小工具函数添加新包。
- Provider SDK 只处理厂商协议，不允许接管 Agent loop。

参考资料：

- [uv 项目管理](https://docs.astral.sh/uv/guides/projects/)
- [Textual App 与异步事件](https://textual.textualize.io/guide/app/)
- [Textual Widgets](https://textual.textualize.io/guide/widgets/)
- [OpenAI Python SDK](https://github.com/openai/openai-python)
- [Pydantic 项目元数据](https://github.com/pydantic/pydantic/blob/main/pyproject.toml)

## 5. 总体架构

```text
┌─────────────────────────────────────────────┐
│ CLI / Textual UI / JSON Output              │
└──────────────────────┬──────────────────────┘
                       │ 用户输入与 UI 命令
                       ▼
┌─────────────────────────────────────────────┐
│ AgentEngine                                 │
│ - 上下文组装                                │
│ - Agent loop                                │
│ - 事件发布                                  │
│ - 停止、取消与错误语义                      │
└──────────────┬──────────────────┬───────────┘
               │                  │
               ▼                  ▼
┌──────────────────────┐  ┌───────────────────┐
│ Provider             │  │ ToolRegistry      │
│ OpenAI / Anthropic   │  │ read/write/edit   │
│ 厂商协议规范化       │  │ bash + policy     │
└──────────────────────┘  └───────────────────┘
               │                  │
               └─────────┬────────┘
                         ▼
                ┌────────────────┐
                │ SessionStore   │
                │ JSONL append   │
                └────────────────┘
```

依赖方向固定为：

```text
UI/CLI -> Application -> Agent domain <- Provider/Tool/Session adapters
```

限制：

- UI 不直接调用模型 SDK。
- Provider 不执行工具、不写 session。
- Tool 不操作 UI、不调用 Provider。
- SessionStore 不理解 Textual 或厂商 API。
- AgentEngine 只依赖小型 Protocol，不依赖具体 Provider 类。

这不是完整 Clean Architecture 分层。Zeta 只保留有两个以上真实实现或需要隔离外部系统的边界。

## 6. 目标目录结构

```text
Zeta/
├── pyproject.toml
├── uv.lock
├── .python-version
├── README.md
├── LICENSE
├── AGENTS.md
├── target.md
└── src/
    └── zeta/
        ├── __init__.py
        ├── cli.py
        ├── app.py
        ├── config.py
        ├── events.py
        ├── messages.py
        │
        ├── agent/
        │   ├── engine.py
        │   └── context.py
        │
        ├── providers/
        │   ├── base.py
        │   ├── openai.py
        │   └── anthropic.py
        │
        ├── tools/
        │   ├── base.py
        │   ├── registry.py
        │   ├── read.py
        │   ├── write.py
        │   ├── edit.py
        │   └── bash.py
        │
        ├── sessions/
        │   ├── models.py
        │   └── jsonl.py
        │
        ├── context/
        │   └── loader.py
        │
        └── ui/
            ├── app.py
            ├── transcript.py
            └── composer.py
```

约束：

- 不创建泛化的 `utils/`、`helpers/`、`services/`、`managers/` 目录。
- 单次使用的小函数留在调用模块。
- 只有模块确实过大或具有独立责任时才拆文件。
- 不提前创建空目录或占位类；上面的结构按阶段逐步出现。

## 7. 核心数据契约

### 7.1 内容块

统一支持以下判别联合：

- `TextBlock`
- `ThinkingBlock`
- `ImageBlock`（类型先保留，图片输入后置）
- `ToolCallBlock`

### 7.2 消息

- `UserMessage`
- `AssistantMessage`
- `ToolResultMessage`

`AssistantMessage` 必须记录：

- provider
- model
- content blocks
- stop reason
- usage
- timestamp
- 可选错误信息

终止原因统一为：

- `stop`
- `tool_use`
- `length`
- `error`
- `cancelled`

### 7.3 Provider 事件

Provider 将厂商事件转换为：

- `response_started`
- `text_delta`
- `thinking_delta`
- `tool_call_delta`
- `response_completed`
- `response_failed`

UI、JSON 输出和 AgentEngine 只能消费统一事件，不读取厂商 SDK 对象。

## 8. 核心接口

### 8.1 Provider

```python
class Provider(Protocol):
    async def stream(
        self,
        request: ModelRequest,
    ) -> AsyncIterator[ModelEvent]: ...
```

Provider 负责：

- Zeta 消息到厂商请求的转换。
- 厂商流式事件到 Zeta 事件的转换。
- tool call 增量参数的累积。
- usage、停止原因和错误的规范化。
- 超时、取消和可重试错误分类。

Provider 不负责：

- 工具执行。
- 权限确认。
- 会话保存。
- UI 更新。

### 8.2 Tool

```python
class Tool(Protocol):
    name: str
    input_model: type[BaseModel]

    async def execute(
        self,
        arguments: BaseModel,
        context: ToolContext,
    ) -> ToolResult: ...
```

首版工具：

- `read`：读取文本或受支持图片，具备行数和字节限制。
- `write`：创建或完整覆盖文件，写入前执行权限检查。
- `edit`：使用唯一精确文本匹配替换；零匹配或多匹配时失败。
- `bash`：使用当前平台 shell 执行命令，支持 cwd、timeout、cancel 和流式输出。

首版不实现独立 `grep`、`find`、`ls` 工具；模型可通过 `bash` 调用系统已有命令。只有专用工具能证明改善安全或模型稳定性时再添加。

### 8.3 AgentEngine

```python
class AgentEngine:
    async def run(self, prompt: UserMessage) -> AsyncIterator[AgentEvent]: ...
```

行为规则：

1. 将用户消息保存并加入上下文。
2. 调用 Provider 并逐个发布规范化事件。
3. 完整组装 assistant message 后才允许处理工具调用。
4. 工具调用参数必须经过对应 Pydantic model 校验。
5. 被 token limit 截断的工具参数不得执行。
6. 工具调用首版按模型给出的顺序串行执行。
7. 每个工具结果立即写入 session，再进入下一次模型调用。
8. 无工具调用、全部终止、错误或取消时结束。
9. Ctrl+C 首次取消当前 operation，连续触发才退出应用。

## 9. 工具执行与安全策略

### 9.1 默认权限

| 行为 | 默认策略 |
| --- | --- |
| 读取工作区文件 | 允许 |
| 写入或编辑工作区文件 | 询问 |
| 执行 shell 命令 | 询问 |
| 访问工作区外路径 | 拒绝 |
| 删除、覆盖大量文件等高风险行为 | 始终单独询问 |

CLI 提供：

```text
--approval ask|never|always
--allow-path PATH
```

默认值是 `--approval ask`。`always` 必须由用户在本次启动中显式传入，项目配置不得静默开启。

### 9.2 路径处理

- 使用 `pathlib.Path.resolve()` 得到规范路径。
- 默认允许当前工作区及其子路径。
- 额外路径必须由 `--allow-path` 声明。
- 符号链接解析后的目标仍需重新检查边界。
- 文件名大小写按真实文件系统处理，不依赖 macOS 大小写不敏感特性。

### 9.3 Bash

- macOS 默认使用用户 shell，预期为 zsh。
- 使用 `asyncio.create_subprocess_exec()` 启动明确的 shell 和参数。
- stdout/stderr 流式读取并设置最大内存保留量。
- 超量输出写入临时文件，并在结果中返回路径。
- timeout 和用户取消必须终止整个子进程组，不能只结束父 shell。
- 返回 command、exit code、cancelled、timed_out、truncated 和 output。

### 9.4 文件写入

- `write` 先写同目录临时文件，再使用 `os.replace()` 原子替换。
- `edit` 只接受唯一精确匹配，避免模糊替换错误文件位置。
- 文件修改工具在同一 session 内串行执行。
- 不自动提交、push、删除或安装系统软件。

## 10. 会话与配置

### 10.1 存储位置

```text
~/.zeta/
└── agent/
    ├── settings.json
    ├── models.json
    └── sessions/
        └── <cwd-hash>/
            └── <timestamp>_<uuid>.jsonl
```

API key 首版只从环境变量读取，不写入上述目录：

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`

OAuth 和 macOS Keychain 支持后置。

### 10.2 JSONL v1

```json
{"type":"session","version":1,"id":"...","cwd":"...","created_at":"..."}
{"type":"message","id":"...","role":"user","content":[...]}
{"type":"message","id":"...","role":"assistant","content":[...]}
{"type":"message","id":"...","role":"tool","tool_call_id":"...","content":[...]}
```

规则：

- append-only。
- 每条记录独占一行。
- 每次 append 后 flush；关键边界执行 fsync。
- 同一个 session 只允许一个写者；macOS/Linux 首版使用 `fcntl.flock`。
- 文件尾部出现半条 JSON 时，恢复完整记录并报告诊断，不静默篡改原文件。
- schema version 只通过显式 migration 升级。

## 11. 上下文加载

首版加载顺序：

1. Zeta 内置 system prompt。
2. 从文件系统根到当前工作目录沿途发现的 `AGENTS.md`。
3. 当前用户消息。

规则：

- 更接近当前目录的 `AGENTS.md` 优先级更高。
- 保存来源路径，便于 `/context` 展示。
- 限制单文件和总上下文大小。
- 首版不加载项目 Python 扩展，因此不建立伪 sandbox。
- 文档中的提示注入风险通过来源展示和工具审批缓解，而不是宣称已经消除。

## 12. Textual UI

### 12.1 组成

- `Transcript`：用户消息、模型流式文本、thinking、工具调用和错误。
- `Composer`：多行输入、提交和历史输入。
- `StatusBar`：cwd、provider、model、thinking level、token usage。
- Modal：模型选择、权限确认、session 恢复。

### 12.2 状态要求

每个异步动作必须具备：

- loading 状态。
- 空状态。
- error 状态。
- cancelled 状态。

每个交互元素必须具备：

- focus 状态。
- disabled 状态。
- 键盘操作路径。

### 12.3 UI 与内核通信

- AgentEngine 发布 `AgentEvent`。
- UI 后台 worker 消费事件并更新 widget。
- UI 通过 command 对象提交用户动作。
- UI 不导入 OpenAI 或 Anthropic SDK。
- print/json mode 复用相同事件，不复用 Textual widget。

## 13. CLI 目标

首版命令表面：

```text
zeta
zeta -p PROMPT
zeta --mode text|json
zeta --provider openai|anthropic
zeta --model MODEL
zeta --resume [SESSION_ID]
zeta --approval ask|never|always
zeta --allow-path PATH
zeta --version
zeta --help
```

交互命令：

```text
/new
/resume
/session
/name
/model
/context
/clear
/quit
```

skills、prompts、fork、tree、compact、export 和 package commands 后置。

## 14. 实施阶段

### Phase 0：工程基线

交付：

- `pyproject.toml`
- `.python-version`
- `uv.lock`
- `src/zeta`
- `zeta --version`
- Ruff/Pyright 配置

完成标准：

- uv 使用 CPython 3.14.x 创建环境。
- 所有直接依赖能在 macOS Apple Silicon 上解析和导入。
- `uv run zeta --version` 正常退出。
- Git 工作区不包含 `.venv` 或密钥文件。

### Phase 1：Headless Agent 闭环

交付：

- 统一消息和事件契约。
- OpenAI Provider。
- AgentEngine。
- `read` 工具。
- text/json 输出模式。
- 取消和基础错误处理。

完成标准：

```zsh
uv run zeta -p "读取 README.md 并用一句话概括"
```

能够完成至少一次真实的“模型 -> 工具 -> 模型 -> 最终答案”闭环，并且 JSON 模式产生可逐行解析的事件。

### Phase 2：Coding tools 与权限

交付：

- `write`、`edit`、`bash`。
- ApprovalPolicy。
- 工作区路径限制。
- timeout、cancel、输出截断和临时完整输出。
- `AGENTS.md` 加载。

完成标准：

- 未确认时不得执行写入或 shell。
- 工作区外路径默认拒绝。
- 取消 shell 后不遗留子进程。
- edit 零匹配和多匹配均不修改文件。

### Phase 3：Session 与配置

交付：

- JSONL SessionStore。
- `/new`、`/resume`、`/session`、`/name`。
- settings 和模型选择。
- usage 汇总。

完成标准：

- 正常退出和异常中断后均能恢复最后一个完整消息边界。
- session 不保存环境变量中的 API key。
- 两个进程不能同时写同一 session。

### Phase 4：Textual TUI

交付：

- transcript、composer、status bar。
- 流式 Markdown。
- 工具执行状态。
- 权限确认 modal。
- 模型和 session selector。
- Ctrl+C 取消与退出语义。

完成标准：

- 流式响应期间 UI 保持可交互。
- 终端缩放后布局可继续使用。
- loading、empty、error、cancelled 状态可区分。
- print/json mode 不依赖 Textual 启动。

### Phase 5：第二 Provider 与长会话

交付：

- Anthropic Provider。
- Provider/model 切换。
- retry/backoff 分类。
- context window 和 compaction。

完成标准：

- OpenAI 与 Anthropic 通过同一个 AgentEngine 执行相同工具协议。
- 厂商错误不泄漏为未分类异常。
- compaction 前后的关键用户约束可追踪。

### Phase 6：按需扩展

候选项：

- skills。
- prompt templates。
- 基于 `importlib.metadata.entry_points()` 的 Python 插件。
- 图片输入。
- OAuth 和系统 Keychain。
- session branching。
- RPC/server。
- 容器或 VM 工具执行后端。

这些项目没有默认排期。只有出现真实使用需求时才进入实施。

## 15. 验证策略

本文件只确定验证方式，不授权创建、修改或扩展测试文件。

每个阶段至少验证：

- Ruff format/check。
- Pyright。
- CLI smoke。
- 对应阶段的真实纵向闭环。
- Git 状态和密钥扫描。

涉及非平凡 Agent loop、解析、权限或持久化逻辑时，应补最小自动化验证；开始创建测试前需取得用户对测试改动的明确授权。

## 16. 与 Pi 的对应关系

Pi 的关键源码证据：

| 能力 | Pi 位置 | Zeta 目标位置 |
| --- | --- | --- |
| Agent loop | `../pi/packages/agent/src/agent-loop.ts` | `src/zeta/agent/engine.py` |
| Agent 消息 | `../pi/packages/agent/src/types.ts` | `src/zeta/messages.py` |
| Provider 统一层 | `../pi/packages/ai/src/` | `src/zeta/providers/` |
| CLI 组合入口 | `../pi/packages/coding-agent/src/main.ts` | `src/zeta/cli.py`、`app.py` |
| Coding tools | `../pi/packages/coding-agent/src/core/tools/` | `src/zeta/tools/` |
| Session | `../pi/packages/coding-agent/src/core/session-manager.ts` | `src/zeta/sessions/` |
| TUI | `../pi/packages/tui/src/` | `src/zeta/ui/` |
| 安全说明 | `../pi/packages/coding-agent/docs/security.md` | ApprovalPolicy 与路径边界 |

重写时先提取行为契约，再用 Python 实现。不得为了保持文件数量或类名一致而复制 Pi 的历史结构。

## 17. 许可证策略

Pi 使用 MIT License，原始版权声明为：

```text
Copyright (c) 2025 Mario Zechner
```

如果 Zeta 翻译、复制或实质改编 Pi 代码，必须在 Zeta 的许可证或第三方声明中保留原 MIT 版权与许可文本。

计划默认：

- Zeta 使用 MIT License。
- README 明确写明 Zeta 是受 Pi 启发的独立 Python 实现。
- 保存 Pi 的仓库链接。
- 不宣称 Zeta 是 Pi 官方移植版。
- 任何直接移植的代码在提交时单独标注来源。

## 18. 架构守则

1. 先完成纵向闭环，再扩展 Provider 和 UI。
2. 不以“以后可能需要”为由创建抽象。
3. 同一能力只允许一个事实来源。
4. 错误、取消和持久化不是后补功能。
5. 外部输入全部在边界验证。
6. 安全确认不能被模型或项目文件静默关闭。
7. UI 是事件消费者，不是业务内核。
8. Provider 只做协议转换，不拥有 Agent loop。
9. 默认串行工具执行；并行必须有冲突模型和收益证据。
10. 首版优化可读性和可恢复性，不追求与 Pi 的功能数量对齐。

## 19. 下一步

下一次实施只执行 Phase 0：创建最小可运行工程、锁定 CPython 3.14.x、解析依赖并让 `uv run zeta --version` 成功。

不在 Phase 0 提前创建所有计划目录，不实现 Provider，不创建测试文件，不安装全局包，不提交或推送 Git。
