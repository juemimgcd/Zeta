# Day 1 前置知识：从 Python 对象到一次完整的工具调用

[学习总览](summary.md) · [Day 1 练习](day1.md) · [固定基础代码](support.md)

这篇文章假设你第一次接触 PydanticAI，不知道消息对象、工具调用协议，也不熟悉这些类的字段。目标是让你读懂 Day 1 已经出现的代码，再去填写练习。本文不新增实现任务，也不要求重写你已经完成的函数。

本文依据 **2026-09-08 本项目实际安装的 `pydantic-ai-slim==2.37.0`**、`days/day1.md`、`days/support.md` 和现有 `src/zeta/tools.py` 编写。网上的最新版文档可能发生变化，字段名和值以这个版本为准。文中的具体 ID、文件正文和模型回答都是**讲解用的示意值**，不是本次真实请求模型的记录；对象片段用于阅读，不是让你另外建立测试或复制一套 Agent。

先回答你最关心的三个问题：

- **`response.parts`**：从 `response` 这个响应对象上取出“消息片段序列”。里面的元素可能是文字对象，也可能是工具调用对象等，不能假定都是字符串。
- **`tool_call_id`**：一个字符串属性，表示“这一次工具调用的编号”，不是函数。结果要带回同一个编号，才能知道它回答了哪一次调用。
- **`ToolReturnPart`**：PydanticAI 提供的类。我们用它把本地工具执行得到的结果包装成一个对象，再放进下一次发给模型的消息里。它本身不执行工具。

建议分三遍读：第一遍读第 1–8 节，认识数据长什么样；第二遍读第 9–13 节，看数据怎样流动；第三遍对照第 14–18 节逐行读 Day 1。遇到符号可以查第 19 节，不必一次背完。

| 阅读范围 | 解决的问题 |
| --- | --- |
| 第 1–2 节：包和 Python 语法 | import、类、对象、属性、方法、类型注解怎么看？ |
| 第 3–6 节：消息与工具片段 | parts 里装什么？调用编号如何对应结果？ |
| 第 7–8 节：完整交互与状态 | 两次模型请求之间发生了什么？complete 和 stop 为什么不能混用？ |
| 第 9–10 节：工具和请求接口 | 参数怎么校验？哪一行执行工具？哪一行请求模型？ |
| 第 11–13 节：Runtime 与异步 | self、配置对象、接入方法和 await 分别做什么？ |
| 第 14–17 节：逐段读 Day 1 | 三个核心函数与异常收尾为什么这样写？ |
| 第 18–20 节：文件地图、速查和依据 | 遇到陌生名字时去哪里找？ |

## 1. 先分清：哪些是 Python，哪些是包，哪些是我们自己的代码

### 1.1 包、模块和 import

看这一行：

```python
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
```

可以从左到右读成：从 `pydantic_ai` 包中的 `messages` 模块，取出三个已经定义好的名字，供当前文件使用。

- **包**：组织多个 Python 模块的单位，这里叫 `pydantic_ai`。
- **模块**：通常对应一个 `.py` 文件，这里对应安装目录里的 `pydantic_ai/messages.py`。
- **类**：定义一种对象有哪些数据、能做什么。这里三个名字都是类。
- **导入**：让当前文件能使用这个名字。导入类不等于请求模型，也不等于执行工具。

项目依赖里叫 `pydantic-ai-slim`，代码却写 `import pydantic_ai`，是因为“安装包名称”和“Python 导入名称”可以不同。`python-dotenv` 对应 `dotenv` 也是一样。

### 1.2 Day 1 的三类来源

| 来源 | 例子 | 负责什么 |
| --- | --- | --- |
| Python 自带的标准库 | `asyncio`、`logging`、`pathlib`、`dataclasses`、`collections.abc`、`typing`、`copy`、`math` | 异步等待、日志、路径、类型表达、对象复制等基础能力 |
| 第三方 Pydantic | `BaseModel`、`Field`、`ConfigDict`、`ValidationError` | 声明并校验数据，例如 read 的参数必须有字符串 `path` |
| 第三方 PydanticAI | `ModelRequest`、`ModelResponse`、各种 `Part`、`model_request`、`ToolDefinition` | 描述模型消息和工具协议，完成单次模型通信 |
| Zeta 自己定义的代码 | `response_calls`、`validate_history`、`run_loop`、`Runtime`、`RunLimitError` | 决定何时请求、何时执行工具、怎样配对、何时停止 |

`from zeta.loop_common import RunLimitError` 表示导入我们自己文件里的名字。它不是 PydanticAI 自带的异常。

**Pydantic 和 PydanticAI 是两个不同的包。** 参数校验用前者，模型通信和消息类型用后者。Zeta 使用 PydanticAI 的 direct API 发送一次请求，后续循环由自己的 `run_loop` 控制。

## 2. 读这些代码需要的最小 Python 语法

### 2.1 类、对象、属性、方法分别是什么

下面这个片段创建一个工具调用对象：

```python
from pydantic_ai.messages import ToolCallPart

call = ToolCallPart(
    tool_name="read",
    args={"path": "README.md"},
    tool_call_id="call_001",
)
```

逐项解释：

| 写法 | 含义 | 在这个例子里的值 |
| --- | --- | --- |
| `ToolCallPart` | 类，规定工具调用的数据形状 | 不是某一次具体调用 |
| `ToolCallPart(...)` | 调用构造入口，创建一个实例 | 得到一个工具调用对象 |
| `call` | 保存这个对象的变量名 | 名字可以换，但这里约定叫 call |
| `call.tool_name` | 读取对象的属性 | `"read"` |
| `call.args` | 读取参数属性 | `{"path": "README.md"}` |
| `call.tool_call_id` | 读取编号属性 | `"call_001"` |
| `call.args_as_dict()` | 调用对象提供的方法 | 将参数按字典形式返回 |

有圆括号的 `call.args_as_dict()` 是方法调用。没有圆括号的 `call.tool_call_id` 是属性访问。不能写 `call.tool_call_id()`，因为字符串不能被当作函数调用。

`ToolCallPart(...)` 里带括号也不意味着执行 read：这里调用的是**对象构造入口**。构造出的对象只是在描述“请调用 read”。

还有一种属性叫 `property`，读取时会执行类内部的计算。`response.text` 就属于这种情况，但使用者仍然写 `response.text`，不写 `response.text()`。

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

对象属性用点号，例如 `call.tool_name`。字典取值用键，例如 `call.args["path"]`，但这句只有在 `args` 已确认是字典时才适用。

### 2.3 类型注解不负责执行，也不自动校验所有数据

