"""入库任务链：parse → split → enhance(auto_question) → embed → write。

状态机：pending → parsing → splitting → enhancing → embedding → writing → done
任一环节失败 → failed(stage, error)，支持从失败 stage 续跑（任务幂等 + 缓存命中降低重跑成本）。
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.ingest.celery_app import celery_app
from app.models.entities import Chunk as ChunkORM
from app.models.entities import Document, DocumentVersion, IngestTask, LawArticle

logger = logging.getLogger(__name__)


def _task_update(task_id: str, **kw) -> None:
    from app.db.session import SyncSessionLocal

    with SyncSessionLocal() as session:
        task = session.get(IngestTask, task_id)
        if task is None:
            return
        for k, v in kw.items():
            setattr(task, k, v)
        session.commit()


@celery_app.task(bind=True, name="ingest.run_pipeline", max_retries=1)
def run_pipeline(self, task_id: str, file_data: bytes, filename: str,
                 kb_id: str, doc_id: str | None = None, doc_type_hint: str | None = None,
                 version_policy: str | None = None):
    """主链入口（单任务串行阶段，便于状态跟踪与续跑）。"""
    from app.db.session import SyncSessionLocal

    try:
        _task_update(task_id, status="running", stage="parsing")
        return _run(task_id, file_data, filename, kb_id, doc_id, doc_type_hint, version_policy)
    except Exception as e:
        logger.exception("入库任务 %s 失败", task_id)
        _task_update(task_id, status="failed", error=str(e)[:2000])
        raise


def _run(task_id: str, file_data: bytes, filename: str, kb_id: str,
         doc_id: str | None, doc_type_hint: str | None,
         version_policy: str | None = None) -> dict:
    from app.db.session import SyncSessionLocal
    from app.ingest.parsers import parse_document
    from app.ingest.splitters import split_document
    from app.ingest.version import content_hash, promote_version, resolve_version

    # ① parse
    _task_update(task_id, stage="parsing")
    doc_id_candidate = doc_id or task_id  # 解析前用 task_id 占位, 版本判定后归正
    parsed = parse_document(file_data, doc_id_candidate, filename, doc_type_hint)

    # ② 版本判定 + split
    _task_update(task_id, stage="splitting")
    with SyncSessionLocal() as session:
        doc, version, created = resolve_version(
            session, kb_id, filename.rsplit(".", 1)[0] if "." in filename else filename,
            content_hash(file_data), doc_id=doc_id, doc_type=parsed.doc_type,
            version_policy=version_policy,
        )
        version.source_uri = f"kb/{kb_id}/doc/{doc.id}/{filename}"
        task = session.get(IngestTask, task_id)
        task.doc_id = doc.id
        task.version_id = version.id
        session.commit()
        if not created:
            _task_update(task_id, status="done", stage="done",
                         error=None)  # 幂等拒绝: 返回已存在版本
            return {"status": "duplicate", "doc_id": doc.id, "version_id": version.id,
                    "version": version.version}
        doc_id = doc.id
        version_id = version.id

        children, parents = split_document(parsed, doc_id, parsed.doc_type)

    # ③ enhance: auto_question（P0, 问题随后随块入向量）
    _task_update(task_id, stage="enhancing")
    question_map: dict[str, list[str]] = {}
    from app.config import settings as st

    if st.ingest.enhance.auto_question.enabled:
        from app.ingest.enhancer.auto_question import generate_questions_sync

        for c in children:
            qs = generate_questions_sync(c.content)
            if qs:
                question_map[c.chunk_id] = qs
        logger.info("任务 %s 问题生成: %d/%d 块", task_id, len(question_map), len(children))

    # ④⑤ write: PG → Milvus → 灰度切换
    _task_update(task_id, stage="writing")
    from app.ingest.store import write_chunks, write_milvus

    with SyncSessionLocal() as session:
        chunk_count = write_chunks(session, doc_id, version_id, kb_id, parsed.doc_type,
                                   children, parents, question_map)
        session.commit()

        write_milvus(session, kb_id, parsed.doc_type, version_id, question_map)
        session.commit()

        # 灰度切换（PG 单事务）
        doc = session.get(Document, doc_id)
        version = session.get(DocumentVersion, version_id)
        promote_version(session, doc, version, chunk_count)

        # 法规元数据落 law_articles（解析阶段抽取的 effective_date）
        if parsed.doc_type == "law":
            eff = (parsed.metadata or {}).get("effective_date")
            if eff:
                session.execute(
                    LawArticle.__table__.update()
                    .where(LawArticle.__table__.c.doc_id == doc_id)
                    .values(effective_date=eff)
                )
        session.commit()

    _task_update(task_id, status="done", stage="done")
    return {"status": "ok", "doc_id": doc_id, "version_id": version_id, "chunk_count": chunk_count}


@celery_app.task(name="ingest.delete_document")
def delete_document_task(doc_id: str):
    """级联删除：PG chunks → Milvus 向量 → MinIO 原文件（§5.3 删除）。失败重试补偿。"""
    from app.clients import milvus_client
    from app.clients.minio_client import delete_object
    from app.db.session import SyncSessionLocal

    errors: list[str] = []
    try:
        with SyncSessionLocal() as session:
            doc = session.get(Document, doc_id)
            source_uri = None
            if doc:
                latest = session.execute(
                    select(DocumentVersion).where(DocumentVersion.doc_id == doc_id)
                    .order_by(DocumentVersion.version.desc()).limit(1)
                ).scalar_one_or_none()
                source_uri = latest.source_uri if latest else None
            session.query(ChunkORM).filter(ChunkORM.doc_id == doc_id).delete(
                synchronize_session=False
            )
            session.query(LawArticle).filter(LawArticle.doc_id == doc_id).delete(
                synchronize_session=False
            )
            session.query(DocumentVersion).filter(DocumentVersion.doc_id == doc_id).delete(
                synchronize_session=False
            )
            if doc:
                session.delete(doc)
            session.commit()
    except Exception as e:
        errors.append(f"pg: {e}")

    try:
        milvus_client.delete_by_doc(doc.kb_id if doc else "", doc_id)
    except Exception as e:
        errors.append(f"milvus: {e}")

    if source_uri:
        try:
            delete_object(source_uri)
        except Exception as e:
            errors.append(f"minio: {e}")

    if errors:
        logger.error("删除文档 %s 部分失败: %s", doc_id, errors)
        raise RuntimeError("; ".join(errors))
    return {"status": "ok"}
