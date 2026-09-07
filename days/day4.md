# Day 4：Memory：跨任务保留有用信息

[总览](summary.md) · [配套基础代码](support.md)

## 核心问题

什么值得从一次对话带进下一次任务？你实现记忆的生命周期和召回规则，而不是把所有聊天再次塞给模型。

## 已提供与本日范围

- 计划新增 `src/zeta/memory.py`；SQLite CRUD 由配套层提供，暂不加 embedding。
- store 契约支持保存、按 scope 查询 active 记录、按 ID 失效；不是当前已有模块。
- Session entry 是来源证据，Memory 是带明确作用域的独立记录。不要在 Pi 中寻找假定存在的同名模块。

## 你手写的入口

```python
def remember(store, text, scope, source_entry_id, *, confirmed):
    """确认后保存记忆；保留来源、创建时间与 active 状态。"""
    ...


def recall(store, query, allowed_scopes, limit=5):
    """先过滤作用域与状态，再排序去重并限制数量。"""
    ...


def forget(store, memory_id, *, confirmed):
    """确认后失效，后续召回与缓存中排除它。"""
    ...
```

第一版只接受显式 remember/forget，不自动把模型推测写成事实。scope 先支持用户级和当前项目级；同一用户其他项目的记忆不能泄漏进来。
召回用明确关键词匹配即可。冲突记忆先保留来源并标记待确认；“更新时间较新”不自动证明它更正确。查询调用方不能靠模型自行声明作用域获得权限。

## 怎样算完成

显式记住一个项目偏好，在新 Session 召回并检查来源；另一个项目不应召回该项目记录。forget 后再次召回，确认它不出现。
这验证的是最小记忆闭环，不代表已经验证召回质量或个性化效果。

<details>
<summary>卡住再看：参考思路（算法说明，不是完整可运行答案）</summary>

```text
remember：检查 confirmed、非空正文、合法 scope、来源 entry 可定位
          → 保存稳定 memory_id；精确重复项复用或显式更新
recall：可信运行配置给出 allowed_scopes
        → 筛 active → 关键词匹配 → 按明确规则排序 → 去重 → Top-N
forget：检查 confirmed 和记录归属 → 标记 inactive → 清理派生缓存
```

遗忘在本单元指不再作为活跃记忆召回；原 Session 仍可能含用户原话。若它还在当前 Context 或旧摘要中，应重建相关视图并注明限制，不能宣称原始数据已被彻底删除。

</details>
