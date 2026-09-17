# Hook 到底是干什么的：配合 Day 2 阅读

[返回 Day 2 练习与注释答案](day2.md)

**Hook 就是程序在某个执行位置，主动调用你提前注册的函数，让你在这里检查数据、处理数据，或决定是否继续。**

在 Zeta 里，例如读取文件之前，程序先调用你写的检查函数。检查允许，就继续读取；检查拒绝，就返回拒绝结果。这段检查逻辑就是一个 Hook 回调。

本文解释的是 Day 2 的完整参考答案。`src/zeta` 中的练习实现可能还没写完，文档里的调用流程不代表当前练习已经全部可运行。

## 1. 为什么需要它

假设循环原来做三件事：请求模型、执行模型要求的工具、把工具结果交回模型。

现在你想增加两个功能：读取前检查路径，读取后隐藏内容中的敏感信息。可以直接把这些逻辑写进循环，但以后换检查规则、加一种处理方式，又要改循环。

Hook 把“什么时候执行扩展逻辑”和“扩展逻辑具体做什么”分开：

- 循环和调度器规定位置：请求前、读取前、读取后。
- 你写回调函数，规定这个位置做什么。
- `Hooks` 保存回调，到指定位置按顺序执行，检查返回值是否合法。

因此，可以为不同运行传入不同的策略，同时复用同一个循环。前提是循环已经预留接入位置；给一个任意名称注册函数，不会凭空产生新的执行位置。

## 2. 先分清函数、方法和对象

普通函数定义在类外，例如 `execute_tool(...)`。方法定义在类里面，例如 `Hooks.register(...)`。调用 `hooks.register(...)` 时，Python 会把 `hooks` 这个实例自动作为方法的 `self` 传进去。

| 写法 | 实际含义 |
| --- | --- |
| `Hooks` | 类，描述回调管理器如何创建和工作 |
| `hooks = Hooks()` | 创建一个管理器对象；自动执行 `__init__`，建立空回调列表 |
| `hooks.callbacks` | 这个对象里保存回调的字典 |
| `check_path` | 函数对象本身，可以被保存、传递 |
| `hooks.register("before_tool", check_path)` | 把函数存入指定列表，此刻不检查路径 |
| `check_path(context)` | 调用异步函数，得到协程对象 |
| `await check_path(context)` | 执行并等待协程，成功后拿到回调返回的数据 |
| `await hooks.invoke("before_tool", context)` | 等待这一组回调，拿到管理器检查后的决策 |

`register` 是普通 `def` 方法，不需要 `await`。`invoke` 是 `async def` 方法，需要调用方等待。`async` 不等于自动并发；Day 2 是一个回调执行完，才开始下一个。

`Callable[[HookContext], Awaitable[HookResult]]` 就是把“接收什么、调用后得到什么”写成类型：接收一个上下文，调用后得到可等待对象，等待成功后得到 `HookResult`。它只是类型描述，不会替你执行函数。

## 3. 从一段回调看清谁调用谁

下面是供阅读的策略示例，不是自测程序。它只演示按文件名拒绝 `.env`；它不是完整的文件权限方案，实际路径、符号链接和工作目录边界仍需由工具层校验。

```python
from pathlib import Path

from zeta.hooks import Decision, HookContext, Hooks, ToolContext


async def check_path(context: HookContext) -> Decision:
    # 类型别名覆盖了五种 Hook 的输入，这里确认拿到的是工具上下文。
    if not isinstance(context, ToolContext):
        raise TypeError("check_path needs ToolContext")

    # read 的 args["path"] 是待读取路径，其他工具可以有不同参数。
    if context.name == "read" and Path(context.args["path"]).name == ".env":
        # 返回决策数据；这里没有退出 Agent，也没有直接生成工具结果。
        return Decision(stop=True, reason="不允许读取 .env 文件")

    # 默认 stop=False，表示这个检查没有提出拒绝。
    return Decision()


hooks = Hooks()
# 保存 check_path 函数本身，不加括号，不在注册时执行检查。
hooks.register("before_tool", check_path)
```

之后把这个 `hooks` 传给 `HookRuntime(workspace, hooks=hooks)`，再通过 Day 2 的 `run_agent` 入口运行。`workspace` 是你的实际工作目录 `Path` 对象。

假设模型要求调用 `read`，参数为 `{"path": ".env"}`，调用 ID 为 `call_1`：

