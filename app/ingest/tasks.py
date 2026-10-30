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
    from app.observability import bind_request_id, reset_request_id

    # L4: 继承 API 请求透传的 request_id，日志可按同一条链路串起来
    rid_token = bind_request_id(self.request.get("request_id"))
    try:
        _task_update(task_id, status="running", stage="parsing")
        return _run(task_id, file_data, filename, kb_id, doc_id, doc_type_hint, version_policy)
    except Exception as e:
        logger.exception("入库任务 %s 失败", task_id)
        _task_update(task_id, status="failed", error=str(e)[:2000])
        raise
    finally:
        reset_request_id(rid_token)


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
        from app.ingest.enhancer.auto_question import generate_questions_batch_sync

        # M1: 并发批量生成，避免逐块串行（15 块约 30 秒 → 数秒）
        all_qs = generate_questions_batch_sync(
            [c.content for c in children],
            concurrency=st.ingest.enhance.auto_question.concurrency,
        )
        for c, qs in zip(children, all_qs):
            if qs:
                question_map[c.chunk_id] = qs
        logger.info("任务 %s 问题生成: %d/%d 块", task_id, len(question_map), len(children))

    # ④⑤ write: PG → Milvus → 灰度切换
    _task_update(task_id, stage="writing")
    from app.ingest.store import write_chunks, write_milvus

    with SyncSessionLocal() as session:
        chunk_count = write_chunks(session, doc_id, version_id, kb_id, parsed.doc_type,
                                   children, parents, question_map)
        session.flush()  # chunks 落 PG（同事务可见），供 write_milvus 读取

        # 向量 upsert（幂等：同 chunk_id 重复 upsert 结果一致，失败可整任务重跑去重）
        write_milvus(session, kb_id, parsed.doc_type, version_id, question_map)

        # 灰度切换 + 法规元数据：同一事务内只提交一次，任一步失败全部回滚
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
        session.commit()  # 唯一提交点：chunks 可见性与法规元数据原子生效

    _task_update(task_id, status="done", stage="done")
    return {"status": "ok", "doc_id": doc_id, "version_id": version_id, "chunk_count": chunk_count}


@celery_app.task(bind=True, name="ingest.delete_document", max_retries=3)
def delete_document_task(self, doc_id: str):
    """级联删除：Milvus 向量 / MinIO 原文件 → PG 级联（§5.3 删除）。

    一致性顺序：外部存储删除幂等（可安全重试），全部成功后才提交 PG。
    - 外部删除失败 → PG 不动，文档保留并标记 failed，避免"PG 已删但向量/文件残留"的孤儿数据
    - PG 提交失败 → 文档仍在，任务重试时外部删除再执行一次仍幂等
    """
    from sqlalchemy import or_

    from app.clients import milvus_client
    from app.clients.minio_client import delete_object
    from app.db.session import SyncSessionLocal
    from app.observability import bind_request_id, reset_request_id

    rid_token = bind_request_id(self.request.get("request_id"))
    try:
        with SyncSessionLocal() as session:
            doc = session.get(Document, doc_id)
            if doc is None:
                logger.info("文档 %s 已不存在, 删除任务幂等结束", doc_id)
                return {"status": "ok", "note": "already_deleted"}

            # 先取出后续步骤要用的值（会话关闭后 ORM 对象属性不可再访问）
            kb_id = doc.kb_id
            versions = session.execute(
                select(DocumentVersion).where(DocumentVersion.doc_id == doc_id)
            ).scalars().all()
            version_ids = [v.id for v in versions]
            source_uris = [v.source_uri for v in versions if v.source_uri]

            # ① 先删外部存储：delete 幂等，失败可安全重试
            milvus_client.delete_by_doc(kb_id, doc_id)
            for uri in source_uris:
                delete_object(uri)

            # ② 外部全成功后一次性提交 PG 级联删除（子表 → 父表，顺序不可调换）
            #    ingest_tasks 同时被 doc_id / version_id 引用，两者都要覆盖
            task_filters = [IngestTask.doc_id == doc_id]
            if version_ids:
                task_filters.append(IngestTask.version_id.in_(version_ids))
            session.query(IngestTask).filter(or_(*task_filters)).delete(synchronize_session=False)
            # chunks 同时按 doc_id 与 version_id 兜底匹配（历史脏数据可能两者不一致）
            chunk_filters = [ChunkORM.doc_id == doc_id]
            if version_ids:
                chunk_filters.append(ChunkORM.version_id.in_(version_ids))
            session.query(ChunkORM).filter(or_(*chunk_filters)).delete(
                synchronize_session=False
            )
            session.query(LawArticle).filter(LawArticle.doc_id == doc_id).delete(
                synchronize_session=False
            )
            session.query(DocumentVersion).filter(DocumentVersion.doc_id == doc_id).delete(
                synchronize_session=False
            )
            session.delete(doc)
            session.commit()
    except Exception as e:
        logger.exception("删除文档 %s 失败: %s", doc_id, e)
        _mark_delete_failed(doc_id)
        raise self.retry(exc=e, countdown=30)
    finally:
        reset_request_id(rid_token)

    return {"status": "ok"}