```python
from collections.abc import Sequence

from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart


def response_calls(response: ModelResponse) -> list[ToolCallPart]:
    """签名阅读示例：函数体见 Day 1。"""
    raise NotImplementedError


def validate_history(messages: Sequence[ModelMessage]) -> None:
    """签名阅读示例：函数体见 Day 1。"""
    raise NotImplementedError
```

这里只读签名，不需要把这两个未完成函数另外复制到源码。

- `response: ModelResponse`：这个参数预期是一个 `ModelResponse` 对象。
- `-> list[ToolCallPart]`：正常返回时，结果是一个列表，列表里的元素都是 `ToolCallPart`。
- `Sequence[ModelMessage]`：一个有顺序的消息序列，可以是列表、元组等；这个接口只要求读取，不要求一定是可修改的列表。
- `-> None`：函数不返回有用的数据。校验成功正常结束，校验失败抛异常。
- `str | None`：允许字符串或者 `None`。
- `dict[str, str]`：键和值都是字符串的字典。

**类型注解主要供人和类型检查器使用。** 写了 `path: str` 不代表普通 Python 函数会自动阻止所有错误输入。`ReadArgs.model_validate(...)` 才是明确执行 Pydantic 运行时校验的操作。

### 2.4 后面会反复出现的短写法

| 表达式 | 用普通话解释 |
| --- | --- |
| `isinstance(part, ToolCallPart)` | part 是不是 ToolCallPart 类型的实例，包括它的子类实例？ |
| `if calls:` | calls 列表是否非空？ |
| `if not calls:` | calls 列表是否为空？ |
| `value.strip()` | 返回去掉两端空白后的字符串，不修改原字符串 |
| `len(ids)` | 列表中有多少个元素？ |
| `set(ids)` | 用集合去除重复编号，不用它保持原顺序 |
| `any(...)` | 里面有没有至少一个条件为真？ |
| `response.text or ""` | text 为 None 或空字符串等假值时，使用空字符串 |
| `pending.get(key)` | 查字典；没有这个键时默认返回 None |
| `del pending[key]` | 从字典删除这个键和值 |
| `history.append(response)` | 把整个 response 作为一个元素放到列表末尾 |
| `continue` | 跳过本轮后续代码，进入下一轮循环 |
| `raise SomeError(...)` | 抛出异常，普通执行流程在这里中断 |

## 3. 模型通信不是“输入一个字符串，输出也只有一个字符串”

用户界面看起来像聊天，但程序需要处理更丰富的数据。模型可能输出普通文字，也可能请求程序读取文件；程序随后要把读取结果发回去。

PydanticAI 用两类消息承载这些数据：

| 消息类 | 方向 | 典型内容 |
| --- | --- | --- |
| `ModelRequest` | 程序交给模型的消息 | 用户的问题、工具执行结果等 |
| `ModelResponse` | 模型返回给程序的消息 | 文字、工具调用等 |

`ModelMessage` 是表示“可以是上述两种消息之一”的类型别名。Day 1 可按 `ModelRequest | ModelResponse` 理解；源码还附带了序列化时用的类型区分信息。它不是要你写 `ModelMessage(...)` 来创建对象的第三种消息类。

**`ModelRequest` 不等于“一次 HTTP 请求”，也不等于“只能装用户说的话”。**

一次 `model_request(model, history, ...)` 通信会把整个历史序列交给适配器。这个序列中既有以前的 `ModelRequest`，也有以前的 `ModelResponse`。适配器再转换成服务商需要的请求格式。

例如第二次调用模型时，输入历史可以有三条消息：

```text
history[0]：ModelRequest   用户要求读取 README.md
history[1]：ModelResponse  模型要求调用 read
history[2]：ModelRequest   程序提供 read 的读取结果
```

这三条消息共同构成第二次请求的输入。模型需要看到它自己之前要求做什么，以及程序实际得到什么结果。

## 4. parts 到底是什么？先看对象里面的层次

`parts` 就是英文“多个部分”。一条消息内部可能含多个部分，所以消息对象有一个叫 `parts` 的属性。

```text
history：外层消息序列
  第 0 条消息：ModelRequest
    parts：这条消息内部的片段序列
      第 0 个片段：UserPromptPart
  第 1 条消息：ModelResponse
    parts：这条消息内部的片段序列
      第 0 个片段：TextPart
      第 1 个片段：ToolCallPart
```

**两层序列不要混淆：`history` 里面是消息，`message.parts` 里面是片段。**

`parts` 的类型声明是 `Sequence[...]`，常见构造形式是列表 `[...]`；它不是一个固定内容的字符串，也不保证只有一个元素。不同片段有不同字段，不是每个片段都有 `content`，也不是每个片段都有 `tool_name`。

### 4.1 先认识四种最常用的 Part

| 类 | 可以拆成 | 含义 | Day 1 中放在哪一侧 | 最重要的属性 |
| --- | --- | --- | --- | --- |
| `UserPromptPart` | User + Prompt + Part | 用户输入片段 | `ModelRequest.parts` | `content` |
| `TextPart` | Text + Part | 模型文字片段 | `ModelResponse.parts` | `content` |
| `ToolCallPart` | Tool + Call + Part | 模型要求调用工具 | `ModelResponse.parts` | `tool_name`、`args`、`tool_call_id` |
| `ToolReturnPart` | Tool + Return + Part | 程序返回工具结果 | `ModelRequest.parts` | `tool_name`、`content`、`tool_call_id`、`outcome` |

普通用户定义工具的调用和返回方向就是上表。包里还有 `ThinkingPart`、原生工具片段、多模态片段等；Day 1 不需要全部掌握，也不能据此假定整个包只有这四种类型。特别是服务商原生工具有自己的返回片段类型，不要与本地 read 使用的 `ToolReturnPart` 混为一谈。

### 4.2 只有文字的响应

下面是一个便于阅读的对象示例：

```python
from pydantic_ai.messages import ModelResponse, TextPart

response = ModelResponse(
    parts=[TextPart(content="你好，我是 Zeta。")],
    state="complete",
    finish_reason="stop",
)
```

各表达式的值为：

| 表达式 | 值 |
| --- | --- |
| `response.parts` | 包含一个 TextPart 对象的序列 |
| `response.parts[0]` | `TextPart(content="你好，我是 Zeta。")`，这里省略默认字段 |
| `response.parts[0].content` | `"你好，我是 Zeta。"` |
| `response.text` | `"你好，我是 Zeta。"` |
| `response.state` | `"complete"` |
| `response.finish_reason` | `"stop"` |

`response.parts[0]` 是对象，`response.parts[0].content` 才是这个文字对象保存的字符串。

### 4.3 只有工具调用的响应

