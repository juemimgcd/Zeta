# Day 2：工具调度、Hooks 与事件生命周期

[总览](summary.md) · [配套基础代码](support.md)

## 核心问题

模型提出工具请求后，谁决定能否执行？怎样在不改 Loop 主体的情况下加入检查和结果处理？你手写调度、Hook 的控制契约、事件顺序，以及预算和取消边界。

## 已提供与本日范围

- 复用 read_file 和 ReadArgs，不重写文件 I/O 或 JSON 校验库。
- 手写 `src/zeta/hooks.py` 的注册和调用、`tools.py` 的工具调度、`app.py` 的生命周期；`events.py` 承担最小事件发布。
- 只用固定回调列表，不做动态插件发现、热加载或完整扩展框架。事件的终端排版和 JSON 编码直接复用或提供。
- 可选阅读：Pi agent-loop.ts 与 types.ts 的 beforeToolCall、afterToolCall、shouldStopAfterTurn。下列 Hook 名称与约束是 Zeta 的设计，不宣称逐项对应 Pi API。

## 你手写的入口

```python
class Hooks:
    def register(self, name, callback):
        """只允许固定 Hook 名称，按注册顺序保存异步回调。"""
        ...

    async def invoke(self, name, context):
        """逐个 await，检查返回契约；变换类回调接收上一项的新视图。"""
        ...


async def emit(event, listeners):
    """按顺序通知观察者；返回值不参与执行决策。"""
    ...


async def execute_tool(call, workspace, hooks):
    """参数校验 → before_tool → 执行或拒绝 → after_tool → 配对结果。"""
    ...


async def run_agent(
    prompt: str,
    workspace: Path,
    *,
    max_requests: int = 8,
    max_tool_calls: int = 16,
    timeout: float = 120.0,
) -> str:
    """沿用 Day 1 Loop，加入 Hooks、事件和整个 run 的取消边界。"""
    ...
```

以上是入口草图，省略类型和依赖组装；不是完整可运行模块。先定义下面的输入/返回契约，再实现调用器。

### 五个 Hook：在哪运行、能改什么

| Hook | 调用时机 | 最小返回契约与权限 |
| --- | --- | --- |
| before_model | 输入视图准备好之后、实际请求之前 | 返回新的输入视图或不变；不得原地修改原始历史、固定系统约束或工具权限。运行时再次校验配对与预算，Day 5 接入完整 Context 预算 |
| after_model | 完整响应通过协议校验并进入历史之后、工具预检之前 | 只读观察，返回 None；第一版不允许改写模型原文或工具调用 |
| before_tool | 固定工具查找与参数校验之后、实际执行之前 | 返回 allow 或 deny(reason)；拒绝即停止后续放行检查，结果仍带原调用 ID；不能绕过工具本身的工作区限制 |
| after_tool | 得到成功、失败或拒绝结果之后、保存最终结果之前 | 返回受限结果视图或不变；保留原 ID、工具名、状态和原始结果，不得把失败/拒绝改成成功 |
| after_turn | assistant 与全批工具结果已入历史之后 | 返回 continue 或 stop(reason)；任一 stop 即停止，不发下一轮请求 |

没有工具的最终回答也经过 after_model 和 after_turn。after_turn 的 continue 只是允许正常 Loop 规则继续，不能使已经得到最终回答的 Loop 无限追加请求。Hook 停止单独记录原因，不能伪装成模型正常完成。

### Hook 与 Event 的区别

Hook 在指定位置参与处理或决策；Event 通知已经发生的状态变化。两者都按注册顺序串行 await，但 Event 监听器只接收只读快照，返回值被忽略，不得改变权限和消息。

最小事件：run_start、turn_start、model_response、tool_start、tool_end、turn_end、run_end。run_end 携带 completed / stopped / failed / cancelled 与原因，每个 run 只发一次。它表示运行终态已经确定；运行函数还需等监听器处理结束后才返回。

