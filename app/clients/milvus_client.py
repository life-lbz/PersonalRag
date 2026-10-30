"""Milvus 客户端封装：按业务知识库自动切 database（§4.2 架构）。

核心设计：
  - 每个业务 KB 映射到 Milvus 的一个 database，database 名 = kb_{kb_id 前 12 位}
  - 同一 database 内只有一个 collection：kb_chunks（schema 统一）
  - 首次遇到新 KB 时自动 create_database + create_collection + load
  - 所有 public 函数签名加 kb_id 参数，内部自动切 db
  - 缓存：{kb_id: (db_name, MilvusClient)}，避免每次重建连接

Collection schema（《RAG系统方案设计文档.md》§4.2）：
  chunk_id VARCHAR PK / doc_id / kb_id / doc_type
  dense_vector 1024d HNSW COSINE / question_vector 1024d HNSW COSINE / sparse_vector SPARSE_FLOAT_VECTOR
"""
from __future__ import annotations

import logging
import re
from typing import Any

from pymilvus import CollectionSchema, DataType, FieldSchema, MilvusClient
from pymilvus.milvus_client.index import IndexParams

from app.config import settings

logger = logging.getLogger(__name__)

# db_name 合法字符集：字母/数字/下划线，最大 128 字符
_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

_kb_ctx: dict[str, tuple[str, MilvusClient]] = {}  # kb_id → (db_name, client)
_collection_name = "kb_chunks"


# ---------- db / collection 生命周期 ----------

def _sanitize(s: str) -> str:
    """转成合法的 Milvus db_name / partition_name（只留字母数字下划线）。"""
    return re.sub(r"[^A-Za-z0-9_]", "_", s)


def _db_name_for_kb(kb_id: str) -> str:
    """kb_id → db_name，格式 kb_{前16位hex}，确保字母数字合法。"""
    hex_part = kb_id.replace("-", "")[:16]  # UUID 去连字符后取前 16 位
    return f"kb_{hex_part}"


def _ensure_kb_db(kb_id: str) -> tuple[str, MilvusClient]:
    """确保 kb 对应的 Milvus database + collection 已就绪。"""
    cached = _kb_ctx.get(kb_id)
    if cached:
        return cached

    db_name = _db_name_for_kb(kb_id)
    client = MilvusClient(uri=settings.milvus.uri, db_name=db_name)

    # database 不存在则创建
    if db_name not in client.list_databases():
        # MilvusClient 没有 create_database 方法, 用通用客户端切
        from pymilvus import MilvusClient as _MC
        root = _MC(uri=settings.milvus.uri, db_name="default")
        root.create_database(db_name=db_name)
        logger.info("Milvus 创建 database: %s", db_name)
        client = MilvusClient(uri=settings.milvus.uri, db_name=db_name)

    # collection 不存在则创建 + 建索引
    if not client.has_collection(collection_name=_collection_name):
        schema = _build_schema()
        client.create_collection(
            collection_name=_collection_name,
            schema=schema,
            dimension=1024,
            auto_id=False,
            enable_dynamic_field=False,
        )
        _create_indexes(client)
        logger.info("Milvus 创建 collection+索引: %s (db=%s)", _collection_name, db_name)

    client.load_collection(collection_name=_collection_name)
    _kb_ctx[kb_id] = (db_name, client)
    return db_name, client


def _build_schema(dim: int = 1024) -> CollectionSchema:
    fields = [
        FieldSchema("chunk_id", DataType.VARCHAR, max_length=64, is_primary=True),
        FieldSchema("doc_id", DataType.VARCHAR, max_length=36),
        FieldSchema("kb_id", DataType.VARCHAR, max_length=36),
        FieldSchema("doc_type", DataType.VARCHAR, max_length=32),
        FieldSchema("dense_vector", DataType.FLOAT_VECTOR, dim=dim),
        FieldSchema("question_vector", DataType.FLOAT_VECTOR, dim=dim),
        FieldSchema("sparse_vector", DataType.SPARSE_FLOAT_VECTOR),
    ]
    return CollectionSchema(fields, description="RAG text chunks per KB")


def _create_indexes(client: MilvusClient) -> None:
    """为 collection 的三个向量字段建索引（HNSW dense/question + SPARSE sparse）。"""
    ip = IndexParams()
    ip.add_index(field_name="dense_vector", index_type="HNSW", metric_type="COSINE",
                 params={"M": 16, "efConstruction": 200})
    ip.add_index(field_name="question_vector", index_type="HNSW", metric_type="COSINE",
                 params={"M": 16, "efConstruction": 200})
    ip.add_index(field_name="sparse_vector", index_type="SPARSE_INVERTED_INDEX", metric_type="IP",
                 params={"drop_ratio_build": 0.2})
    client.create_index(collection_name=_collection_name, index_params=ip)