```python
from pydantic_ai.messages import ModelResponse, ToolCallPart

response = ModelResponse(
    parts=[
        ToolCallPart(
            tool_name="read",
            args={"path": "README.md"},
            tool_call_id="call_001",
        )
    ],
    state="complete",
    finish_reason="tool_call",
)
```

这次 `response.parts[0]` 是 `ToolCallPart`。它的意思是：希望程序执行名为 read 的工具，参数是 path=README.md，这次调用编号是 call_001。

此时 `response.text` 是 **`None`**，因为没有文字片段。工具调用是真实的结构化内容，即使 `response.text` 为空也不能直接认定“模型没有返回任何东西”。

### 4.4 文字和工具调用同时存在

```python
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

response = ModelResponse(
    parts=[
        TextPart(content="我先读取项目说明。"),
        ToolCallPart(
            tool_name="read",
            args={"path": "README.md"},
            tool_call_id="call_001",
        ),
    ],
    state="complete",
    finish_reason="tool_call",
)
```

`response.text` 只能拿到 `"我先读取项目说明。"`。如果只保留它，就丢掉了工具名称、参数、调用编号，也就无法执行和配对了。

所以 Day 1 会遍历 `response.parts`，找出其中的 `ToolCallPart`。**有文字不代表任务已经结束，要先看有没有工具调用。**

在本地 2.37.0 中，`response.text` 是根据文字片段计算出来的便捷属性：相邻文字片段拼接，隔着其他片段的文字段之间使用空行分隔；也可包含语音转写文字。Day 1 只需理解它是文字视图，不能替代完整 `parts`。

### 4.5 为什么先判断类型再读属性

同一个 `parts` 序列里可以混合多种对象。只有确认片段属于工具调用，才读取工具调用的字段。

```python
from pydantic_ai.messages import ModelResponse, ToolCallPart


def describe_calls(response: ModelResponse) -> list[str]:
    """语法讲解：只描述调用，不执行工具，不属于新增练习。"""
    descriptions: list[str] = []
    for part in response.parts:
        if isinstance(part, ToolCallPart):
            descriptions.append(f"{part.tool_call_id}: {part.tool_name}")
    return descriptions
```

上面的 `isinstance` 同时帮助人和类型检查器缩小范围：进入 `if` 后，就知道 `part` 可以按 `ToolCallPart` 读取。这也叫类型收窄。

## 5. tool_call_id：给“这一次调用”配对，不是给工具命名

### 5.1 tool_name 和 tool_call_id 的区别

假设模型同一轮想读两个文件：

| 调用 | `tool_name` | `args` | `tool_call_id` |
| --- | --- | --- | --- |
| 第一次 | `"read"` | `{"path": "README.md"}` | `"call_001"` |
| 第二次 | `"read"` | `{"path": "pyproject.toml"}` | `"call_002"` |

两个调用的工具名称相同。只写 `tool_name="read"` 无法说明“这份结果对应哪一个文件的调用”。不同编号用来区分每一次调用。

可以把工具名称理解为操作种类，把调用编号理解为这笔操作的单号。编号不是文件路径、不是函数名，也不是整个会话的编号。

### 5.2 编号从哪里来

真实模型调用中，服务商返回的工具调用数据通常带有编号，PydanticAI 将它保存在 `ToolCallPart.tool_call_id`。包也有缺少编号时的生成机制，手动构造对象时不填该字段会触发默认生成。

**对 Zeta 而言，拿到 `call.tool_call_id` 后应原样使用，不要解析前缀，也不要自己重新生成结果编号。** 本文的 `call_001` 只是易读示意，不要求真实 ID 长这样。

尤其不要因为 `ToolReturnPart` 也能自动生成编号，就省略返回对象上的编号。它自动生成的新编号不保证与原调用相同。

### 5.3 正确配对的结果对象

```python
from pydantic_ai.messages import ToolCallPart, ToolReturnPart

call = ToolCallPart(
    tool_name="read",
    args={"path": "README.md"},
    tool_call_id="call_001",
)

result = ToolReturnPart(
    tool_name=call.tool_name,
    tool_call_id=call.tool_call_id,
    content="# Zeta\n一个本地 Coding Agent。",
)
```

这里的 `content` 是讲解用正文。在实际 `execute_tool` 中，这个参数来自 `read_file(...)` 的返回值。

匹配关系是：

```text
调用：tool_name="read", tool_call_id="call_001"
结果：tool_name="read", tool_call_id="call_001"
```

`content` 可以变化，它承载结果；名称和编号必须对应原调用。

Day 1 校验非空、同批编号不重复，并按编号与名称检查结果。编号只满足这些条件并不证明工具真的执行了，也不证明结果内容正确；那还要看实际执行过程。

## 6. ToolReturnPart 是结果信封，Python return 是语言动作

名字里的 Return 很容易让人误会。看实际工具代码的形状：

```text
return ToolReturnPart(
    tool_name=call.tool_name,
    tool_call_id=call.tool_call_id,
    content=read_file(args, workspace),
)
```

执行顺序是：

1. 先调用 `read_file(args, workspace)`，得到文件正文字符串；失败时会抛异常。
2. 用正文、名称和编号创建 `ToolReturnPart` 对象。
3. Python 的 `return` 把这个对象交给 `execute_tool` 的调用者。

`return` 是 Python 关键字；`ToolReturnPart` 是类；`content` 是构造参数和对象属性。它们属于三个层面。

结果对象本身不会自动发送到模型。Day 1 还要把结果放进 `ModelRequest(parts=results, ...)`，加入历史，然后再请求一次模型。

本地版本中常见字段如下：

| 字段 | 类型/典型值 | 作用 |
| --- | --- | --- |
| `tool_name` | `str`，例如 `"read"` | 对应哪个工具 |
| `tool_call_id` | `str`，例如 `"call_001"` | 对应哪一次调用 |
| `content` | Day 1 是文件正文字符串；库还支持更丰富内容 | 把什么结果告诉模型 |
| `outcome` | `"success"` / `"failed"` / `"denied"` / `"interrupted"` | 本次工具处理结果，默认 success |
| `part_kind` | `"tool-return"` | 标识片段种类，通常不用自己填 |
| `timestamp` | 时间对象 | 结果记录时间，有默认值 |
| `metadata` | 可选附加数据 | 本地附加信息，不作为这个字段直接发送给模型 |

Day 1 的基础 `execute_tool` 成功时返回结果，预期失败时抛出 `ToolError` 并停止。Day 2 才增加把预期失败和拒绝转换为结果对象的调度逻辑。不要仅因为库支持 `outcome="failed"`，就以为 Day 1 已经实现了失败后继续。

## 7. 走一遍完整历史：用户提问 → 工具调用 → 工具结果 → 最终回答

