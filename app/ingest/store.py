"""多路入库（StoreWriter）：PG(chunks) 成功后再写 Milvus(向量)，失败补偿任务兜底（§3.1.1 store）。

写入时 searchable=false（灰度），全链成功后由版本管理模块原子切换。
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.entities import Chunk, LawArticle

logger = logging.getLogger(__name__)


def write_chunks(session: Session, doc_id: str, version_id: str, kb_id: str, doc_type: str,
                 children: list, parents: list, question_map: dict[str, list[str]] | None = None) -> int:
    """写 PG chunks 表 + law_articles 扩展。返回 chunk 数。

    children/parents 为 Chunk(pydantic)，chunk_id 已 finalize。
    parents 中 parent_id 引用"PARENT_{idx}"的子块在此回填真实父块 id。
    """
    from app.ingest.splitters.base import finalize_chunk_ids

    finalize_chunk_ids(children, version_id)
    finalize_chunk_ids(parents, version_id)

    # 回填父子关系
    for c in children:
        pid = c.parent_id
        if pid and pid.startswith("PARENT_"):
            idx = int(pid.split("_")[1])
            c.parent_id = parents[idx].chunk_id

    rows: list[Chunk] = []
    for p in parents:
        p.metadata = {**p.metadata, "is_parent": True}
        rows.append(p)
    rows.extend(children)
    # 去重（父子同块时 chunk_id 相同）；失败续跑时先清理残留
    seen: set[str] = set()
    deduped: list[Chunk] = []
    for c in rows:
        if c.chunk_id in seen:
            continue
        seen.add(c.chunk_id)
        deduped.append(c)
    rows = deduped
    session.query(Chunk).filter(Chunk.version_id == version_id).delete(
        synchronize_session=False
    )

    law_effective = (children[0].metadata or {}).get("effective_date") if children else None
    for c in rows:
        session.add(
            Chunk(
                id=c.chunk_id,
                version_id=version_id,
                doc_id=doc_id,
                parent_id=c.parent_id,
                prev_id=c.prev_id,
                next_id=c.next_id,
                content=c.content,
                token_count=c.token_count,
                chapter_path=c.metadata.get("chapter_path"),
                searchable=False,  # 灰度：切由 promote_version 原子执行
                meta=c.metadata,
            )
        )

    # 法规扩展表
    if doc_type == "law":
        for c in children:
            md = c.metadata or {}
            if not md.get("article_no"):
                continue
            session.add(
                LawArticle(
                    doc_id=doc_id,
                    law_name=md.get("law_name"),
                    article_no=md.get("article_no"),
                    chapter_path=md.get("chapter_path"),
                    effective_date=_parse_date(md.get("effective_date") or law_effective),
                    status="现行有效",
                    version="v1",
                )
            )
    session.flush()
    return len(children)


def _parse_date(s):
    if not s:
        return None
    from datetime import date as _d

    try:
        parts = str(s).split("-")
        return _d(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return None


def write_milvus(session: Session, kb_id: str, doc_type: str, version_id: str,
                 question_map: dict[str, list[str]]) -> int:
    """对某 version 的子块做向量化并 upsert Milvus（幂等缓存命中则跳过 embedding）。"""
    from sqlalchemy import select

    from app.clients import milvus_client
    from app.clients.redis_client import cache_get_json_sync, cache_set_json_sync
    from app.config import settings
    from app.ingest.embedder import embed_texts_sync
    from app.ingest.splitters.base import make_chunk_id

    chunks = session.execute(select(Chunk).where(Chunk.version_id == version_id)).scalars().all()
    # 只向量化"检索块"：父块 metadata.is_parent=True，不参与召回
    target = [c for c in chunks if not (c.meta or {}).get("is_parent")]
    if not target:
        return 0

    cache_cfg = settings.ingest.cache
    texts, cached_vecs = [], {}
    for c in target:
        key = f"{cache_cfg.key_prefix}{make_chunk_id(version_id, c.content)}:embed:{cache_cfg.step_version}"
        if cache_cfg.enabled:
            hit = cache_get_json_sync(key)
            if hit:
                cached_vecs[c.id] = hit
                continue
        texts.append((c.id, key, c))

    # 组装 embedding 输入：问题向量与正文向量分开
    content_texts = []
    question_texts = []
    q_index: dict[str, list[int]] = {}
    for cid, _key, c in texts:
        content_texts.append(c.content)
        qs = question_map.get(cid, [])
        idxs = list(range(len(question_texts), len(question_texts) + len(qs)))
        q_index[cid] = idxs
        question_texts.extend(qs if qs else [c.content])  # 无问题向量时占位(与正文同)

    if content_texts:
        dense_all, sparse_all = embed_texts_sync(content_texts)
    else:
        dense_all, sparse_all = [], []
    q_dense = []
    if question_texts:
        q_dense, _ = embed_texts_sync(question_texts)

    rows = []
    it_content = 0
    for i, (cid, key, c) in enumerate(texts):
        dense, sparse = dense_all[it_content], sparse_all[it_content]
        it_content += 1
        if not q_index[cid] or not question_map.get(cid):
            qvec = dense
        else:
            qvec = q_dense[q_index[cid][0]]
        if cache_cfg.enabled:
            cache_set_json_sync(key, {"dense": dense, "sparse": sparse, "qvec": qvec})
        rows.append({
            "chunk_id": c.id, "doc_id": c.doc_id, "kb_id": kb_id, "doc_type": doc_type,
            "dense_vector": dense, "question_vector": qvec, "sparse_vector": _to_milvus_sparse(sparse),
        })
    # 缓存命中的直接组装
    for cid, hit in cached_vecs.items():
        c = next(x for x in target if x.id == cid)
        rows.append({
            "chunk_id": cid, "doc_id": c.doc_id, "kb_id": kb_id, "doc_type": doc_type,
            "dense_vector": hit["dense"], "question_vector": hit.get("qvec") or hit["dense"],
            "sparse_vector": _to_milvus_sparse(hit["sparse"]),
        })

    milvus_client.upsert_chunks(kb_id, rows)
    for c in target:
        c.milvus_id = c.id
    session.flush()
    return len(rows)


def _to_milvus_sparse(sparse: dict) -> dict[int, float]:
    """BGE-M3 lexical_weights: {token_str: weight} → Milvus {token_id_int: weight}。"""
    out = {}
    for k, v in (sparse or {}).items():
        try:
            out[int(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out
