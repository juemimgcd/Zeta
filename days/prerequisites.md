# Day 1 前置知识：从 Python 对象到一次完整的工具调用

[学习总览](summary.md) · [Day 1 练习](day1.md) · [固定基础代码](support.md)

本篇保留 GitHub `9359d5f` 原版的阅读顺序：对象与消息 → 工具配对 → Runtime 与异步 → Day 1 三个函数逐段解释。只将 PydanticAI 的类型、字段和调用方式换成 LangChain，不另设一套简化课程。

接口已在临时环境中核对：`langchain-openai==1.6.2`、`langchain-core==1.6.2`。项目现有源码尚未因此迁移；示例中的 ID、正文和回答是结构示意，不是真实模型运行记录，不需要另建测试。

先回答最容易混淆的三个问题：

- `response` 是 LangChain 的 `AIMessage` 对象；文字看 `content` / `text`，调用看 `tool_calls`。
- `response.tool_calls` 是列表，每项 `ToolCall` 在运行时是字典，用 `call["name"]`、`call["args"]`、`call["id"]` 读取。
- `ToolMessage` 是一条独立的工具结果消息。它带回调用 ID，直接加入历史，不再放进 ModelRequest 的 parts 中。

建议分三遍读：第 1–8 节认识数据；第 9–13 节看请求、Runtime 和异步；第 14–20 节对照 Day 1 的代码。已有函数不要为了对照答案整文件覆盖。

## 阅读方式：先认对象，再读执行过程