设用户要求：**“用 read 读取 README.md 并概括目标。”**

### 7.1 第一步：创建用户消息

```python
from pydantic_ai.messages import ModelRequest

request = ModelRequest.user_text_prompt(
    "用 read 读取 README.md 并概括目标。",
    instructions="You are Zeta. Use read for file questions.",
)
```

`user_text_prompt` 是 `ModelRequest` 提供的类方法，用来方便地创建用户文字消息。在这个版本中，它相当于构造：

```python
from pydantic_ai.messages import ModelRequest, UserPromptPart

request = ModelRequest(
    parts=[UserPromptPart(content="用 read 读取 README.md 并概括目标。")],
    instructions="You are Zeta. Use read for file questions.",
)
```

上面两段是两种等价写法，不是让你往历史里添加两次。

`instructions` 是程序给模型的行为要求；用户问题在 `UserPromptPart.content`。read 的文件正文随后属于工具结果内容。数据来自文件，不会因为被拼进消息就获得程序指令的权限。

此时历史只有一条：

```text
[用户消息]
```

### 7.2 第二步：发出第一次模型请求

`run_loop` 经由 `runtime.io.request(...)` 调用 `request_once(...)`，它再调用 PydanticAI 的 `model_request(...)`。

输入包括历史和工具定义。假设响应是第 4.3 节那样的工具调用，循环会把完整 `ModelResponse` 加入历史：

```text
[用户消息, 模型工具调用消息]
```

模型只是要求读文件，文件还没有被读取。文字“我读完了”也不等于工具执行记录。

### 7.3 第三步：执行本地工具

程序检查调用、预算和参数，再执行 `read_file`。假设成功，得到带 `call_001` 的 `ToolReturnPart`。

`runtime.on_result(execution)` 先记录执行对象，`runtime.after_turn(results)` 再把本批结果包装成一条请求消息：

```text
ModelRequest(
    parts=[ToolReturnPart(tool_name="read", tool_call_id="call_001", content=正文)],
    instructions=INSTRUCTIONS,
)
```

此时历史为：

```text
[用户消息, 模型工具调用消息, 程序工具结果消息]
```

**ToolReturnPart 放在 ModelRequest 一侧。** 因为这是程序提供给模型的输入，哪怕内容不是用户亲自写的。

### 7.4 第四步：发出第二次模型请求

把上述三条消息一起送给模型。模型看到原始问题、它发起的工具调用、对应的读取结果，才有依据生成回答。

假设这次得到只有 `TextPart` 的完整响应，循环把它加入历史，最终返回文字：

```text
[用户消息, 模型工具调用消息, 程序工具结果消息, 模型最终文字消息]
```

两次请求是同一个 `run_loop` 的两轮，不需要写两个 `run_agent`。

### 7.5 一轮有多个调用时

如果一个响应里有两个 `ToolCallPart`，Day 1 先执行两个调用，把两个结果收集到 `results`，然后加入同一条 `ModelRequest`：

```text
ModelResponse.parts = [read 调用 call_001, read 调用 call_002]
ModelRequest.parts  = [read 结果 call_001, read 结果 call_002]
```

在 Day 1 的实现里，这两个工具通过 `for` 逐个执行，**没有并发执行**。必须补齐这一批调用的结果，才允许发起下一次模型请求。

## 8. response.state 和 finish_reason：两个问题，两套值

这两个属性非常容易写混，应该分开问：

- `state`：这个响应对象处于什么完成状态？
- `finish_reason`：模型这一轮生成为什么结束？

### 8.1 本地 2.37.0 的 state

| 值 | 含义 | Day 1 如何处理 |
| --- | --- | --- |
| `"complete"` | 这一份响应已完成 | 再检查结束原因和内容 |
| `"incomplete"` | 响应尚未完整，例如流式途中或提前停止 | 拒绝执行工具 |
| `"suspended"` | 模型暂停，期待后续继续 | 当前简单循环没有实现这类续传，拒绝 |
| `"interrupted"` | 生成被显式中断 | 拒绝 |

`state` **没有 `"stop"` 这个合法值**。

### 8.2 本地 2.37.0 的 finish_reason

| 值 | 含义 | Day 1 如何处理 |
| --- | --- | --- |
| `"stop"` | 模型正常结束本轮生成 | 检查工具调用；无调用时还要求非空文字 |
| `"tool_call"` | 本轮结束于工具调用 | 提取并验证调用 |
| `"length"` | 生成触及长度限制 | 拒绝，不能用可能截断的参数执行工具 |
| `"content_filter"` | 因内容过滤结束 | 拒绝 |
| `"error"` | 以错误原因结束 | 拒绝 |
| `None` | 没有提供结束原因 | 当前 Day 1 保守拒绝 |

这些是 PydanticAI 归一化后的值，不要求与服务商原始 JSON 的字符串完全一致。例如不要把别处见到的 `"tool_calls"` 直接当成这里的 `"tool_call"`。

常见正常组合：

```text
完整文字回答：state="complete", finish_reason="stop"
完整工具调用：state="complete", finish_reason="tool_call"
```

**一份响应完整，不表示整个用户任务已经完成。** 工具调用响应可以是 complete，但 Agent 还要执行工具和请求下一轮。反过来，拿到响应对象也不保证内容适合执行，仍需要检查原因、参数与编号。

### 8.3 对照你当前练习中的写法

阅读本文时，如果你的 `response_calls` 仍写着：

```text
response.state != "stop"
```

这里应该检查的是 `"complete"`。否则正常响应的 state 为 complete，也会被判为不完整。Day 1 参考答案使用的是 complete。

这是属性取值的纠正，不需要换一套函数或重写循环。本次前置知识文档不会修改你的练习源码。

## 9. 模型怎么知道有 read？ToolDefinition 与真正执行工具的区别

模型不会自动知道本机存在 `read_file` 函数。程序需要先描述可以用什么工具，以及每个工具接受什么参数。

现有 `tools.py` 有三层：

| 层 | 名字 | 做什么 |
| --- | --- | --- |
| 参数规则 | `ReadArgs` | read 必须接收怎样的数据 |
| 给模型看的说明 | `ToolDefinition` / `TOOL_DEFINITIONS` | 告诉模型有一个名为 read 的工具及参数格式 |
| 真正执行 | `execute_tool` → `read_file` | 检查名称和参数，读取本地文件，创建返回对象 |

**给出 ToolDefinition 不会自动运行 Python 函数。** 在 Zeta 使用的 direct API 路线里，执行动作由我们自己的循环发起。

### 9.1 ReadArgs 和 Pydantic

```python
from pydantic import BaseModel, ConfigDict, Field


class ReadArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(min_length=1, description="UTF-8 file path inside the workspace")
```