# ---------- 对外 API ----------

def upsert_chunks(kb_id: str, rows: list[dict]) -> None:
    """rows: [{chunk_id, doc_id, kb_id, doc_type, dense_vector, question_vector, sparse_vector}]"""
    if not rows:
        return
    _db_name, client = _ensure_kb_db(kb_id)
    data = []
    for r in rows:
        data.append({
            "chunk_id": r["chunk_id"],
            "doc_id": r["doc_id"],
            "kb_id": r["kb_id"],
            "doc_type": r.get("doc_type", "general"),
            "dense_vector": r["dense_vector"],
            "question_vector": r.get("question_vector") or r["dense_vector"],
            "sparse_vector": r["sparse_vector"],
        })
    client.upsert(collection_name=_collection_name, data=data)


def search_dense(kb_id: str, vector: list[float], top_k: int, filter_expr: str | None = None) -> list[dict]:
    return _search(kb_id, vector, "dense_vector", top_k, filter_expr)


def search_question(kb_id: str, vector: list[float], top_k: int, filter_expr: str | None = None) -> list[dict]:
    return _search(kb_id, vector, "question_vector", top_k, filter_expr)


def search_sparse(kb_id: str, sparse: dict[int, float], top_k: int, filter_expr: str | None = None) -> list[dict]:
    return _search(kb_id, sparse, "sparse_vector", top_k, filter_expr, metric="IP")


def _search(kb_id: str, vector, field: str, top_k: int, filter_expr: str | None, metric: str = "COSINE") -> list[dict]:
    _db_name, client = _ensure_kb_db(kb_id)
    search_params = {"metric_type": metric, "params": {"ef": 256}}
    # pymilvus 3.0+ 要求 search data 统一传 list（dense: [list[float]], sparse: [dict[int,float]]）
    data = [vector] if not isinstance(vector, list) else [vector]
    results = client.search(
        collection_name=_collection_name,
        data=data,
        anns_field=field,
        search_params=search_params,
        limit=top_k,
        filter=filter_expr or "",
        output_fields=["chunk_id", "doc_id", "kb_id", "doc_type"],
    )
    out: list[dict] = []
    for hits in results:
        for h in hits:
            out.append({
                "chunk_id": h.get("chunk_id") or h.get("id"),
                "doc_id": h.get("doc_id"),
                "kb_id": h.get("kb_id"),
                "doc_type": h.get("doc_type"),
                "score": float(h.get("score", 0.0)),
            })
    return out


def existing_chunk_ids(kb_id: str, ids: list[str]) -> set[str]:
    """返回给定 chunk_id 中已存在于 Milvus 的集合（H6 回滚向量覆盖度校验）。"""
    if not ids:
        return set()
    _db_name, client = _ensure_kb_db(kb_id)
    try:
        rows = client.get(collection_name=_collection_name, ids=ids, output_fields=["chunk_id"])
    except Exception:
        # 兼容不支持 ids 参数的 pymilvus 版本：退化为过滤查询
        id_list = ", ".join(f'"{i}"' for i in ids)
        rows = client.query(collection_name=_collection_name,
                            filter=f"chunk_id in [{id_list}]", output_fields=["chunk_id"])
    return {r.get("chunk_id") for r in rows if r.get("chunk_id")}


def delete_by_doc(kb_id: str, doc_id: str) -> None:
    _db_name, client = _ensure_kb_db(kb_id)
    client.delete(collection_name=_collection_name, filter=f'doc_id == "{doc_id}"')


def delete_by_ids(kb_id: str, ids: list[str]) -> None:
    if not ids:
        return
    _db_name, client = _ensure_kb_db(kb_id)
    id_list = ", ".join(f'"{i}"' for i in ids)
    client.delete(collection_name=_collection_name, filter=f"chunk_id in [{id_list}]")


def collection_stats(kb_id: str) -> dict[str, Any]:
    _db_name, client = _ensure_kb_db(kb_id)
    info = client.get_collection_stats(collection_name=_collection_name)
    return {"num_entities": info.get("row_count", 0), "db_name": _db_name}


def list_kb_dbs() -> list[str]:
    """列出所有按 KB 创建的 Milvus database（用于运维/迁移）。"""
    root = MilvusClient(uri=settings.milvus.uri, db_name="default")
    return [db for db in root.list_databases() if db.startswith("kb_")]
