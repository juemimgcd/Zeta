# Day 4：新增长期 Memory

[总览](summary.md) · [固定基础代码](support.md)

## 核心问题

哪些信息值得跨任务保留？实现显式记住、召回和遗忘，复用已有 SQLite 存储，不修改运行入口或 Session 文件。

## 今天新增什么，哪些文件不动

**今天只新增：** `memory.py`。每个文件的实现只在它所属的这一天给出。

**保留不动：** support.md 的固定基础文件及前面各天已完成的全部文件。今天不替换 app.py，不重新填写 run_agent/run_loop，不复制一份旧循环改名。

## 本日实现与边界

- MemoryStore 的 allowed_scopes 由可信入口绑定，不能由模型声明提升权限。
- remember 要求确认、有效正文、合法作用域和可定位来源；精确重复项复用 ID。
- recall 先过滤 active 和 scope，再按关键词命中数稳定排序、去重、限量；这不是语义检索。
- forget 只将记忆失效，不删除原 Session；冲突记录保留来源，人工决定，不宣称自动语义冲突检测已完成。

## 完整练习骨架

导包、异常类、字段、初始化和辅助实现已给出，只填 TODO 函数体。NotImplementedError 是未完成提示；移除它并填写真实逻辑后再验收。骨架暂时关闭未使用导入提示，其他类型检查保持开启。

### src/zeta/memory.py

只填写：`forget`、`recall`、`remember`。

```python
# ruff: noqa: F401  # Prepared imports for exercise bodies.
# pyright: reportUnusedImport=false
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from zeta.session import SessionData
from zeta.storage import JsonStore


class Memory(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    text: str
    scope: str
    source_entry_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    active: bool = True


class MemoryStore:
    def __init__(self, database: JsonStore, allowed_scopes: frozenset[str]) -> None:
        if not allowed_scopes:
            raise ValueError("at least one trusted scope is required")
        self.database = database
        self.allowed_scopes = allowed_scopes


def remember(
    store: MemoryStore, text: str, scope: str, source_entry_id: str, *, confirmed: bool
) -> Memory:
    """TODO：
    1. 校验确认、正文、scope 和来源可访问性。
    2. 精确重复活跃记忆复用 ID。
    3. 保存来源、时间、状态并返回记录。"""
    raise NotImplementedError("请完成 remember")


def recall(
    store: MemoryStore, query: str, allowed_scopes: frozenset[str], limit: int = 5
) -> list[Memory]:
    """TODO：
    1. 验证请求 scope 是可信 scope 的子集。
    2. 过滤失效记录，统计关键词命中数。
    3. 稳定排序、去重和限量，返回带来源的记忆。"""
    raise NotImplementedError("请完成 recall")


def forget(store: MemoryStore, memory_id: str, *, confirmed: bool) -> None:
    """TODO：
    1. 检查确认与记录归属。
    2. 将 active 设为 False 并提交。
    3. 不删除 Session 原文，也不声称彻底遗忘。"""
    raise NotImplementedError("请完成 forget")
```

## 怎样核对

在同一数据库中显式记住项目偏好，用新的 Session/查询入口召回；其他 scope 不可见。forget 后再次召回不出现。中文关键词可用空格分开，例如“回答 中文”，不以自然语言命中率冒充语义检索效果。

不新增测试、mock、fixture 或内联自测。代码静态检查与实际模型/故障验收分开记录。

## 完整参考答案

答案只针对本日新增文件。前面各天的答案是被复用的依赖，不在这里再给修改版。

<details>
<summary>参考答案：src/zeta/memory.py（完整文件）</summary>

```python
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from zeta.session import SessionData
from zeta.storage import JsonStore


class Memory(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    text: str
    scope: str
    source_entry_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    active: bool = True


class MemoryStore:
    def __init__(self, database: JsonStore, allowed_scopes: frozenset[str]) -> None:
        if not allowed_scopes:
            raise ValueError("at least one trusted scope is required")
        self.database = database
        self.allowed_scopes = allowed_scopes


def remember(
    store: MemoryStore, text: str, scope: str, source_entry_id: str, *, confirmed: bool
) -> Memory:
    if not confirmed:
        raise PermissionError("explicit confirmation required")
    if not text.strip() or scope not in store.allowed_scopes:
        raise ValueError("invalid text or scope")
    with store.database.transaction():
        sessions = [
            SessionData.model_validate_json(body)
            for body in store.database.all("session")
        ]
        if not any(
            session.scope in store.allowed_scopes
            and any(entry.id == source_entry_id for entry in session.entries)
            for session in sessions
        ):
            raise ValueError("source entry missing or outside allowed scopes")
        for body in store.database.all("memory"):
            memory = Memory.model_validate_json(body)
            if (
                memory.active
                and memory.scope == scope
                and (memory.text == text.strip())
            ):
                return memory
        memory = Memory(text=text.strip(), scope=scope, source_entry_id=source_entry_id)
        store.database.put("memory", memory.id, memory.model_dump_json())
    return memory


def recall(
    store: MemoryStore, query: str, allowed_scopes: frozenset[str], limit: int = 5
) -> list[Memory]:
    if not allowed_scopes <= store.allowed_scopes:
        raise PermissionError("scope escalation")
    if type(limit) is not int or limit <= 0:
        raise ValueError("limit must be positive")
    keywords = set(query.casefold().split())
    if not keywords:
        return []
    ranked: list[tuple[int, Memory]] = []
    for body in store.database.all("memory"):
        memory = Memory.model_validate_json(body)
        if not memory.active or memory.scope not in allowed_scopes:
            continue
        score = sum(word in memory.text.casefold() for word in keywords)
        if score:
            ranked.append((score, memory))
    ranked.sort(key=lambda pair: (-pair[0], pair[1].id))
    seen: set[tuple[str, str]] = set()
    result: list[Memory] = []
    for _, memory in ranked:
        key = (memory.scope, memory.text)
        if key not in seen:
            seen.add(key)
            result.append(memory)
        if len(result) == limit:
            break
    return result


def forget(store: MemoryStore, memory_id: str, *, confirmed: bool) -> None:
    if not confirmed:
        raise PermissionError("explicit confirmation required")
    with store.database.transaction():
        body = store.database.get("memory", memory_id)
        if body is None:
            raise KeyError("unknown memory")
        memory = Memory.model_validate_json(body)
        if memory.scope not in store.allowed_scopes:
            raise PermissionError("memory belongs to another scope")
        memory.active = False
        store.database.put("memory", memory.id, memory.model_dump_json())
```

</details>

## 与前后单元的关系

Day 7 直接导入本日完成的模块，不要求改写函数或扩大签名。原文、作用域和摘要来源边界仍以本日契约为准。