这是现有参数模型的核心结构：

- `BaseModel`：Pydantic 的基类，继承后获得数据校验等能力。
- `path: str`：预期有一个字符串字段 path。
- `Field(min_length=1, ...)`：字符串至少一个字符；description 描述字段用途。
- `extra="forbid"`：拒绝额外字段，例如模型无故加一个 `command`。
- `strict=True`：启用严格校验，不应依靠宽松转换把错误类型凑成可用参数。

`min_length=1` 不是文件安全检查：空格也占字符，路径是否存在、是否越界仍由 `read_file` 处理。

### 9.2 args 为什么可能是字符串，也可能是字典

下面两种形式表达的参数信息相同，但 Python 类型不同：

```text
字典：{"path": "README.md"}
字符串：'{"path": "README.md"}'
```

第二种外层有引号，里面是 JSON 文本。真实适配结果或手动构造对象都可能采用不同表示；库的 `ToolCallPart.args` 类型允许 `str | dict[str, Any] | None`。

因此 `execute_tool` 区分两条路径：

| 调用 | 输入 | 成功结果 |
| --- | --- | --- |
| `ReadArgs.model_validate_json(call.args)` | JSON 字符串 | ReadArgs 对象 |
| `ReadArgs.model_validate(call.args)` | Python 数据，例如字典 | ReadArgs 对象 |

有了 ReadArgs 对象，就用 `args.path` 读取已经校验过的路径字段。非法 JSON、缺少 path、path 类型错误或多出字段会导致 `ValidationError`。

`call.args_as_dict()` 是库提供的参数转换便捷方法，**不能替代 ReadArgs 对工具参数规则的校验**。本地版本默认还会宽容地包装某些坏 JSON；Day 1 执行工具使用上述明确的校验路径。

### 9.3 model_json_schema() 是给模型看的结构说明

`ReadArgs.model_json_schema()` 生成 JSON Schema，大致表达：

```json
{
  "type": "object",
  "properties": {
    "path": {"type": "string", "minLength": 1}
  },
  "required": ["path"],
  "additionalProperties": false
}
```

这是省略标题和描述字段后的结构示意，不是声称完整打印结果只有这些键。

`ToolDefinition(name="read", ..., parameters_json_schema=...)` 把名称、描述和结构说明组合起来。`TOOL_DEFINITIONS` 是按名称保存这些定义的字典；`.values()` 取出定义对象，`list(...)` 把它们组成列表。

工具定义中的 `strict=False` 与 `ReadArgs` 的 `strict=True` 控制不同层：前者涉及服务商工具 schema 的严格模式，后者是本地 Pydantic 数据校验。给模型的参数说明不会免除本地校验和权限检查。

### 9.4 read_file 中暂时需要认识的标准库操作

| 操作 | 在本项目中的用途 |
| --- | --- |
| `Path(...)` / `Path.cwd()` | 表示路径 / 得到当前工作目录 |
| `workspace.resolve(strict=True)` | 解析实际路径并要求路径存在 |
| `root / args.path` | Path 重载的路径拼接，不是数字除法 |
| `target.is_relative_to(root)` | 判断解析后的目标是否位于根目录内 |
| `relative.parts` | **路径组件元组**，例如 `("src", "zeta", "tools.py")` |
| `target.is_file()` | 是否为普通文件 |
| `with target.open("rb") as file` | 用二进制模式打开文件，并在离开代码块时关闭 |
| `file.read(MAX_READ_BYTES + 1)` | 多读一个字节来识别是否超过上限 |
| `data.decode("utf-8")` | 将字节解码成正文字符串 |

注意这里又出现了 `.parts`：**`Path.parts` 是路径的部分，`ModelResponse.parts` 是消息的部分。** 属性名字可以相同，实际含义由左边对象的类型决定。

## 10. model_request、request_once、ModelRequest 为什么长得这么像

这三个名字分别属于不同层：

| 名字 | 种类 | 含义 |
| --- | --- | --- |
| `ModelRequest` | PydanticAI 类 | 一条输入消息的数据容器 |
| `model_request` | PydanticAI 异步函数 | 发送一次模型请求并返回 ModelResponse |
| `request_once` | Zeta 异步函数 | 为 model_request 配好本项目模型设置和工具定义 |

真实调用关系是：

```text
run_loop
  调用 runtime.io.request
    默认指向 request_once
      调用 PydanticAI 的 model_request
        通过模型适配器与服务商通信
```

### 10.1 模型对象是什么

`create_model()` 返回 `OpenAIChatModel("deepseek-chat", provider="deepseek")`。

- `"deepseek-chat"` 是模型名称。
- `provider="deepseek"` 指明服务商配置。
- `OpenAIChatModel` 是使用兼容 OpenAI Chat Completions 格式的模型适配类，类名不意味着这里请求 OpenAI 服务商。
- 模型对象负责适配通信；创建对象可能进行配置检查，但不等于已经完成了一次模型生成。

CLI 通过 `load_dotenv(override=False)` 加载本地 `.env` 配置，已有环境变量优先。本文不需要读取或展示你的密钥。

### 10.2 一次请求的三个输入层次

配套 `request_once` 调用中：

| 参数 | 例子 | 用途 |
| --- | --- | --- |
| `model` | create_model 返回的对象 | 找哪个模型、通过哪个服务商通信 |
| `history` | `Sequence[ModelMessage]` | 模型本轮看到的历史内容 |
| `model_settings` | timeout、max_tokens | 超时与生成长度等请求设置 |
| `model_request_parameters` | ModelRequestParameters(...) | 工具定义等模型请求能力参数 |

`function_tools` 是“这次允许模型请求调用哪些函数工具”的描述列表。它没有直接把函数体交给远程模型执行。

`max_tokens` 中的 token 是模型处理文本的计量单位，不等于一个汉字或一个英文单词；这个参数限制生成输出，不是请求次数，也不是整个 Agent 的全部费用上限。

`model_request` 只完成一次请求。它返回 `ToolCallPart` 后，不会替 Zeta 自动执行 read 并完成后续循环。

### 10.3 response 还有哪些暂时不用背的属性

除了 parts、text、state、finish_reason，响应还有 `usage`、`model_name`、`timestamp`、服务商相关字段等。

- `usage`：本次请求的用量对象，例如 `input_tokens`、`output_tokens`。手工构造对象有默认值，不能把默认值当成实际计费证据。
- `model_name`：模型名称信息，可能为 None。
- `timestamp`：响应记录时间。
- `provider_response_id`：服务商响应编号，与某一次工具的 tool_call_id 不同。

