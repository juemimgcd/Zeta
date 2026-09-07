# Day 5：Context：决定模型这一轮看见什么

[总览](summary.md) · [配套基础代码](support.md)

## 核心问题

Session 很长、Memory 很多，但模型输入有限。你决定选哪些信息、用什么顺序、在哪里让出预算，并能解释每块信息的来源。

## 已提供与本日范围

- 计划新增 `src/zeta/context.py`；复用 Session 和 Memory 查询结果。
- token 估算与消息编码作为配套函数；先使用同一估算口径并留余量，不把字符数当精确计费。
- 可选阅读：Pi resource-loader.ts 和 agent-loop.ts 中模型调用前的上下文转换边界。

## 你手写的入口

```python
def build_context(instructions, resources, memories, summary, history, budget):
    """返回请求视图、来源清单、估算量；不足则报告需要压缩。"""
    ...
```

第一版返回三类结果：模型消息视图、各块 source IDs 与取舍原因、estimated_tokens / needs_compaction。不要修改原始 history。Day 2 的 before_model 返回新视图后，再做一次配对、来源和预算校验；否则 Hook 注入的信息可能绕过本日预算约束。

优先保留固定指令、当前用户问题和最近必须完整的交互，再给相关 Memory、资源与摘要分配额度；最终展示顺序可以是“指令 → 资源/Memory → 摘要 → 近期历史”。展示顺序不等于淘汰优先级。

输入额度 = 配置窗口 - 输出预留 - 工具 schema 等开销 - 安全余量。工具调用与结果按完整组处理；不能任意截断消息数组。资源和工具正文标为数据，不提升为系统指令。必需部分都放不下时明确停止或请求缩小输入，不静默丢掉当前问题。

## 怎样算完成

针对一次实际任务查看 Context 来源清单：当前问题存在，Memory 在允许 scope 内，工具配对完整，预算包含输出预留。对比 Session 原文，确认仅模型视图被选择或裁短。
能解释：有用的信息为什么被选中，另一条历史为什么被排除。

<details>
<summary>卡住再看：参考思路（算法说明，不是完整可运行答案）</summary>

```text
required = 固定指令 + 当前问题 + 最近不可拆交互
available = 窗口 - 输出预留 - schema 开销 - 余量
required 超出 available → 报告不可容纳，不截断协议
按相关性挑选 memories/resources，记录来源和成本
按完整交互补入摘要与历史
仍需旧历史但空间不足 → needs_compaction
返回新视图，不修改持久化原文
```

对超大工具输出可保存原文引用、给模型受限正文，但保留 ToolReturnPart 的 ID 和状态。估算值与实际 API usage 分开记录，运行后用偏差校准余量。

</details>