def _mark_delete_failed(doc_id: str) -> None:
    """外部存储删除失败：文档保留在 PG，状态置 failed 供前端提示，等待重试/人工处理。"""
    from app.db.session import SyncSessionLocal

    try:
        with SyncSessionLocal() as session:
            doc = session.get(Document, doc_id)
            if doc is not None and doc.status == "deleting":
                doc.status = "failed"
                session.commit()
    except Exception:
        logger.exception("标记文档 %s 删除失败状态出错", doc_id)


@celery_app.task(bind=True, name="ingest.purge_archived", max_retries=2)
def purge_archived_versions_task(self):
    """定时清理已过 purge_after 窗口的 archived 版本（§3.1.5 版本清理）。

    replace 策略下旧版本只被标记 archived + searchable=false，其 PG chunks、
    Milvus 向量与 MinIO 原文件此前无人回收，数据只增不减。本任务由 Celery Beat
    每日触发，删除顺序与 delete_document_task 一致：先删外部存储（幂等可重试），
    全部成功后再一次性提交 PG。
    """
    from datetime import date

    from app.clients import milvus_client
    from app.clients.minio_client import delete_object
    from app.db.session import SyncSessionLocal

    purged, skipped, errors = 0, 0, []
    with SyncSessionLocal() as session:
        due = session.execute(
            select(DocumentVersion).where(
                DocumentVersion.status == "archived",
                DocumentVersion.purge_after.isnot(None),
                DocumentVersion.purge_after <= date.today(),
            )
        ).scalars().all()

        for v in due:
            version_id = v.id
            try:
                doc = session.get(Document, v.doc_id)
                kb_id = doc.kb_id if doc is not None else None
                # 防御：当前生效版本绝不能被清理（异常数据保护）
                if doc is not None and doc.current_version == v.version:
                    skipped += 1
                    continue

                chunk_ids = session.execute(
                    select(ChunkORM.id).where(ChunkORM.version_id == version_id)
                ).scalars().all()
                source_uri = v.source_uri

                # ① 先删外部存储（删除幂等，失败可下次重试）
                if kb_id and chunk_ids:
                    milvus_client.delete_by_ids(kb_id, list(chunk_ids))
                if source_uri:
                    delete_object(source_uri)

                # ② 再一次性提交 PG：审计任务解绑 → chunks → version
                session.query(IngestTask).filter(IngestTask.version_id == version_id).update(
                    {"version_id": None}, synchronize_session=False
                )
                session.query(ChunkORM).filter(ChunkORM.version_id == version_id).delete(
                    synchronize_session=False
                )
                session.delete(v)
                session.commit()
                purged += 1
            except Exception as e:
                session.rollback()
                logger.exception("清理 archived 版本 %s 失败", version_id)
                errors.append(f"{version_id}: {e}")

    logger.info("archived 版本清理完成: purged=%s skipped=%s errors=%s",
                purged, skipped, len(errors))
    return {"purged": purged, "skipped": skipped, "errors": errors}