成功路径固定为：

```text
run_start → turn_start
→ before_model → 校验最终输入 → 请求模型 → 校验并保存完整响应
→ after_model → model_response
→ 整批 ID / 预算预检
→ 每个工具：参数校验 → before_tool → tool_start（仅实际执行时）
           → 执行或生成 failed/denied 结果 → after_tool
           → 保存原始结果和最终视图 → tool_end（包括失败和拒绝）
→ 整批结果配齐 → turn_end → after_turn
→ 下一轮 turn_start，或保存终态 → run_end
```

Day 2 的“保存”先指内存状态，Day 3 换成可靠提交；每项结果先放入批次缓冲，齐批再组成 ModelRequest。不能在模型调用与结果之间注入普通消息。未知工具或非法参数直接生成 failed 结果，跳过 before_tool，仍经过 after_tool；无工具回答跳过工具阶段。

### 异常、预算与取消

| 情况 | 处理 |
| --- | --- |
| 工具非法参数、未知名称、文件不可读 | 仅将预期的工具异常转成同 ID 的 failed 结果 |
| before_tool 拒绝 | 不执行，生成同 ID 的 denied 结果 |
| 响应不完整、调用 ID 无效、Hook 返回违反契约 | 停止，不能带残缺批次继续请求 |
| Hook 抛出异常 | 停止并记录 failed；不包装成可让模型重试的工具错误，也不默认放行 |
| Event 监听器抛出普通异常 | 记录监听器诊断，继续通知其他观察者；不撤销已完成的工具，也不重新执行它 |
| 预算耗尽、总超时、取消 | 分别记录停止/失败/取消原因，不继续下一项操作；CancelledError 传播 |

持久化必须由明确的提交步骤负责，不能依赖允许失败的观察性监听器。异常处理应保留原始原因；终态通知不能吞掉取消，也不能让清理阶段的错误覆盖原失败。

次数为正整数，timeout 正且有限；失败和拒绝调用也计数。执行前检查整批工具额度和下一次请求额度。总 timeout 覆盖请求、工具与 Hook 等待；终态通知使用单独的有界清理时间，不能无限等监听器。未预期的程序错误直接传播。

## 怎样算完成

1. 注册实际的 before_tool 策略，拒绝读取 `days/`；让模型请求读取 days/day1.md，确认没有执行、没有 tool_start，存在同 ID 的 denied 结果和 tool_end。
2. 读取 README.md，观察五个 Hook 与事件顺序；after_model 能看见已入历史的完整响应，after_turn 能看见完整工具批次。
3. 手动读取不存在的文件，确认 failed 经 after_tool 后仍为 failed；不得美化为成功。
4. 在 Hook 或模型等待中按 Ctrl-C，确认不继续工具或模型请求。检查 Hook 异常与 Event 异常采用不同处理规则，未实际遇到的分支记为未验证。

不为验收创建测试、mock 或故障注入回调；使用实际策略和调试器观察。能解释 Hook 的执行顺序、修改边界、失败规则，才算完成，而不只是注册了几个函数。

<details>
<summary>卡住再看：参考思路（算法说明，不是完整可运行答案）</summary>

```text
注册：固定名称 → 按注册顺序保存回调
调用：逐个 await → 校验返回值 → 应用该 Hook 专属合并规则
      before_model / after_tool：传递新视图，不传可变原始记录
      before_tool：遇到 deny 即结束权限链
      after_model：仅允许 None
      after_turn：遇到 stop 即结束决策链
Loop：按上面的成功路径安排调用点
      把 Hook 调用放在工具预期异常捕获范围之外
      全批结果配齐后才允许下一次请求
结束：先保存终态，再有界通知 run_end，最后返回或传播原异常
```

同步 read 可用 await asyncio.to_thread；取消等待不能强制终止线程内 I/O，因此此处只用于受限只读工具，不能直接作为 bash 的取消机制。

</details>
