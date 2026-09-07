# Day 7：串联：一个任务走完核心生命周期

[总览](summary.md) · [配套基础代码](support.md)

## 核心问题

把前六天连接起来，确认 Loop、Hooks、事件、Session、Memory、Context 和 Compaction 各自拥有清晰职责，而不是只完成几个互不相连的函数。

## 已提供与本日范围

- 只整合已有模块，以 `src/zeta/app.py` 作为入口组装；不新增框架或 Worker。
- CLI、SQLite 细节和模型接入的剩余配套工作直接补齐，不重新变成你的学习章节。
- 今天仍使用非流式只读工具；流式与写文件在核心闭环完成后再选修。

## 你手写的入口

```python
async def run_session_task(session_id, prompt, services):
    """恢复 → 召回 → 构建 Context → Loop → 安全提交。"""
    ...
```

services 是配套依赖集合的草图，不要求建设 DI 框架。Day 1/2 的 run_agent 入口可以内部调用它，保持 CLI 使用方式稳定。

Hook 契约与事件顺序沿用 [Day 2](day2.md)：before_model 之后重新校验输入预算与工具配对；after_model 只读完整响应；after_tool 保留结果身份和状态；after_turn 只在全批结果提交后决定停止。持久化为显式步骤，不交给观察性监听器；终态通知失败不触发工具重放。

每轮请求前重新构建模型视图；权威历史在 Session，临时模型输入在 Context。响应和结果先保存，再进入下一轮。不要把摘要、Memory 注入文本重复追加成用户的原始发言。
记忆写入只接受已确认操作；正常结束、预算耗尽、取消、模型错误分别记录状态。恢复时先处理 pending，再决定继续，不能盲目重新运行整个用户任务。

## 怎样算完成

按同一条真实工作流程观察：

1. 确认保存当前项目的回答偏好；创建新 Session，请求读取 README.md 并回答。
2. 观察召回来源、Context 选择、真实 read 调用及结果、Loop 的停止原因。
3. 累积到足够长的历史后观察压缩；退出并恢复同一 Session，继续提问。
4. 显式遗忘偏好，在新的 Context 中确认它不再作为活跃记忆注入。
5. 启用 Day 2 的实际拒绝策略，核对 Hook、提交、事件的顺序：拒绝不执行，失败不变成功，Hook 停止与正常回答分别记录。审阅 Hook 异常、观察者异常和取消分支，不把未触发路径当作通过。

记录实际看到的状态与缺口，再运行相关已有检查。取消、超时等未实际触发的路径不宣称通过；不新增自动测试或模拟数据。

<details>
<summary>卡住再看：参考思路（算法说明，不是完整可运行答案）</summary>

```text
加载 Session → 检查恢复边界 → 保存本次用户输入
从可信作用域召回 Memory
进入已有有限 Loop：
    从 Session + Memory 构建 Context
    需要压缩且边界安全 → 压缩并重建
    before_model → 校验最终输入 → 调用一次模型 → 校验并保存完整响应
    after_model → model_response
    有工具 → 预检 → before_tool → 执行/拒绝 → after_tool → 逐项提交并发布 tool_end
    齐批或无工具 → turn_end → after_turn
    按 Hook 决策和正常 Loop 规则继续，或提交终态 → run_end
异常/取消 → 保存对应状态 → 有界终态通知 → 向调用方传播
```

每个失败都应该能定位到：模型接入、Hook、调度、持久化、召回、上下文选择或压缩，而不是统一显示“Agent 失败”。

学完后换到另一个框架，先找这些机制的入口、状态和控制权；SDK 的函数名按需查，不再从头学习一遍终端和网络封装。

</details>
