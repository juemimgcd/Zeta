import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import cast


# 用 SQLite 按 (kind, id) 保存文本的简单存储；body 通常由上层编码为 JSON。
# 本类不校验 JSON 内容；用于单进程教学，由调用者决定事务范围。
class JsonStore:
    """Single-process teaching store; transaction ownership stays with callers."""

    # path 为数据库文件路径；创建父目录，打开连接并初始化 documents 表。
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # SQLite 连接对象，所有查询和写入通过它执行，用完由 close 释放。
        self.connection = sqlite3.connect(path)
        # 复合主键 (kind, id) 区分类别与记录；同类同编号最多保留一条。
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS documents ("
            "kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, "
            "PRIMARY KEY(kind, id))"
        )
        self.connection.commit()

    # 把带 yield 的生成器转换为可写 with store.transaction(): 的上下文管理器。
    @contextmanager
    # 提供事务范围：正常离开时提交，异常离开时回滚；不自动关闭连接。
    # yield 把控制权交给调用者的 with 代码块，本方法不产出业务数据。
    def transaction(self) -> Generator[None]:
        with self.connection:
            yield

    # 按类别 kind 和记录编号 key 查询正文；不存在返回 None，存在返回字符串。
    def get(self, kind: str, key: str) -> str | None:
        # ? 占位符绑定参数；fetchone 取一行，row[0] 是所选 body 列。
        row = self.connection.execute(
            "SELECT body FROM documents WHERE kind=? AND id=?", (kind, key)
        ).fetchone()
        # cast 只告诉类型检查器此值按 str 使用，不是运行时字符串转换。
        return None if row is None else cast(str, row[0])

    # 写入正文 body；相同 (kind, key) 已存在就更新，否则插入。
    # 此方法不主动 commit，应在调用者的 transaction 上下文中使用。
    def put(self, kind: str, key: str, body: str) -> None:
        self.connection.execute(
            "INSERT INTO documents(kind,id,body) VALUES(?,?,?) "
            "ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
            (kind, key, body),
        )

    # 查询某类别的全部正文，按记录 id 排序后返回字符串列表。
    def all(self, kind: str) -> list[str]:
        rows = self.connection.execute(
            "SELECT body FROM documents WHERE kind=? ORDER BY id", (kind,)
        ).fetchall()
        return [cast(str, row[0]) for row in rows]

    # 关闭数据库连接；调用前应完成事务，close 本身不替未提交修改执行 commit。
    def close(self) -> None:
        self.connection.close()