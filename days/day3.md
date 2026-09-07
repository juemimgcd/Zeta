# Day 3：Session：保存事实与恢复位置

[总览](summary.md) · [配套基础代码](support.md)

## 核心问题

history 在内存里能运行，进程退出后怎么办？Session 保存发生过的完整事实，checkpoint 指定能否继续；这还不是长期 Memory。

## 已提供与本日范围

- 计划新增 `src/zeta/session.py`，把提交和恢复规则接入 app.py。
- 配套层后续提供 SQLite 连接、CRUD 和框架消息序列化；今天不考 SQL，不假设 store 已实现。
- 可选阅读：Pi session-manager.ts 的 appendMessage / buildSessionContext；借鉴记录与模型视图分离，不照抄存储格式。

## 你手写的入口

```python
def commit_response(store, session_id, response):
    """保存完整响应；有调用则记录 pending IDs，否则记录正常完成。"""
    ...


def commit_tool_result(store, session_id, result):
    """保存一项结果并更新 pending；只有整批齐全才允许下一次请求。"""
    ...


def load_resume_point(store, session_id):
    """读取历史、运行状态和 pending；决定继续或停在恢复处理。"""
    ...
```

先定最小数据契约，再让配套存储实现它：session_id、稳定 entry_id、递增序号、完整消息、run 状态、pending tool IDs。保存 usage、工具名称和结果状态，不把它们降成一段文本。单个结果允许先存，发给模型时再重建完整批次。

只实现线性 Session；parent_id、分支、搜索留到选修。数据库短事务里更新记录和 checkpoint，不把网络请求包进事务。

## 怎样算完成

手动运行一次真实 read 闭环，记录 session_id；退出进程后读取同一个 Session，确认消息内容和 call ID 保留，后续提问可以延续它。
调试器查看 pending 非空的恢复分支：它不能直接请求模型。若未实际中断并恢复，只算代码审阅，不算崩溃恢复已经通过。

<details>
<summary>卡住再看：参考思路（算法说明，不是完整可运行答案）</summary>

```text
模型响应提交：记录完整 response + pending IDs，同一事务
工具结果提交：记录 result + 移除对应 pending ID，同一事务
恢复：
    pending 为空且状态允许继续 → 重建历史，接受新输入或继续
    pending 非空 → 先处理未完成批次
    已记录的结果 → 复用，不重做
    无结果的 read → 显式采用可重试只读策略，完成后补齐批次
    无结果的副作用 → 状态不确定，要求人工处理，不自动重放
```

数据库事务不能让外部命令恰好执行一次。失败或取消也要保存终态；不能把“有记录”直接等同于“可恢复运行”。

</details>