Day 1 不必全部处理，但保存完整 ModelResponse 可以保留这些信息。只保存文字会丢失结构和关联数据。

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
| `history` | `[]` | 保存 ModelRequest / ModelResponse |
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
| `Callable[[], OpenAIChatModel]` | 不接收参数、返回模型对象的可调用对象 |
| `Awaitable[ModelResponse]` | 可以 await，等待结果是 ModelResponse |
| `Protocol` | 描述需要满足的接口形状，帮助类型检查 |
| `RequestFn.__call__` | 规定 request 可调用对象应该接受哪些参数、返回什么 |
| `Literal["completed", ...]` | 只允许列出的几个字面量值 |
| `type RunStatus = ...` | 给一组类型规则起一个别名，不是在创建运行状态对象 |
| 签名中的 `/` | 前面的相应参数仅按位置传入 |
| 签名中的 `*` | 后面的相应参数必须用名字传入，如 `max_tokens=2048` |

你在 Day 1 不需要实现自己的 Protocol 框架。先理解这里提前约定了函数如何接入，以后替换能力时就能保持循环不变。

### 11.5 Callable 和 Awaitable：函数、调用结果、等待后的结果

正确拼写是 **`Callable`** 和 **`Awaitable`**。它们在这里从 Python 标准库 `collections.abc` 导入，不是 PydanticAI 独有的类型。

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
| `Callable[[], OpenAIChatModel]` | `fn()` | 一个模型适配对象 |
| `Callable[[str], Awaitable[str]]` | `fn("请概括这段内容")` | 一个可等待对象，成功 await 后才得到字符串 |

例如 `Callable[[int, int], int]` 表示接收两个整数参数，不是接收一个含有两个整数的列表。空列表 `[]` 表示不需要传参数。

**Awaitable[T] 表示“可以使用 await 等待，并在成功完成后得到 T 类型结果的对象”。** `T` 在这里是占位写法：换成 `str`，等待后得到字符串；换成 `ModelResponse`，等待后得到模型响应。

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

`RequestFn.__call__` 使用普通 `def ... -> Awaitable[ModelResponse]` 描述接口，也是为了表达调用后直接得到可等待对象。它的函数体是 `...`，只声明接口；实际默认实现是 `request_once`。

#### 对照 ModelIO 的三个字段

| 字段 | 保存的默认函数 | 调用方式 | 成功取得的结果 |
| --- | --- | --- | --- |
| `factory` | `create_model` | `runtime.io.factory()` | 直接得到 OpenAIChatModel |
| `request` | `request_once` | `await runtime.io.request(model, messages, max_tokens=2048)` | 等待后得到 ModelResponse |
| `summarize` | `summarize_once` | `await runtime.io.summarize(prompt)` | 等待后得到 str |

`factory()` 返回的模型对象可以用于 `async with` 管理资源，但这不意味着 `factory()` 本身要 await。**能够异步管理资源与能够被 await，是两种不同的接口能力。**

最后区分大小写：`Callable[...]` 用来写类型注解；Python 内置函数 `callable(obj)` 用来询问对象能否被调用，返回布尔值。后者不会验证参数签名和返回类型，也不会执行那个对象。

### 11.6 ToolExecution 又是什么

`ToolExecution` 是 **Zeta 自己的 dataclass**，不是 PydanticAI 的另一种 Part：

```text
ToolExecution
  raw：工具原始结果 ToolReturnPart
  result：最终采用的结果 ToolReturnPart
```

Day 1 的两个字段内容相同，但 raw 使用深复制，保留独立对象。Day 2 有结果处理 Hook 后，才更需要区分原始结果与最终结果。

因此 `execution.result` 是一个 ToolReturnPart，而 `execution.result.content` 才是结果正文。发送给模型的是结果消息，不是直接把 ToolExecution 当成消息发送。

## 12. Runtime 的方法：循环固定，每个位置做什么

这些名字是 Zeta 自己定义的接入约定，不是框架要求你必须这样命名。

| 调用位置 | Day 1 默认做什么 | 产生的数据变化 |
| --- | --- | --- |
| `start(prompt)` | 检查输入，创建用户消息 | history 增加用户输入，started=True |
| `begin_turn()` | 暂无额外动作 | 默认不改变历史 |
| `prepare()` | deepcopy 当前 history | 返回本轮可读取的历史副本 |
| `on_response(response)` | 保存完整模型响应 | history 增加 ModelResponse |
| `execute(call)` | 调用基础 execute_tool | 返回 ToolExecution |
| `on_result(execution)` | 保存执行记录 | executions 增加一项 |
| `after_turn(results)` | 有结果时统一包装为请求消息 | history 增加带 ToolReturnPart 的 ModelRequest |
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

意思是：执行请求并等待完成，完成后把 ModelResponse 保存为 response。等待网络期间，事件循环可以安排其他可运行的异步任务。

**await 不会自动创建多个 Agent，也不会让一个 for 循环自动并行。** Day 1 仍然按代码顺序等待请求、执行工具、收集结果。

普通 `read_file` 是同步函数。基础 Runtime 在异步方法中直接调用它，不会因此自动变成后台线程；这是小文件只读起点的实现边界。

### 13.2 asyncio.run 是入口桥梁

CLI 的普通函数 `main()` 不能直接写 await，因此使用：

```text
asyncio.run(run_agent(prompt, Path.cwd()))
```

它创建并管理事件循环，执行这个顶层协程，取得返回值。已经在异步函数内部时继续使用 await，不要在里面再嵌套 asyncio.run。

### 13.3 with 和 async with

普通 `with` 常用于文件打开与关闭。`async with` 则让资源进入和退出过程可以异步等待。

`async with runtime.io.factory() as model`：先由 factory 创建模型适配对象，再进入其异步资源上下文，使用期间命名为 model，退出时按适配器约定管理客户端资源。

`async with asyncio.timeout(runtime.options.timeout)`：为里面的运行步骤设置时间范围。超时时，取消在异步可响应位置发生，退出这个 timeout 上下文时通常表现为 TimeoutError。

异步超时不是操作系统强制杀线程；阻塞的同步操作可能不能立即中断。Day 1 的 finally 清理位于这个总运行 timeout 块之外；Hook 的终态通知另有自己的限制，不能笼统地声称所有自定义清理都被同一个 timeout 包住了。

## 14. 逐行读 response_calls：从一份响应提取工具调用

这个函数来自 Zeta，职责是：检查响应是否适合消费，返回其中的工具调用列表。它不执行工具，不发模型请求。

### 14.1 先排除不完整或异常结束的响应

```text
if response.state != "complete" or response.finish_reason not in ("stop", "tool_call"):
    raise UnexpectedModelBehavior("incomplete model response")
```

`or` 表示只要任意一项不满足，就拒绝。这是当前练习的保守策略，并不是对所有模型、所有应用的唯一通用策略。