1. 循环拿到模型的 `ToolCall`，调用 `await runtime.execute(call)`。
2. `runtime` 是 `HookRuntime` 实例，因此执行 `HookRuntime.execute`，它再调用 `dispatch.execute_tool`。
3. 调度器调用 `resolve_tool_call(call)`，取得执行函数 `handler` 和校验后的参数实例，再用 `args.model_dump(mode="json")` 构造 `ToolContext("read", "call_1", {"path": ".env"})`。
4. 调度器调用 `await hooks.invoke("before_tool", context)`。
5. `invoke` 从列表取出 `check_path`，传入上下文的深拷贝，等待其返回。
6. `check_path` 返回 `Decision(stop=True, reason=...)`。`invoke` 检查理由非空，立即将决策返回给调度器。
7. 调度器看到 `stop=True`，调用 `make_tool_message(call, decision.reason, "denied")`，生成 status="error"、artifact={"outcome": "denied"} 的结果，不调用 `handler`（本例为 `read_file`）。
8. 拒绝结果仍经过 `after_tool`，随后作为 `ToolExecution.result` 交回循环。
9. 循环记录执行结果，发送 `tool_end`；这一批工具处理完后，把结果放进历史，供后续模型请求使用。

**回调返回的是“拒绝建议”，调度器负责实际拒绝。** 此处 `stop=True` 只拒绝本次工具调用，不代表立即终止整个 Agent；同一批后续工具仍可能继续处理。

在 `after_turn` 位置返回同样的停止决策时，则由 `HookRuntime.after_turn` 抛出 `RunStopped`，停止整个运行。返回值含义要连着调用位置一起看。

## 4. 五个位置分别能做什么

| Hook 名称 | 什么时候调用 | 回调收到什么 | 允许返回什么 | 典型用途 |
| --- | --- | --- | --- | --- |
| `before_model` | 本轮消息已准备好，模型请求发出前 | 消息列表快照 | 新消息列表或 `None` | 补充检索到的资料 |
| `after_model` | 完整模型响应已写入历史后 | `AIMessage` 快照 | 只能 `None` | 观察模型响应、统计信息 |
| `before_tool` | 工具名与参数校验通过、实际执行前 | `ToolContext` 快照 | `Decision` 或 `None` | 决定本次工具是否放行 |
| `after_tool` | 成功、失败或拒绝结果生成后 | `ToolMessage` 快照 | 新工具结果或 `None` | 截断、脱敏结果内容 |
| `after_turn` | 本轮工具结果已补齐到历史后 | 完整历史快照 | `Decision` 或 `None` | 按业务条件停止运行 |

表格列的是“你写的回调”允许返回什么。`invoke` 还会统一返回给调用方：变换类返回最终数据，决策类在无人拒绝时返回 `Decision()`，`after_model` 返回 `None`。

这里的限制是 Day 2 主动定义的契约，不是所有项目的 Hook 都必须如此：

- `before_model` 只能在已有消息之前增加用户级数据；不能删改已有消息，新增消息只能是非空 HumanMessage，不能插入 SystemMessage，也不能夹带工具结果。它补充的是本次请求视图，不会自动改写 `history`。
- `after_tool` 必须保留 `name`、`tool_call_id`、`status`、`artifact`。不能把失败伪装成成功，也不能让结果对应到别的调用。
- `after_model` 只能观察，不允许提交替换响应。
- 回调异常会向外传播；错误不会自动变成“放行”，也不会被包装成普通工具失败。

即使内容可做脱敏，Day 2 仍保留 `raw` 原始结果。修改 `result` 不会自动清除 `raw` 里的原文。

## 5. `invoke` 为什么要复制两次

读答案时可以把三个变量这样理解：

| 变量 | 它是谁 |
| --- | --- |
| `context` | 调用方传入的原始输入 |
| `current` | 本次回调链目前正式采用的数据 |
| `result` | 当前这个回调返回、等待检查的数据 |

开始时，`current = deepcopy(context)`，先隔开调用方的数据。每次调用回调时，再把 `deepcopy(current)` 传进去，隔开回调和管理器当前采用的数据。

例如 `after_tool` 注册了 A、B 两个回调：A 收到原结果的副本，返回截断后的结果；管理器检查通过后更新 `current`，B 收到的就是截断后结果的副本，可以继续脱敏。

如果 A 只修改自己收到的副本，却返回 `None`，管理器会忽略这次修改，B 仍收到原来的内容。**想提交修改，必须返回符合该 Hook 契约的数据。**

复制隔离的是这些传入的数据，不是任意副作用：回调自己写文件或修改外部变量，不会被 `deepcopy` 撤销。`frozen=True` 也只是禁止给数据类字段重新赋值，不是执行沙箱。

## 6. `HookRuntime` 和 `super()` 为什么存在

`Hooks` 只知道“存函数、执行函数”，不知道模型什么时候返回，也不知道工具什么时候运行。`HookRuntime` 负责在循环调用的方法里触发它。

`class HookRuntime(Runtime)` 表示继承。假设创建了一个 `HookRuntime` 实例并传给循环，循环写的是 `await runtime.prepare()`，实际就会进入子类的 `prepare`。

其中这一行：

```text
return await self.apply_before_model(await super().prepare())
```

