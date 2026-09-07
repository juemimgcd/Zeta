# Day 1：Agent 状态、消息与 Loop

[总览](summary.md) · [配套基础代码](support.md)

## 核心问题

模型调用只返回一次响应。Agent 为什么能反复读文件并继续工作？因为你保存状态、执行工具，再决定是否发下一次请求。

## 已提供与本日范围

- 直接使用 [基础接入](support.md) 和现有 execute_tool；今天先接受工具失败即停止。
- 只改 `src/zeta/app.py` 的核心逻辑；model_io.py、cli.py 使用配套代码。
- 可选阅读：`../pi/packages/agent/src/agent-loop.ts` 的 runLoop，只追“响应 → 工具结果 → 下一轮”。

## 你手写的入口

```python
class RunLimitError(Exception):
    """请求或工具调用预算不足。"""


def response_calls(response):
    """校验完整响应与调用 ID，返回本批工具调用。"""
    ...


async def run_agent(prompt: str, workspace: Path) -> str:
    """维护 history，有限循环调用 request_once，执行并回传工具结果。"""
    ...
```

入口草图省略导入与部分类型，不是可直接运行模块。history 使用 ModelMessage，响应使用 ModelResponse，调用使用 ToolCallPart。

只实现这些决定：

1. 拒绝空输入；创建携带固定 instructions 的用户消息。
2. 在一次模型连接生命周期内，最多请求 8 次。完整响应追加 history，不能只保存 text。
3. 校验 state 为 complete、finish_reason 为 stop 或 tool_call；调用 ID 非空且本批唯一。无工具时必须是 stop 且文本非空。
4. 有工具先检查整批预算：累计最多 16 次，且必须还有下一次请求额度。最后一次请求提出工具时不执行。
5. 按模型给出的顺序执行，保留原 ID，把完整批次结果放进一条 ModelRequest，再继续请求。每轮保持相同 instructions。

明确区分完整 history、当前响应、待回传工具批次、累计次数和运行终态；先用简单变量或数据结构，不提前造状态框架。Day 2 再把 Hook 与事件接入这些边界。

这一天只做 read；不执行部分流式参数，不同时维护第二套流式 Loop。

## 怎样算完成

接入配套 CLI 后运行 `uv run zeta -p "用 read 读取 README.md，再概括项目目标"`。
在调试器观察完整 assistant tool call、同 ID 的 tool result、下一次请求和最终文本。模型没实际调用 read 就不能算工具闭环验收。
能解释：谁保存 history，谁执行工具，为什么单次模型函数无法替代这个循环。

<details>
<summary>卡住再看：参考思路（算法说明，不是完整可运行答案）</summary>

```text
history = [用户消息]
打开 model
重复最多 8 次：
    response = await request_once(model, history)
    calls = response_calls(response)
    history.append(response)
    没有 calls → 返回最终文本
    检查整批工具额度和下一次请求额度
    results = 按顺序 execute_tool(call, workspace)
    history.append(携带完整 results 和 instructions 的 ModelRequest)
```

工具失败或协议异常直接向外抛出，不能拿半批结果继续请求。Day 2 才把预期工具失败变成模型可读结果。

</details>