`UnexpectedModelBehavior` 是 PydanticAI 提供的异常类。这里由我们的校验主动抛出，表示结果不满足当前循环预期。

### 14.2 从混合片段中筛出 ToolCallPart

```text
calls = [part for part in response.parts if isinstance(part, ToolCallPart)]
```

这是列表推导式，按下面顺序理解：

1. `for part in response.parts`：依次拿到每个片段。
2. `if isinstance(...)`：只保留工具调用类型。
3. 最前面的 `part`：把原来的那个对象放进新列表。

它与下面的展开写法表达同样的筛选逻辑：

```text
calls = []
for part in response.parts:
    if isinstance(part, ToolCallPart):
        calls.append(part)
```

结果是 `list[ToolCallPart]`。如果只有文字，得到 `[]`；如果文字加两个工具调用，得到只含那两个工具调用的列表。这里没有深复制工具对象。

### 14.3 取出编号，检查空白和重复

```text
ids = [call.tool_call_id for call in calls]
```

对两个调用，结果可能是 `['call_001', 'call_002']`。

```text
any(not value.strip() for value in ids)
```

对每个编号去掉两端空白，再看是否为空。`""` 和 `"   "` 都不合格。检查不会自动把合法 ID 改写为 strip 后的版本。

```text
len(ids) != len(set(ids))
```

例如 `['call_001', 'call_001']` 原长 2，去重后长 1，说明同批有重复编号。

### 14.4 没有工具调用时，必须有可用最终文字

```text
if not calls and (
    response.finish_reason != "stop" or not (response.text or "").strip()
):
    raise UnexpectedModelBehavior("missing final text")
```

只有 `calls` 为空才进入这项最终回答检查。`response.text or ""` 把 None 统一为可 `.strip()` 的字符串；去掉空白后仍为空，就没有可用文字。

最后 `return calls`：有调用返回调用列表；正常最终回答返回空列表。这个设计让 run_loop 用同一返回值决定“执行工具继续”还是“返回最终回答”。

## 15. 逐行读 validate_history：pending 是“还欠着哪些结果”

工具调用与结果是关联记录。发起下一次模型请求之前，不能把缺一半的历史发过去。

### 15.1 pending 字典长什么样

```text
pending: dict[str, str] = {}
```

键是工具调用编号，值是工具名称。两个调用进入后：

```text
{
    "call_001": "read",
    "call_002": "read"
}
```

它只记录“哪个调用还没看到结果”，不记录文件正文，也不代表工具正在后台运行。

### 15.2 看见模型响应时，把调用登记进去

```text
if isinstance(message, ModelResponse):
    if pending:
        raise ValueError("assistant response before complete tool results")
    for call in response_calls(message):
        pending[call.tool_call_id] = call.tool_name
```

如果上一批 pending 还没清空，就先出现下一条模型响应，说明中间缺结果，所以拒绝。

然后调用已经写好的 `response_calls`，不用再复制一遍响应校验。每个工具调用登记为“欠一条结果”。文字最终响应返回空列表，自然不会登记任何调用。

### 15.3 看见请求消息时，逐个核销结果

Day 1 参考答案的另一个分支是：

```text
else:
    for part in message.parts:
        if isinstance(part, ToolReturnPart):
            if pending.get(part.tool_call_id) != part.tool_name:
                raise ValueError("unmatched tool result")
            del pending[part.tool_call_id]
        elif pending:
            raise ValueError("message inserted inside a tool batch")
```

逐步理解：

- 此处 `else` 对应外层 `if isinstance(message, ModelResponse)`。在合法 ModelMessage 范围内，它处理的是 **ModelRequest**。
- 遇到工具结果，按它的编号在 pending 查名称。
- 找不到编号时 get 返回 None，与工具名称不相等，拒绝。
- 编号找到了但工具名称不匹配，也拒绝。
- 编号和名称对应，删除 pending 中这一项，表示已经收到结果。
- 若还欠工具结果，却插入其他普通片段，就拒绝破坏这个批次。

**缩进决定这段代码在处理谁。** 不能把遍历 ToolReturnPart 的循环缩进到 ModelResponse 分支里；本地 read 的 ToolReturnPart 在 ModelRequest 中，否则你检查不到真正的工具结果。

### 15.4 用完整历史手动跟踪字典

| 正在读到的内容 | pending 处理前 | 做什么 | pending 处理后 |
| --- | --- | --- | --- |
| 用户输入 UserPromptPart | `{}` | 没有欠结果，允许 | `{}` |
| 模型调用 call_001/read | `{}` | 登记 | `{'call_001': 'read'}` |
| 工具返回 call_001/read | `{'call_001': 'read'}` | 配对并删除 | `{}` |
| 模型最终 TextPart | `{}` | 没有调用，不登记 | `{}` |

末尾 `if pending: raise ...` 表示：所有历史都读完了仍欠结果，不能发送。

以下情况也会被拒绝：只有结果没有调用；相同结果重复出现；结果名称错误；只补齐两个调用中的一个。

这个函数成功时返回 None，因为它的工作是“允许继续或抛错”，不用产出新的历史。

### 15.5 为什么在这个位置校验

工具调用响应刚加入 history、工具还没执行完的短暂阶段，history 有 pending 是正常的。Day 1 在下一次模型请求前校验，要求那时必须完整。

一旦预算耗尽或工具失败，运行可以带着未完成批次停止，但不能把它当成可直接续发的完整历史。之后 Session 的恢复单元才处理这种状态；校验函数不会自动替你重放工具。

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

`while runtime.requests < runtime.options.max_requests` 控制最多尝试几次请求。这里的次数不是 message 条数，也不是 parts 数量。

### 16.3 发请求并处理允许的重试

`response = await runtime.io.request(...)` 返回一份 ModelResponse。

`except ModelHTTPError as error` 捕获模型服务 HTTP 错误。只有还有请求额度且 `runtime.retry(error)` 返回 True，才执行 continue 重新进入循环。Day 1 默认 retry=False，所以不是“任何错误自动重试”。Day 7 才加入特定上下文超长的压缩重试策略。

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
results: list[ToolReturnPart] = []
for call in calls:
    execution = await runtime.execute(call)
    await runtime.on_result(execution)
    results.append(execution.result)
