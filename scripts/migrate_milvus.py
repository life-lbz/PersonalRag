# -*- coding: utf-8 -*-
"""迁移 default database 的 kb_chunks 数据到按 KB 命名的新 database。

迁移后 default.kb_chunks 可保留（后续删除），Attu 上会看到：
  default  (Milvus 系统库, 保留或清空)
  kb_3b78605f  (业务库, 对应测试知识库)

运行: python scripts/migrate_milvus.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.clients.milvus_client import _db_name_for_kb, _ensure_kb_db  # noqa: E402
from pymilvus import MilvusClient  # noqa: E402

ROOT_URI = "http://localhost:19530"


def main() -> None:
    root = MilvusClient(uri=ROOT_URI, db_name="default")

    if not root.has_collection(collection_name="kb_chunks"):
        print("default.kb_chunks 不存在, 无需迁移")
        return

    # query 不需要 load（search 才需要）

    # 拉取 default.kb_chunks 全部数据（分批量）
    all_data: list[dict] = []
    offset = 0
    batch = 100
    while True:
        rows = root.query(
            collection_name="kb_chunks",
            limit=batch,
            offset=offset,
            output_fields=["chunk_id", "doc_id", "kb_id", "doc_type",
                           "dense_vector", "question_vector", "sparse_vector"],
        )
        if not rows:
            break
        all_data.extend(rows)
        offset += batch
        if len(rows) < batch:
            break

    if not all_data:
        print("default.kb_chunks 为空, 无需迁移")
        return

    print(f"从 default.kb_chunks 读取 {len(all_data)} 条数据")

    # 按 kb_id 分组写入各自的 database
    by_kb: dict[str, list[dict]] = {}
    for row in all_data:
        by_kb.setdefault(row["kb_id"], []).append(row)

    for kb_id, rows in by_kb.items():
        db_name = _db_name_for_kb(kb_id)
        print(f"  写入 kb_id={kb_id} → db={db_name} ({len(rows)} 条)")
        _db, client = _ensure_kb_db(kb_id)
        client.upsert(collection_name="kb_chunks", data=rows)

    print()
    print("迁移完成!")
    print(f"  已创建的 Milvus databases: {[d for d in root.list_databases() if d.startswith('kb_')]}")
    print("  Attu 刷新后即可看到 kb_* 数据库")
    print("  default.kb_chunks 中的旧数据可手动删除:")
    print("    python -c \"from pymilvus import MilvusClient; c=MilvusClient(uri='http://localhost:19530',db_name='default'); c.drop_collection(collection_name='kb_chunks')\"")


if __name__ == "__main__":
    main()