各天文档的代码前已补上“类是什么、属性是什么意思、函数接收什么并返回什么”的对照表。公共的消息类、ModelIO、Runtime、RunOptions、ToolExecution、ReadArgs、JsonStore 统一见 [基础代码对象说明](support.md#先认识基础代码中的类与函数)，各天新增的类在当天说明。

看到 `class` 时，先分清它保存数据、管理行为，还是表示异常；看到 `self.xxx` 时，它是当前实例的属性；函数体中的普通变量通常只在这次调用中使用。`type X = ...` 是类型别名，不代表创建了一个新类。`@property` 定义的计算属性读作 `obj.value`；一般方法写作 `obj.method(...)`。

函数要连着三件事读：谁传入参数，函数内做什么，谁使用返回值。尤其是回调：`check_path` 是函数对象，注册只保存它；`check_path(context)` 得到协程对象，`await check_path(context)` 才取得 return 的数据。具体例子见 [Hook 讲解](hooks-explained.md#9-invoke-的实际回调与逐分支解释)。

## 1. 先分清：哪些是 Python，哪些是包，哪些是我们自己的代码

### 1.1 包、模块和 import

```python
# ruff: noqa: F401  # 仅展示消息类的导入写法。
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
```

从 `langchain_core` 包的 messages 模块导入三个消息类。导入只让当前文件能使用这些名字，不会请求模型或执行工具。安装包名 `langchain-core` 和导入名 `langchain_core` 不同，和 python-dotenv / dotenv 类似。

基础请求使用 `from langchain_openai import ChatOpenAI`。添加 langchain-openai 会带入其需要的 Core 和 SDK 依赖；我们不使用 LangChain 的 create_agent 来运行循环。

### 1.2 Day 1 的几类来源

| 来源 | 例子 | 职责 |
| --- | --- | --- |
| Python 标准库 | asyncio、logging、pathlib、dataclasses、typing、copy | 异步、日志、文件、类型与复制 |
| Pydantic | BaseModel、Field、ValidationError | ReadArgs 和业务记录的校验，仍然保留 |
| LangChain Core | BaseMessage、AIMessage、ToolMessage、ToolCall | 消息结构、工具调用结构 |
| LangChain OpenAI 兼容接口 | ChatOpenAI | 一次模型通信 |
| 底层模型 SDK | APIStatusError、APIError | HTTP 和连接错误 |
| Zeta | Runtime、response_calls、validate_history、run_loop | 循环、配对、工具执行和停止决策 |

Pydantic 与 PydanticAI 是不同依赖。此次替换 PydanticAI，保留 Pydantic 参数校验。`ModelResponseError` 是 Zeta 在 loop_common.py 提前提供的异常类，用于拒绝不完整响应。

## 2. 读这些代码需要的最小 Python 语法

### 2.1 类、对象、属性、字典键分别是什么

```python
from langchain_core.messages import AIMessage, ToolCall

call: ToolCall = {"name": "read", "args": {"path": "README.md"}, "id": "call_001"}
response = AIMessage(
    content="先读取文件。",
    tool_calls=[call],
    response_metadata={"finish_reason": "tool_calls"},
)
```

`AIMessage` 是类，`response` 是它的实例。`response.tool_calls` 是对象属性；`call` 则是字典，`call["name"]` 读取字典键。这两种访问方式不能混用。

ToolCall 是 TypedDict 类型约定，不是一个带 tool_name、args_as_dict 方法的框架对象。不要用 isinstance(call, ToolCall) 做运行时检查；参数正确性仍由 ReadArgs 校验，完整响应由 response_calls 检查。

`AIMessage(...)` 创建消息对象，不执行 read。`response.text` 是属性，返回文字，不写 response.text()。本课程只接收普通字符串 content，多模态内容块留待后续扩展。

### 2.2 字符串、列表、字典和 None

| 写法 | 类型/作用 |
| --- | --- |
| `"read"` | 字符串 `str`，是一段文本 |
| `[a, b]` | 列表 `list`，按顺序保存两个元素 |
| `{"path": "README.md"}` | 字典 `dict`，通过键 `"path"` 找到值 `"README.md"` |
| `[]`、`{}` | 空列表、空字典 |
| `None` | 表示这里没有值，不是字符串 `"None"` |
| `True`、`False` | 布尔值，表示条件成立或不成立 |

`parts[0]` 取序列的第一个元素；Python 索引从 0 开始。`args["path"]` 则通过字典的键取值。这两种方括号访问不是一回事。

对象属性用点号，例如 `response.tool_calls`。调用字典用键，例如 `call["name"]` 和 `call["args"]["path"]`；后者仍需先通过 ReadArgs 校验。

### 2.3 类型注解不负责自动执行或校验

`response: AIMessage` 表示这个参数应当是 AIMessage；`list[ToolCall]` 表示由调用字典组成的列表。类型提示不会自动发请求，也不保证模型返回值合法，所以仍要写 response_calls 和 validate_history。

`Sequence[BaseMessage]` 表示可以按顺序读取的消息序列；调用者可传列表，函数不要求它提供 append。需要修改自己的历史时，Runtime 使用 list[BaseMessage]。

### 2.4 后面会反复出现的短写法

| 写法 | 意思 |
| --- | --- |
| `isinstance(message, AIMessage)` | 判断是不是模型消息对象 |
| `[call["id"] for call in calls]` | 从每个调用取编号，形成新列表 |
| `any(...)` | 只要有一个条件成立就为真 |
| `len(ids) != len(set(ids))` | 去重前后长度不同，说明有重复 |
| `value or ""` | value 为空或 None 时取空字符串 |
| `raise ValueError(...)` | 抛出异常，中断普通执行路径 |
| `return calls` | 把列表交还给调用方 |

LangChain 的调用 ID 类型允许 None，但 Zeta 的 response_calls 会拒绝空编号。下游 `call["id"] or ""` 是在这项校验之后满足类型检查的写法，不是为缺失编号补造值。

## 3. 模型通信不是“输入一个字符串，输出也只有一个字符串”

一次响应可能是最终文字，也可能包含工具调用。单次 ainvoke 只负责把请求交给服务商并取回 AIMessage。文件读取发生在 Zeta 的 execute_tool，不发生在 bind_tools 或 ainvoke 里。

因此必须保存完整 AIMessage，再保存对应 ToolMessage。只保存 response.text 会丢失调用编号、参数、结束原因和用量信息，下一轮无法正确接续。

## 4. content 与 tool_calls：先看对象里面的层次

### 4.1 先认识常用消息类型

| 类型 | 代表谁的消息 | 主要数据 |
| --- | --- | --- |
| SystemMessage | 可信指令 | content |
| HumanMessage | 用户输入或明确标注的参考资料 | content |
| AIMessage | 模型响应 | content、tool_calls、response_metadata |
| ToolMessage | 一次工具的结果 | content、tool_call_id、name、status |
| BaseMessage | 这些消息的公共父类 | 便于描述混合消息列表 |

ToolCall 不是独立消息。它放在 AIMessage.tool_calls 列表里，描述待执行的调用。

### 4.2 只有文字的响应

```python
from langchain_core.messages import AIMessage

response = AIMessage(
    content="项目目标是实现自己的 Agent 核心。",
    response_metadata={"finish_reason": "stop"},
)
```

此时 response.tool_calls 是空列表；response.text 得到回答文字。

### 4.3 只有工具调用的响应

```python
from langchain_core.messages import AIMessage

response = AIMessage(
    content="",
    tool_calls=[{"name": "read", "args": {"path": "README.md"}, "id": "call_001"}],
    response_metadata={"finish_reason": "tool_calls"},
)
```

空 content 在有合法调用时允许。它只是要求 read，此刻文件尚未读取。

### 4.4 文字和工具调用同时存在

content 可以是“我先检查 README”，tool_calls 同时包含 read 调用。有调用时循环继续执行工具，不把这段过渡文字当最终答案。

### 4.5 为什么先判断类型再读属性

历史是 list[BaseMessage]。AIMessage 才有 tool_calls；ToolMessage 才有 tool_call_id。先用 isinstance 区分消息，再读取相应字段。不要在 HumanMessage 上遍历不存在的 parts，也不要把所有消息都当工具结果。

## 5. tool_call_id：给“这一次调用”配对，不是给工具命名

### 5.1 name 和 id 的区别

两次 read 的 name 都可以是 read，但必须有不同调用 ID。编号来自模型响应，在本地执行器、Hooks、Session 和下一次模型请求中保持不变。

### 5.2 编号从哪里来

LangChain 在 response.tool_calls 中提供 id。Zeta 检查它非空、同批唯一；执行结果沿用这个编号。不能用文件名替换，也不能为错误结果另造一个编号。

### 5.3 正确配对的结果对象

```python
from langchain_core.messages import ToolMessage

result = ToolMessage(
    name="read",
    tool_call_id="call_001",
    content="这里是实际读取到的正文。",
    status="success",
)
```

这里 name 是 Zeta 额外保留的工具名，校验时和 pending 记录一起核对；服务商主要通过 tool_call_id 关联调用与结果。

## 6. ToolMessage 是结果信封，Python return 是语言动作

`ToolMessage(...)` 是构造结果消息；`return result` 是把这个对象交给当前函数的调用者。两者都不等于已经发送给模型。

Day 1 的链条是：read_file 返回正文字符串 → execute_tool 返回 ToolMessage → Runtime.execute 返回 ToolExecution → 循环收集 execution.result → Runtime.after_turn 把这些 ToolMessage 追加到历史 → 下一次请求才发出去。

ToolExecution 是 Zeta 自己的记录，包含 raw 和 result；它不是 LangChain 消息，不直接发送。

## 7. 完整历史：用户提问 → 工具调用 → 工具结果 → 最终回答

### 7.1 第一步：创建用户消息

Runtime.start 将 HumanMessage(content=prompt) 加入 history。固定指令由 Runtime.prepare 放入本轮视图中的 SystemMessage，不在 Session 每条原始记录里重复存一份。

### 7.2 第二步：发出第一次模型请求

循环依次调用 begin_turn、prepare、validate_history，再 await runtime.io.request。prepare 返回 SystemMessage 加历史副本，request_once 附带 read 工具定义，调用 LangChain ainvoke，取得 AIMessage。

### 7.3 第三步：执行本地工具

response_calls 检查响应，on_response 保存整条 AIMessage。执行器检查 ReadArgs、路径和文件大小，返回同编号的 ToolMessage。工具结果在 after_turn 通过 history.extend(results) 加入历史。

### 7.4 第四步：发出第二次模型请求

```text
模型输入视图：
SystemMessage(固定指令)
HumanMessage(用户问题)
AIMessage(tool_calls=[read, id=call_001])
ToolMessage(正文, tool_call_id=call_001)
```

第二次请求才包含文件正文。模型这次给出无调用的完整 AIMessage 时，循环返回 response.text。

### 7.5 一轮有多个调用时

一条 AIMessage 可以要求多个 read，每个调用各有一条 ToolMessage。LangChain 不要求把工具结果重新包进请求消息；按顺序追加独立 ToolMessage 即可，但下次请求前整批必须配齐。

## 8. 完整消息与 finish_reason：怎样判断响应能否使用

### 8.1 LangChain 没有这里可用的 response.state

本课用非流式 ainvoke 取得完整 AIMessage；AIMessageChunk 属于流式片段，明确拒绝执行。invalid_tool_calls 非空说明有无法解析的工具参数，也拒绝整次响应，不能忽略坏调用只执行剩余部分。

### 8.2 finish_reason 在 response_metadata 中

`finish_reason` 是服务商返回的结束原因。本课简化版不要求它与 `tool_calls` 精确匹配，也不因缺少这个字段而拒绝响应。循环直接根据 `response.tool_calls` 决定是否执行工具；没有调用时返回 `response.text`，允许为空。因此，这个校验不保证最终文字完整或非空。

### 8.3 对照你的函数

response_calls 只拒绝流式片段、未解析调用，以及空白或同批重复的调用 ID。工具名和参数由执行器处理。工具状态属于 ToolMessage.status；运行状态属于 Runtime 的 RunStatus，不能相互混用。

## 9. 模型怎么知道有 read：工具说明与真正执行工具的区别

### 9.1 ReadArgs 和 Pydantic 继续保留

ReadArgs 仍继承 BaseModel，path 使用 Field，ConfigDict(extra="forbid", strict=True) 拒绝多余字段与错误类型。换 LangChain 不要求你改写参数校验库。

### 9.2 args 已由 LangChain 解析成字典

`resolve_tool_call(call)` 先按工具名从 `TOOLS` 取出 `args_model, handler`，再调用 `args_model.model_validate(call["args"])`。read 对应的参数模型是 `ReadArgs`。旧版根据字符串/字典选择 model_validate_json 的分支不再需要。解析 JSON 失败的调用会出现在 invalid_tool_calls，先由 response_calls 拒绝。

### 9.3 model_json_schema() 仍是给模型看的结构说明

`TOOLS` 是普通字典：`{"read": (ReadArgs, read_file)}`。`args_model, handler = TOOLS["read"]` 把这一对对象取出来，分别得到参数模型类和执行函数。函数文档字符串提供 description；没有文档字符串时使用工具名。

`tool_schemas()` 从注册表生成给模型的 schema 字典列表，function 中保存 name、description、parameters；parameters 来自 `args_model.model_json_schema()`。对于 read，这就是 `ReadArgs.model_json_schema()`。

model.bind_tools(tool_schemas()) 仅把这些说明附到请求。它没有收到 read_file 的执行结果，也不代替本地 ReadArgs 校验、权限检查和读取。

### 9.4 read_file 中的标准库操作不变

Path.resolve 解析路径与符号链接，is_relative_to 检查工作区，is_file 检查普通文件；open("rb") 按字节读取，超过 32768 字节拒绝，最后用 UTF-8 解码。`read_file` 位于 `builtin_tools/read.py`，完整代码见 support，不在此另写一版。

## 10. ainvoke、request_once 和消息类型分别是什么

### 10.1 模型对象是什么

ChatOpenAI 是 LangChain 的模型客户端。创建对象和 bind_tools 都不是执行 Agent；await requester.ainvoke(...) 才发一次模型请求。

### 10.2 一次请求的三个输入层次

| 内容 | 来自哪里 |
| --- | --- |
| 消息列表 | Runtime.prepare 或 ContextRuntime.prepare |
| 工具说明 | request_once 默认提供全部已注册工具 schema，目前内置 read；摘要/规划/汇总显式传空序列 |
| 模型与设置 | create_model 指定模型、地址、超时并禁用自动重试与缓存；每次请求传 max_tokens；不设置厂商专用 thinking 参数 |

单次请求统一使用 `request_once(model, history, *, tools=None, max_tokens=2048)`：默认携带已注册工具，传入空序列则不带工具，传入指定列表则使用该列表。函数直接请求模型，不做工具调度或自动续跑。

### 10.3 response 还保存什么

response_metadata 保留结束原因等服务商元数据；usage_metadata 保留 input_tokens、output_tokens、total_tokens 等用量。未提供 usage 时是 None，不能伪造为真实的零用量。Day 9 沿用预留额度结算缺失用量的策略。

## 11. Runtime、self 和配置对象：读懂“点号接点号”

`runtime.options.max_requests` 并不是特殊语法，只是连续取两层属性：

1. `runtime` 是一个 Runtime 实例。
2. `runtime.options` 是它持有的 RunOptions 实例。
3. `.max_requests` 是这个配置对象上的整数属性。

### 11.1 self 表示当前这个对象

在 `Runtime.__init__` 中：

```text
self.history = []
self.requests = 0
```

意思是：给这个 Runtime 实例保存一份历史列表和一个计数器。以后调用它的方法时，就能继续访问同一份状态。

方法定义写 `async def start(self, prompt)`，使用时写 `await runtime.start(prompt)`；Python 会自动把 runtime 作为 self 传进去，不需要你再传一遍。

`__init__` 在构造对象时初始化属性。`self` 不是全局共享空间：创建两个独立 Runtime，各自有自己的 history 和计数器。

### 11.2 Day 1 的实例属性

| 属性 | 初始/典型值 | 作用 |
| --- | --- | --- |
| `workspace` | 解析后的 Path | 工具可访问的工作目录 |
| `io` | ModelIO 对象 | 保存模型创建和请求函数 |
| `options` | RunOptions 对象 | 保存次数、时限、输出额度 |
| `history` | `[]` | 保存 HumanMessage / AIMessage / ToolMessage |
| `executions` | `[]` | 保存工具执行记录 ToolExecution |
| `requests` | `0` | 当前运行已尝试的模型请求次数 |
| `tool_calls` | `0` | 当前运行已计入额度的工具调用数 |
| `started` | `False` | 防止同一个实例被当作全新运行重复启动 |

### 11.3 dataclass、frozen 和 __post_init__

`@dataclass` 是装饰器，为主要保存数据的类生成初始化等常用方法。例如 `RunOptions()` 不传参数，就得到配套代码中的默认配置：

```text
max_requests=8
max_tool_calls=16
timeout=120.0
output_tokens=2048
```

`frozen=True` 限制实例字段的普通重新赋值，但不是递归冻结所有内部对象。`__post_init__` 在 dataclass 自动初始化之后执行，用来检查配置：额度必须是正整数，timeout 必须有限且大于零。

`math.isfinite` 排除无穷大和 NaN。`type(value) is int` 采用精确类型检查，这里也避免把布尔值当作整数额度。

### 11.4 io.request 为什么能像函数一样调用

Python 可以把函数本身存到对象属性里：

```text
request = request_once     保存函数，尚未调用
request_once(...)         调用函数
```

`ModelIO.request` 默认保存 `request_once`；`ModelIO.factory` 默认保存 `create_model`；`summarize` 保存摘要函数。于是 `runtime.io.request(...)` 就能调用被保存的函数。

配套类型注解中的几个名字：

| 名字 | 读法 |
| --- | --- |
| `Callable[[], AbstractAsyncContextManager[ChatOpenAI]]` | 不接收参数、返回异步上下文管理器的可调用对象 |
| `Awaitable[AIMessage]` | 可以 await，等待结果是 AIMessage |
| `Protocol` | 描述需要满足的接口形状，帮助类型检查 |
| `RequestFn.__call__` | 规定 request 可调用对象应该接受哪些参数、返回什么 |
| `Literal["completed", ...]` | 只允许列出的几个字面量值 |
| `type RunStatus = ...` | 给一组类型规则起一个别名，不是在创建运行状态对象 |
| 签名中的 `/` | 前面的相应参数仅按位置传入 |
| 签名中的 `*` | 后面的相应参数必须用名字传入，如 `max_tokens=2048` |

你在 Day 1 不需要实现自己的 Protocol 框架。先理解这里提前约定了函数如何接入，以后替换能力时就能保持循环不变。

### 11.5 Callable 和 Awaitable：函数、调用结果、等待后的结果

正确拼写是 **`Callable`** 和 **`Awaitable`**。它们在这里从 Python 标准库 `collections.abc` 导入，不是 LangChain 独有的类型。

**Callable 表示“可以调用的对象”。** 这里的“调用”指给对象加圆括号，例如 `create_model()`。普通函数、绑定方法，以及实现了 `__call__` 的对象都可以是可调用对象。

类型注解的基本写法是：

```text
Callable[[参数1的类型, 参数2的类型], 调用后返回值的类型]
```

外层方括号里分成两项：第一项是参数类型列表，第二项是返回类型。内层的列表描述函数输入，不是说你实际必须传入一个 Python 列表。

| 类型注解 | 如何调用 | 正常调用后直接得到什么 |
| --- | --- | --- |
| `Callable[[str], int]` | `fn("abc")` | 一个整数 |
| `Callable[[int, int], int]` | `fn(2, 3)` | 一个整数 |
| `Callable[[], str]` | `fn()` | 一个字符串 |
| `Callable[[], AbstractAsyncContextManager[ChatOpenAI]]` | `fn()` | 一个异步上下文管理器；进入后得到模型 |
| `Callable[[str], Awaitable[str]]` | `fn("请概括这段内容")` | 一个可等待对象，成功 await 后才得到字符串 |

例如 `Callable[[int, int], int]` 表示接收两个整数参数，不是接收一个含有两个整数的列表。空列表 `[]` 表示不需要传参数。

**Awaitable[T] 表示“可以使用 await 等待，并在成功完成后得到 T 类型结果的对象”。** `T` 在这里是占位写法：换成 `str`，等待后得到字符串；换成 `AIMessage`，等待后得到模型响应。

常见 Awaitable 包括协程对象、`asyncio.Task` 和 `asyncio.Future`。Day 1 主要接触调用 `async def` 函数得到的协程对象，不必先掌握另外两种的完整用法。

不要把可等待对象当成已经得到的结果：`Awaitable[str]` 本身不是字符串，不能直接把它当摘要正文。等待时也可能抛异常，因此“成功后得到 str”不保证请求一定成功。

#### 用项目里的摘要函数拆成三步

`summarize_once` 的定义是 `async def summarize_once(prompt: str) -> str`。下面展示三个表达式的不同含义，不需要额外运行模型请求：

```text
summary_fn = summarize_once
pending_summary = summary_fn("请概括这段内容")
summary_text = await pending_summary
```

| 变量 | 保存什么 | 现在已经拿到摘要了吗？ |
| --- | --- | --- |
| `summary_fn` | 异步函数本身，可以被调用 | 没有 |
| `pending_summary` | 调用该异步函数得到的协程对象，符合 Awaitable[str] | 没有 |
| `summary_text` | await 成功后得到的字符串 | 是 |

这里的第三行需要放在允许使用 await 的异步环境中，例如 `async def` 函数内部。

对普通 `async def` 函数，仅调用它来创建协程对象，不会立即执行完函数体，也不会自动创建后台任务。`await` 会推进并等待它；若使用 Task 调度，则任务可以先被安排运行，再等待结果。无论哪种情况，`Awaitable` 这个类型注解本身都不负责启动或调度任务。

平时把后两步合起来写就是：

```text
summary_text = await summary_fn("请概括这段内容")
```

因此项目中的声明：

```text
type SummaryFn = Callable[[str], Awaitable[str]]
```

可以完整读成：**SummaryFn 是一个类型别名，表示某个函数接收一个字符串，调用后返回一个可等待对象，成功等待后得到一个字符串。**

#### 为什么 async def 的箭头写 str，而 Callable 里写 Awaitable[str]？

两处注解描述的阶段不同：

- `async def summarize_once(...) -> str`：箭头标注协程成功完成后的结果，也就是 await 后得到的值。
- `Callable[[str], Awaitable[str]]`：标注可调用对象“刚被调用时”返回什么；这里先返回可等待对象。

所以它们可以描述同一个异步函数，并不矛盾。不要为了匹配 Callable，把正常返回字符串的异步函数改成 `async def ... -> Awaitable[str]`；那会表达“等待结束后返回的值仍然是一个可等待对象”，与当前实现不同。

`RequestFn.__call__` 使用普通 `def ... -> Awaitable[AIMessage]` 描述接口，也是为了表达调用后直接得到可等待对象。它的函数体是 `...`，只声明接口；实际默认实现是 `request_once`。

#### 对照 ModelIO 的三个字段

| 字段 | 保存的默认函数 | 调用方式 | 成功取得的结果 |
| --- | --- | --- | --- |
| `factory` | `create_model` | `runtime.io.factory()` | 得到异步上下文管理器；async with 进入后得到 ChatOpenAI |
| `request` | `request_once` | `await runtime.io.request(model, messages, max_tokens=2048)` | 等待后得到 AIMessage |
| `summarize` | `summarize_once` | `await runtime.io.summarize(prompt)` | 等待后得到 str |

`factory()` 返回的上下文管理器可以用于 `async with` 管理资源，但这不意味着 `factory()` 本身要 await。**能够异步管理资源与能够被 await，是两种不同的接口能力。**

最后区分大小写：`Callable[...]` 用来写类型注解；Python 内置函数 `callable(obj)` 用来询问对象能否被调用，返回布尔值。后者不会验证参数签名和返回类型，也不会执行那个对象。

### 11.6 ToolExecution 又是什么

`ToolExecution` 是 **Zeta 自己的 dataclass**，不是 LangChain 的消息类：

```text
ToolExecution
  raw：工具原始结果 ToolMessage
  result：最终采用的结果 ToolMessage
```

Day 1 的两个字段内容相同，但 raw 使用深复制，保留独立对象。Day 2 有结果处理 Hook 后，才更需要区分原始结果与最终结果。

因此 `execution.result` 是一个 ToolMessage，而 `execution.result.content` 才是结果正文。发送给模型的是结果消息，不是直接把 ToolExecution 当成消息发送。

## 12. Runtime 的方法：循环固定，每个位置做什么

这些名字是 Zeta 自己定义的接入约定，不是框架要求你必须这样命名。

| 调用位置 | Day 1 默认做什么 | 产生的数据变化 |
| --- | --- | --- |
| `start(prompt)` | 检查输入，创建用户消息 | history 增加用户输入，started=True |
| `begin_turn()` | 暂无额外动作 | 默认不改变历史 |
| `prepare()` | 在 history 副本前添加固定 SystemMessage | 返回本轮输入视图 |
| `on_response(response)` | 保存完整模型响应 | history 增加 AIMessage |
| `execute(call)` | 调用基础 execute_tool | 返回 ToolExecution |
| `on_result(execution)` | 保存执行记录 | executions 增加一项 |
| `after_turn(results)` | 有结果时 history.extend(results) | history 按顺序增加独立 ToolMessage |
| `retry(error)` | 返回 False | Day 1 默认不重试 |
| `finish(status, reason)` | 暂无持久化或监听器动作 | Day 1 不会因此自动保存数据库 |

`deepcopy` 是深复制：复制历史中的嵌套对象，使准备出来的视图与原历史尽量独立。直接 `messages = self.history` 只是两个变量指向同一个列表。

只有文档字符串、没有其他执行语句的方法是合法 Python，调用后相当于不做额外动作并返回 None。它与练习里的 `raise NotImplementedError` 不同：前者是明确的默认无操作，后者表示必须完成的函数还没写。

后续 `HookRuntime`、`SessionRuntime`、`ContextRuntime` 在同样的方法位置加入自己的行为，复用之前的方法。Day 1 保留这些调用位置，就是为了后面不重写 run_loop。

## 13. async、await、async with：这里到底在等什么

### 13.1 async def 与 await

`async def request_once(...)` 定义异步函数。调用它通常先得到协程对象，`await` 它才会在当前异步任务中推进执行并等待结果。

```text
response = await runtime.io.request(model, messages, max_tokens=2048)
```

意思是：执行请求并等待完成，完成后把 AIMessage 保存为 response。等待网络期间，事件循环可以安排其他可运行的异步任务。

**await 不会自动创建多个 Agent，也不会让一个 for 循环自动并行。** Day 1 仍然按代码顺序等待请求、执行工具、收集结果。

普通 `read_file` 是同步函数。基础 Runtime 用 await asyncio.to_thread(execute_tool, call, workspace) 接入，事件循环等待线程结果。取消 await 不会强制终止已经运行的文件读取线程。

### 13.2 asyncio.run 是入口桥梁

CLI 的普通函数 `main()` 不能直接写 await，因此使用：

```text
asyncio.run(run_agent(prompt, Path.cwd()))
```

它创建并管理事件循环，执行这个顶层协程，取得返回值。已经在异步函数内部时继续使用 await，不要在里面再嵌套 asyncio.run。

### 13.3 with 和 async with

普通 `with` 常用于文件打开与关闭。`async with` 则让资源进入和退出过程可以异步等待。

`async with runtime.io.factory() as model`：先由 factory 创建我们提供的异步上下文管理器，进入后创建并得到模型客户端，使用期间命名为 model，退出时按适配器约定管理客户端资源。

`async with asyncio.timeout(runtime.options.timeout)`：为里面的运行步骤设置时间范围。超时时，取消在异步可响应位置发生，退出这个 timeout 上下文时通常表现为 TimeoutError。

异步超时不是操作系统强制杀线程；阻塞的同步操作可能不能立即中断。Day 1 的 finally 清理位于这个总运行 timeout 块之外；Hook 的终态通知另有自己的限制，不能笼统地声称所有自定义清理都被同一个 timeout 包住了。

## 14. 逐行读 response_calls：从一份响应提取工具调用

职责保持原样：检查响应是否适合消费，返回工具调用列表；不执行工具、不发请求。

### 14.1 先排除片段与非法参数

检查 isinstance(response, AIMessageChunk) 和 response.invalid_tool_calls。任何一项成立都抛 ModelResponseError；不再限制 content 必须是字符串。

### 14.2 直接取出 LangChain 已解析的调用

```text
calls = response.tool_calls
```

不再从混合 parts 里按 ToolCall 类型筛选。列表中的元素仍是原调用字典；只有文字时得到空列表。

### 14.3 取出编号，检查空白和重复

```text
ids = [call["id"] for call in calls]
any(not value or not value.strip() for value in ids)
len(ids) != len(set(ids))
```

第一项排除 None、空字符串和全空格，第二项排除同批重复。检查不会把合法 ID 改写成 strip 后的字符串。

### 14.4 返回调用列表

最后 `return calls`。有调用就返回列表，没有调用就返回 `[]`。不再检查工具名非空、正文类型、结束原因或最终文字非空；未知工具和参数错误由执行器处理。

## 15. 逐行读 validate_history：pending 是“还欠着哪些结果”

### 15.1 pending 字典长什么样

pending: dict[str, str] 的键是调用 ID，值是工具名。例如 {"call_001": "read", "call_002": "read"} 表示尚欠两条结果，不表示工具正在后台运行。

### 15.2 看见 AIMessage 时登记调用

先要求上一批 pending 为空，再读取 message.tool_calls，检查编号非空且同批唯一，把 call["id"] 和 call["name"] 登记进去。这里不重新检查旧响应的正文或元数据。无调用的最终响应不增加 pending。

### 15.3 看见 ToolMessage 时核销结果

```text
if isinstance(message, ToolMessage):
    if pending.get(message.tool_call_id) != message.name:
        raise ValueError("unmatched tool result")
    del pending[message.tool_call_id]
    continue
```

ToolMessage 本身就是结果消息，所以这一层直接检查 message，不遍历 message.parts。没有编号、重复结果或工具名称不一致都会拒绝。

处理完 ToolMessage 后用 continue 进入下一条消息。所有非 ToolMessage 共用一个 pending 检查，避免分别为 AIMessage、HumanMessage 和 SystemMessage 写相同分支。函数只负责配对，不再额外限制消息类型。

### 15.4 手动跟踪 pending

| 读到的消息 | pending |
| --- | --- |
| HumanMessage(问题) | {} |
| AIMessage(read call_001、read call_002) | 两个编号 |
| ToolMessage(call_001) | 只剩 call_002 |
| ToolMessage(call_002) | {} |
| AIMessage(最终文字) | {} |

### 15.5 为什么在这个位置校验

发送下一次请求之前，必须已有完整调用与结果组。保存过程中允许出现暂时 pending，恢复与下一次请求却不能把缺结果的历史直接发给模型。Session 的这个原则仍沿用原版。

## 16. 逐段读 run_loop：它只是反复推动同一条消息链

掌握前面的对象之后，再看 Day 1 的循环就能把每句对应到具体数据。

### 16.1 初始状态与启动

`status="failed"` 是保守初值，只有正常完成才改为 completed。`reason` 保存终态原因；`primary` 保存最初导致中断的异常对象，避免清理错误把原始错误盖掉。

进入总超时上下文后调用 `runtime.start(prompt)`，再进入模型资源上下文。

### 16.2 每轮请求前

按顺序做四件事：

1. `await runtime.begin_turn()`：让这一轮的扩展逻辑有接入位置。
2. `messages = await runtime.prepare()`：拿到本轮输入视图。
3. `validate_history(messages)`：确保调用和结果完整。
4. `runtime.requests += 1`：在尝试请求前计数，请求失败也消耗一次尝试额度。

`while runtime.requests < runtime.options.max_requests` 控制最多尝试几次请求。这里的次数不是 message 条数，也不是工具调用数量。

### 16.3 发请求并处理允许的重试

`response = await runtime.io.request(...)` 返回一份 AIMessage。

`except APIStatusError as error` 捕获模型服务 HTTP 错误。只有还有请求额度且 `runtime.retry(error)` 返回 True，才执行 continue 重新进入循环。Day 1 默认 retry=False，所以不是“任何错误自动重试”。Day 7 才加入特定上下文超长的压缩重试策略。

### 16.4 校验、保存响应、整批检查预算

先 `calls = response_calls(response)`，再 `await runtime.on_response(response)` 保存完整响应。

若有 calls，在执行任何工具前检查整个批次：

```text
requests >= max_requests
或
tool_calls + len(calls) > max_tool_calls
```

前一项是为了确保执行完工具后至少还有一次模型请求机会；后一项避免执行到一半才发现工具额度不足。

例如 max_requests=1：第一次请求如果返回最终文字，可以成功；如果返回工具调用，剩余次数无法用于消费工具结果，所以停止，不去读文件。

通过检查后 `tool_calls += len(calls)` 先计入整批调用。因此某次执行中途失败时，这个计数不一定等于已成功执行的工具数量。

### 16.5 执行和汇总工具结果

```text
results: list[ToolMessage] = []
for call in calls:
    execution = await runtime.execute(call)
    await runtime.on_result(execution)
    results.append(execution.result)
await runtime.after_turn(results)
```

每轮 results 都是新列表，只装本轮工具结果。保存执行记录与添加发给模型的历史是两个动作，不能以为 on_result 默认已经把 history 补齐。

执行完一批后，while 自然继续下一轮，模型就会看到新增的工具结果消息。

### 16.6 最终文字与终态

没有调用时，循环设置 `status="completed"`，返回 `response.text or ""`。

本代码中的状态名称属于不同对象：

| 名字 | 例子 | 回答什么问题 |
| --- | --- | --- |
| 消息类型与 invalid_tool_calls | 完整 AIMessage、无非法调用 | 这份模型响应是否可消费？ |
| `response.response_metadata["finish_reason"]` | `"stop"` | 这一轮生成为什么结束？ |
| `status: RunStatus` | `"completed"` | 整次 Zeta 运行最后怎样结束？ |
| `ToolMessage.status` | `"success"` | 这一次工具执行怎样结束？ |

LangChain 这里没有旧版的 complete 状态字段；completed 仍是 Zeta 整次运行的终态值。

## 17. 异常、取消、finally 和日志

### 17.1 异常不是普通返回值

函数可以正常 `return`，也可以 `raise` 抛异常。抛异常后，Python 会离开当前普通执行路径，向外寻找匹配的 except；找不到就继续向上传播。

| 异常 | 来源 | 在 Day 1 中的用途 |
| --- | --- | --- |
| `ValueError` | Python | 参数、历史配对等不符合约定 |
| `ModelResponseError` | Zeta | 响应内容不符合循环预期 |
| `APIStatusError` | 底层 OpenAI SDK | 模型服务 HTTP 错误，可读取 status_code 等信息 |
| `RunLimitError` | Zeta | 请求或工具额度耗尽 |
| `RunStopped` | Zeta，继承 RunLimitError | 后续 Hook 主动要求停止 |
| `ToolError` | Zeta | read 参数或文件读取等预期失败 |
| `TimeoutError` | Python | 超时上下文到期 |
| `asyncio.CancelledError` | Python | 当前异步任务被取消 |
| `NotImplementedError` | Python | 练习函数尚未填写，不是成功占位结果 |

`class RunStopped(RunLimitError)` 表示子类关系，因此捕获 RunLimitError 也可以捕获 RunStopped。这两个类即使没有自定义方法，也可以用类型表达不同原因。

### 17.2 为什么捕获 BaseException 后又 raise

`BaseException` 范围比普通 `Exception` 大，包含 asyncio.CancelledError 等中断信号。Day 1 捕获它是为了记录终态，然后用不带参数的 `raise` 把同一个异常继续向外抛。

这里不是“忽略所有错误”。若只记录后返回一段普通文字，外层可能误以为任务成功，取消也可能被吞掉。

终态映射是：取消 → cancelled；额度或主动停止 → stopped；其他错误 → failed。

### 17.3 finally 为什么在 return 后仍执行

`finally` 表达“离开这个 try 时仍要执行的收尾”，正常返回、异常传播时都会经过它。因此最终回答已经准备返回，也会先执行 `runtime.finish(status, reason)`。

若清理失败且没有更早的错误，清理错误会继续抛出；若已经有 primary 错误，就记录清理问题，让原始错误继续传播。这是为了保留最有用的失败原因。

### 17.4 logging 的两个名字

`logging.getLogger(__name__)` 获取当前模块的日志记录器。`__name__` 是 Python 设置的模块名称字符串。

`logger.warning("cleanup failed: %s", type(cleanup_error).__name__)` 发出警告日志，记录清理错误的类名。日志不是模型回答，也不会因为写了日志就自动回传给模型。

## 18. 最后串起来：从 CLI 到工具结果的文件地图

| 文件/位置 | 你阅读时应回答的问题 |
| --- | --- |
| `cli.py: main` | 用户输入从哪里来，怎样进入异步函数，异常怎样显示？ |
| `app.py: run_agent` | 选择哪个 Runtime，怎样调用固定循环？ |
| `loop.py: run_loop` | 一轮请求结束后，为什么继续或停止？ |
| `loop_common.py: response_calls` | 响应的 tool_calls 中有哪些调用，响应是否可消费？ |
| `loop_common.py: validate_history` | 已有调用是否都有对应结果？ |
| `runtime_base.py: Runtime` | 历史、计数器放在哪，各步骤如何改变它们？ |
| `model_io.py: request_once` | 用什么工具定义和设置发送一次请求？ |
| `tools.py: resolve_tool_call / execute_tool` | 怎样按名称取得参数模型和函数、校验参数并执行 handler？ |
| `tools.py: make_tool_message` | 怎样把正文和调用编号包装成工具结果？ |
| `builtin_tools/read.py: ReadArgs / read_file` | read 接收哪些参数，哪一行真正读取了本机文件？ |
| `tools.py: TOOLS` | 工具名对应哪个参数模型和执行函数，新增工具在哪里加一项？ |
| `builtin_tools/__init__.py: ToolError` | 具体工具和调度层如何共用同一种预期错误？ |

这些位置描述的是 Day 1 和 support.md 组合后的目标代码。有些文件可能尚未由你在 src 中准备完成；文档有完整代码不代表当前 CLI 已经跑通。

CLI 中暂时需要认识的补充名字：`argparse.ArgumentParser` 定义命令行参数；`parse_args()` 读取参数；`cast(str, args.prompt)` 提供类型提示而不是执行字符串转换；`parser.exit(...)` 显示错误并退出；`__version__` 是项目版本变量。`prompt` 是用户输入字符串，`workspace` 是本地工具工作的目录。

`run_agent` 中的 `runtime=None` 表示可不传自定义 Runtime；`active = runtime if runtime is not None else Runtime(workspace)` 表示“传了就用，否则创建默认对象”。这个入口不需要随学习天数改写，后续传入新增的 Runtime 子类即可。

support.md 还提供了 SQLite 存储和摘要函数。它们主要在后续单元使用，读 Day 1 时先认识入口，不需要先掌握数据库事务和压缩算法。`summarize_once` 是无工具的单次模型请求，不会在默认 Day 1 循环中自动触发。

## 19. 遇到一个陌生表达式时，按这个顺序拆

以 `results.append(execution.result)` 为例：

1. 左边 results 是什么类型？——本轮 ToolMessage 列表。
2. append 是属性还是方法？——带括号，是列表的方法。
3. 括号里的 execution 是什么？——ToolExecution 对象。
4. execution.result 又是什么？——最终采用的 ToolMessage。
5. 整句有什么效果？——把一个结果对象放入列表，尚未发送给模型。

常用名字速查：

| 名字 | 先记这一句 |
| --- | --- |
| `message` | 历史中的一条消息，可能是请求或响应 |
| `messages` / `history` | 多条消息组成的序列，前者常是当前视图，后者常是保存的历史 |
| `response` | 一次模型返回的 AIMessage 对象 |
| `Path.parts` | 文件路径组件；LangChain 消息不使用旧版 response.parts |
| `tool_calls` | AIMessage 上的调用字典列表 |
| `calls` | 从本轮响应筛出的 ToolCall 列表 |
| `call` | 某一次具体工具调用的数据 |
| `call["name"]` / `ToolMessage.name` | 调用与结果对应的工具名 |
| `tool_call_id` | 这次调用的编号，结果原样带回 |
| `call["args"]` | LangChain 已解析的参数字典 |
| `content` | 内容；具体是问题、文字还是工具正文，要看所属消息类型 |
| `result` | 这里通常指一个工具结果对象，注意具体函数的类型注解 |
| `results` | 本轮工具结果列表 |
| `execution` | Zeta 保存的原始/最终工具结果组合 |
| `pending` | 历史扫描时仍未找到结果的调用编号与名称 |
| `runtime` | 保存运行状态并提供各步骤方法的对象 |
| `options` | 本次运行的额度和时限配置 |
| `io` | 保存模型创建/请求函数的配置对象 |
| `invalid_tool_calls` | LangChain 未能解析的调用，非空时拒绝响应 |
| `finish_reason` | 模型这一轮结束生成的原因 |
| `status` | 看所属对象：运行终态，或 ToolMessage 的 success/error |
| `artifact` | 本地工具元数据；本课用它保留 denied/failed 区别 |

这些小写变量名多数是程序作者起的，不能只靠名字猜类型。优先看它在哪里赋值、函数签名怎么写、类里声明了什么字段。

读回 Day 1 时，只要能顺着说出下面这段话，就有了开始写代码的基础：

> 我先把用户输入包装成 HumanMessage。一次模型请求返回 AIMessage，我从 tool_calls 取出调用，检查名称、参数和编号，再由本地代码执行工具。执行结果包装成同编号的 ToolMessage，直接追加到历史。把完整历史再发给模型，直到得到没有工具调用的有效最终文字，或者触发明确的停止条件。

## 20. 资料依据与后续查阅

课程结构来自 [GitHub 9359d5f](https://github.com/juemimgcd/Zeta/tree/9359d5fadadaf82ef42ae600be22d565cf72a984/days)。当前接口依据 [LangChain OpenAI 兼容接口 接入](https://docs.langchain.com/oss/python/integrations/chat/openai)、[消息说明](https://docs.langchain.com/oss/python/langchain/messages) 和 [消息序列化 API](https://reference.langchain.com/python/langchain-core/messages)。

完整可复制代码以 support.md 和各日参考答案为准。异步入口、Runtime、SQLite 与后续并发 Worker 保留原版职责；这篇前置阅读不增加实现任务，也不说明现有 src 已完成迁移。