按从内到外的顺序理解：

1. `super().prepare()` 使用父类的方法实现，操作的仍然是当前这个 `self`。
2. 等待父类方法，拿到包含固定 SystemMessage 和 history 深拷贝的视图。
3. 将列表传给 `self.apply_before_model(...)`，执行 `before_model` 回调链。
4. 等待处理完成，把最终列表返回给循环。
5. 循环再用这个列表请求模型。

`super()` 不会创建第二个运行对象。它使子类可以复用父类已有动作，再增加本日行为。例如 `on_response` 先用父类保存响应，再执行 Hook；`on_result` 先记录执行，再发事件。

## 7. Hook 和 Event 有什么区别

**Hook 的返回值可以被程序用于处理数据或作决策；Event 用来通知观察者某件事发生了。**

`before_tool` 回调说“拒绝”，调度器就不读取。`tool_end` 监听器可以打印状态、更新界面，但 `emit` 不读取监听器返回值，不能借它批准工具或修改工具结果。

| 代码对象 | 职责 |
| --- | --- |
| `Event` | 保存事件名、补充信息、调用 ID |
| `emit` | 依次等待监听器，普通异常记日志后继续 |
| `finish_event` | 发送 `run_end`，为结束通知设置异步超时 |

监听器仍然需要 `await`，所以不是自动后台运行。普通异常被隔离，但取消会向外传播。异步超时也依赖协作取消，不能强行打断监听器中的同步阻塞代码。

一个成功读取工具的正常轮次顺序为：

```text
turn_start 事件
→ before_model Hook
→ 请求模型
→ 保存模型响应
→ after_model Hook
→ model_response 事件
→ resolve_tool_call 查找参数模型和执行函数并校验参数
→ before_tool Hook
→ tool_start 事件
→ 执行 handler，本例为 read_file
→ make_tool_message 包装正文，生成 raw
→ after_tool Hook，得到 result
→ 保存 ToolExecution 执行记录
→ tool_end 事件
→ 将本轮全部工具结果补齐到 history
→ turn_end 事件
→ after_turn Hook
→ 若未停止，进入下一轮
```

这描述的是单个工具成功的路径；一轮有多个工具时，中间的工具处理会依次重复。拒绝时没有 `tool_start`，但正常完成处理后仍有 `tool_end`；参数无效时跳过 `before_tool`，生成 failed 后仍走 `after_tool`。无工具的响应也会走 `after_turn`，之后循环才返回最终文字。

整次运行开始时还有 `run_start`，收尾时有 `run_end`。`after_turn` 的停止判断发生在 `turn_end` 通知之后，所以 `turn_end` 表示本轮已处理到收尾位置，不表示已决定继续下一轮。

## 8. 回到 Day 2，该按什么顺序读

先读 `Decision` 和 `ToolContext`，明确传递的数据；再读 `register`，看到函数如何保存。接着读 `execute_tool` 中的 `before_tool` 分支，理解“调用回调、取决策、执行或拒绝”。

理解这一条链之后，再读完整 `invoke` 的返回检查、`after_tool` 的结果串联，最后看 `HookRuntime` 如何接入循环和 `lifecycle.py` 如何通知事件。每个方法都问三个问题：谁调用它、它收到什么、它的返回值由谁使用。

## 9. invoke 的实际回调与逐分支解释