await runtime.after_turn(results)
```

每轮 results 都是新列表，只装本轮工具结果。保存执行记录与添加发给模型的历史是两个动作，不能以为 on_result 默认已经把 history 补齐。

执行完一批后，while 自然继续下一轮，模型就会看到新增的工具结果消息。

### 16.6 最终文字与终态

没有调用时，前面的 response_calls 已确认有可用文字。循环设置 `status="completed"`，返回 `response.text or ""`。

本代码中的状态名称属于不同对象：

| 名字 | 例子 | 回答什么问题 |
| --- | --- | --- |
| `response.state` | `"complete"` | 这份模型响应是否完整？ |
| `response.finish_reason` | `"stop"` | 这一轮生成为什么结束？ |
| `status: RunStatus` | `"completed"` | 整次 Zeta 运行最后怎样结束？ |
| `ToolReturnPart.outcome` | `"success"` | 这一次工具执行怎样结束？ |

注意 `complete` 与 `completed` 不是随意混用的两个拼法，它们属于不同字段的不同约定。

## 17. 异常、取消、finally 和日志

### 17.1 异常不是普通返回值

函数可以正常 `return`，也可以 `raise` 抛异常。抛异常后，Python 会离开当前普通执行路径，向外寻找匹配的 except；找不到就继续向上传播。

| 异常 | 来源 | 在 Day 1 中的用途 |
| --- | --- | --- |
| `ValueError` | Python | 参数、历史配对等不符合约定 |
| `UnexpectedModelBehavior` | PydanticAI | 响应内容不符合循环预期 |
| `ModelHTTPError` | PydanticAI | 模型服务 HTTP 错误，可读取 status_code 等信息 |
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
| `loop_common.py: response_calls` | 响应内哪些片段是调用，响应是否可消费？ |
| `loop_common.py: validate_history` | 已有调用是否都有对应结果？ |
| `runtime_base.py: Runtime` | 历史、计数器放在哪，各步骤如何改变它们？ |
| `model_io.py: request_once` | 用什么工具定义和设置发送一次请求？ |
| `tools.py: execute_tool` | 怎样从 ToolCallPart 选工具并校验参数？ |
| `tools.py: read_file` | 哪一行真正读取了本机文件？ |

这些位置描述的是 Day 1 和 support.md 组合后的目标代码。有些文件可能尚未由你在 src 中准备完成；文档有完整代码不代表当前 CLI 已经跑通。

CLI 中暂时需要认识的补充名字：`argparse.ArgumentParser` 定义命令行参数；`parse_args()` 读取参数；`cast(str, args.prompt)` 提供类型提示而不是执行字符串转换；`parser.exit(...)` 显示错误并退出；`__version__` 是项目版本变量。`prompt` 是用户输入字符串，`workspace` 是本地工具工作的目录。

`run_agent` 中的 `runtime=None` 表示可不传自定义 Runtime；`active = runtime if runtime is not None else Runtime(workspace)` 表示“传了就用，否则创建默认对象”。这个入口不需要随学习天数改写，后续传入新增的 Runtime 子类即可。

support.md 还提供了 SQLite 存储和摘要函数。它们主要在后续单元使用，读 Day 1 时先认识入口，不需要先掌握数据库事务和压缩算法。`summarize_once` 是无工具的单次模型请求，不会在默认 Day 1 循环中自动触发。

## 19. 遇到一个陌生表达式时，按这个顺序拆

以 `results.append(execution.result)` 为例：

1. 左边 results 是什么类型？——本轮 ToolReturnPart 列表。
2. append 是属性还是方法？——带括号，是列表的方法。
3. 括号里的 execution 是什么？——ToolExecution 对象。
4. execution.result 又是什么？——最终采用的 ToolReturnPart。
5. 整句有什么效果？——把一个结果对象放入列表，尚未发送给模型。

常用名字速查：

| 名字 | 先记这一句 |
| --- | --- |
| `message` | 历史中的一条消息，可能是请求或响应 |
| `messages` / `history` | 多条消息组成的序列，前者常是当前视图，后者常是保存的历史 |
| `response` | 一次模型返回的 ModelResponse 对象 |
| `parts` | 某个对象的组成部分；消息 parts 和路径 parts 不能混用 |
| `part` | 正在遍历的一段内容，要先看具体类型 |
| `calls` | 从本轮响应筛出的 ToolCallPart 列表 |
| `call` | 某一次具体工具调用的数据 |
| `tool_name` | 调用哪个工具 |
| `tool_call_id` | 这次调用的编号，结果原样带回 |
| `args` | 调用输入参数，可为 JSON 文本或 Python 字典等 |
| `content` | 内容；具体是问题、文字还是工具正文，要看所属 Part 类型 |
| `result` | 这里通常指一个工具结果对象，注意具体函数的类型注解 |
| `results` | 本轮工具结果列表 |
| `execution` | Zeta 保存的原始/最终工具结果组合 |
| `pending` | 历史扫描时仍未找到结果的调用编号与名称 |
| `runtime` | 保存运行状态并提供各步骤方法的对象 |
| `options` | 本次运行的额度和时限配置 |
| `io` | 保存模型创建/请求函数的配置对象 |
| `state` | 模型响应的完整状态 |
| `finish_reason` | 模型这一轮结束生成的原因 |
| `status` | Zeta 整次运行的终态 |
| `outcome` | 某次工具的处理结果 |

这些小写变量名多数是程序作者起的，不能只靠名字猜类型。优先看它在哪里赋值、函数签名怎么写、类里声明了什么字段。

读回 Day 1 时，只要能顺着说出下面这段话，就有了开始写代码的基础：

> 我先把用户输入包装成 ModelRequest。一次模型请求返回 ModelResponse，它的 parts 可能有文字和工具调用。我筛出 ToolCallPart，验证它的名称、参数和编号，由本地代码执行工具。执行结果包装成同编号的 ToolReturnPart，放入新的 ModelRequest。把完整历史再发给模型，直到获得没有工具调用的有效最终文字，或者触发明确的停止条件。

## 20. 资料依据与后续查阅

本篇字段和值已对照本地安装源码：

- [PydanticAI 消息定义源码](../.venv/lib/python3.14/site-packages/pydantic_ai/messages.py)：ModelRequest、ModelResponse、各 Part、state 和 finish_reason、text 属性。
- [PydanticAI direct 源码](../.venv/lib/python3.14/site-packages/pydantic_ai/direct.py)：单次 model_request 的入口。
- [项目现有工具实现](../src/zeta/tools.py)：ReadArgs、工具定义、参数校验和 read_file。
- [Day 1 参考代码](day1.md) 与 [固定基础代码](support.md)：Zeta 自己的 Loop、Runtime、配置和异常约定。

线上官方资料用于交叉核对消息分类和单次请求入口，可能比本项目安装版新；尤其不要直接把新版工具返回字段搬进 2.37.0：[消息 API](https://pydantic.dev/docs/ai/api/pydantic-ai/messages/)、[direct API](https://pydantic.dev/docs/ai/api/pydantic-ai/direct/)。本篇详细字段解释以本地源码为依据。