Day 2 的全部类、属性和函数见 [对象对照表](day2.md#先认识本日的类与函数)。本节接着解释参考答案中的 invoke；src 练习是否完成要单独看实际文件。

### 9.1 callback 是你写的函数，result 是它返回的数据

下面是阅读用回调示例，不是新增练习或自测。`add_project_info` 的功能是接收 before_model 消息列表，在前面加一条参考资料，返回新列表。

```python
async def add_project_info(context: HookContext) -> HookResult:
    if not isinstance(context, list):
        raise TypeError("需要消息列表")
    extra = HumanMessage(content="项目资料：本项目使用 uv 管理依赖。")
    return [extra, *context]


hooks = Hooks()
hooks.register("before_model", add_project_info)
```

`[extra, *context]` 把 extra 放在前面，再展开原列表。register 保存 add_project_info 函数本身，没有在注册时调用它。之后 invoke 中取到这个函数时，`result = await callback(deepcopy(current))` 就相当于 `result = await add_project_info(deepcopy(current))`。

`HookResult` 是列表、ToolMessage、Decision、None 的联合类型别名，不是一个 result 类；不写 `HookResult(...)`，而是直接返回具体列表或 `Decision(...)` 等数据。callback 调用产生可等待对象，await 后才取得 return 的数据。共用类型别名只是粗略描述，具体 Hook 分支还要检查更严格的规则。

### 9.2 context 不是固定结构的容器

context 是调用方在那个执行位置提供的数据；不必有 `.messages` 属性。

| 位置 | 输入形状示例 | 回调可返回 |
| --- | --- | --- |
| before_model | `[SystemMessage(content="固定指令"), HumanMessage(content="用户问题")]` | 新消息列表或 None |
| after_model | `AIMessage(content="模型回答")` | 只能 None |
| before_tool | `ToolContext(name="read", call_id="call_123", args={"path": "README.md"})` | Decision 或 None |
| after_tool | `ToolMessage(content="文件正文", name="read", tool_call_id="call_123")` | 新 ToolMessage 或 None |
| after_turn | 包含用户、模型和已补齐工具结果的完整历史列表 | Decision 或 None |

表里的 AIMessage 是为展示形状而简写，不代表省略响应元数据的对象也能通过本项目的完整响应校验。

### 9.3 before_model：原消息必须完整留在尾部

`result[-len(current):]` 取新列表最后 N 条，N 是当前列表长度。`!= current` 检查这些消息是否仍等于原来的消息，保持内容与顺序；比较的是值，不要求仍是同一批对象引用。

```text
current = [系统消息, 用户问题]
result  = [新增资料, 系统消息, 用户问题]

result[-2:] = [系统消息, 用户问题]  → 原有部分，必须等于 current
result[:-2] = [新增资料]            → 新增部分，逐条检查
```

因此，在前面补资料可以通过；修改原问题、交换顺序或把资料追加到后面都会失败。新增部分必须是正文为非空字符串的 HumanMessage。前面的 `not current` 和长度检查先排除空上下文与删除消息，也避免 `-0` 等于 0 时切片含义不同。检查通过才把 result 深拷贝到 current，交给下一个回调。

### 9.4 after_tool：处理结果正文，保留调用身份和状态

这个分支先确认 current 和 result 都是 ToolMessage，再比较两个元组：

```python
(result.name, result.tool_call_id, result.status, result.artifact)
(current.name, current.tool_call_id, current.status, current.artifact)
```

元组不相等表示至少一项变了。name 不能把 read 变成另一种工具；tool_call_id 不能把结果配给另一调用；status 不能把 error 改成 success；artifact 保存的附加结果信息也要原样保留。

例如，回调可以截断 content，返回这份 ToolMessage。检查通过后 `current = deepcopy(result)`，后续回调继续对截断后的结果脱敏。这里明确保护的是上述四个字段；代码没有逐一锁定 ToolMessage 的其他所有字段。

### 9.5 before_tool / after_turn：有人要求停止就提前返回

两类回调返回非 None 时必须是 Decision。`Decision()` 默认 stop=False，表示没有提出拒绝，继续下一个回调；stop=True 时必须带有效 reason。

`reason.strip()` 去掉两端空白；空字符串和全空格都不算理由。有效的停止决策执行 `return result`，会退出整个 invoke，不再执行后面的回调。原因是本课程采用“任一检查拒绝就不放行”的规则，后面的回调不能覆盖已有拒绝。

invoke 只交回数据：before_tool 的调用方据此拒绝本次工具；after_turn 的调用方据此抛 RunStopped 结束运行。不要把两处 stop=True 都理解成立即退出整个 Agent。

### 9.6 after_model：正常情况早已被 None 分支处理

循环开头统一处理了：

```python
if result is None:
    continue
```

所以 after_model 回调观察响应并返回 None 时，直接继续下一个回调；只有返回了非 None 数据才会进入显式的 `elif name == "after_model"` 分支，抛出“只读 Hook 必须返回 None”的错误。源码分支按 `before_model → after_model → before_tool → after_tool → after_turn` 排列，便于对照生命周期。一次 invoke 只处理 name 指定的那种 Hook；实际先后由循环和 Runtime/工具调度器的调用位置决定。

即使回调修改了收到的副本，只要返回 None，管理器也不采用这次修改。复制只能隔离传入的数据，不能撤销回调自己写文件等外部副作用。

### 9.7 for 循环结束后，invoke 自己返回什么

| Hook 类别 | 所有回调执行完后的返回值 | 原因 |
| --- | --- | --- |
| before_tool / after_turn | `Decision()` | 能走到这里说明无人提出有效 stop=True |
| after_model | `None` | 观察类没有替换数据可交回 |
| before_model / after_tool | `current` | 交回已经验证、累积处理后的消息列表或工具结果 |

返回 current 而不是最后一次 result，是因为最后一个回调可能只打印日志并返回 None。前面回调已通过检查的修改仍保存在 current，不应丢弃。`isinstance(current, (list, ToolMessage))` 表示满足两种类型中的任意一种；都不满足则抛 invalid hook context。

即使没有注册任何回调，for 也会跳过并进入这套收尾规则：决策类默认不拒绝，观察类返回 None，变换类返回输入副本。异常没有被 invoke 捕获，因此 callback 出错或任务取消时不会悄悄当作通过。
