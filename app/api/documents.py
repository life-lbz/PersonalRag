"""文档管理 API：上传（multipart）/ 状态 / 版本 / 回滚 / 策略 / 删除（§6 接口契约）。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_async_session
from app.models.entities import Document, DocumentVersion, IngestTask

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    kb_id: str = Form(...),
    doc_id: str | None = Form(None),
    version_policy: str = Form("replace"),
    session: AsyncSession = Depends(get_async_session),
):
    # ① KB 存在校验
    from app.models.entities import KnowledgeBase

    if await session.get(KnowledgeBase, kb_id) is None:
        raise HTTPException(404, "知识库不存在")

    # ② 版本策略校验
    if version_policy not in ("replace", "coexist"):
        raise HTTPException(400, "version_policy 只能是 replace（覆盖式）或 coexist（并存式）")

    # ③ 文件类型白名单
    ALLOWED_EXT = {".txt", ".md", ".pdf", ".docx", ".doc", ".html", ".htm", ".json", ".csv"}
    ALLOWED_MIME = {"text/plain", "text/markdown", "application/pdf",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/msword", "text/html", "application/json", "text/csv"}
    filename = file.filename or "unnamed.txt"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            400, f"不支持的文件类型: {ext or '无扩展名'}。支持: {', '.join(sorted(ALLOWED_EXT))}"
        )

    # ③ 文件大小校验
    max_bytes = settings.ingest.upload_max_mb * 1024 * 1024
    data = await file.read()
    if len(data) > max_bytes:
        raise HTTPException(413, f"文件超过 {settings.ingest.upload_max_mb}MB 上限")
    if not data:
        raise HTTPException(400, "空文件")

    # ④ 原文件落 MinIO
    from app.clients.minio_client import upload_bytes
    import uuid

    placeholder_doc = str(uuid.uuid4())
    object_key = f"kb/{kb_id}/doc/{placeholder_doc}/{filename}"
    upload_bytes(object_key, data, content_type=file.content_type or "application/octet-stream")

    # ⑤ 建 task
    task = IngestTask(status="pending", stage="pending")
    session.add(task)
    await session.commit()
    await session.refresh(task)

    from app.ingest.tasks import run_pipeline

    run_pipeline.apply_async(
        args=[task.id, data, filename, kb_id, doc_id, None, version_policy],
        queue="high_priority",
    )
    return {"task_id": task.id, "doc_id_hint": placeholder_doc, "version_policy": version_policy}


@router.get("")
async def list_documents(kb_id: str, page: int = 1, size: int = 20,
                         session: AsyncSession = Depends(get_async_session)):
    q = select(Document).where(Document.kb_id == kb_id).order_by(Document.updated_at.desc())
    rows = (await session.execute(q.offset((page - 1) * size).limit(size))).scalars().all()
    out = []
    for d in rows:
        versions = (await session.execute(
            select(DocumentVersion).where(DocumentVersion.doc_id == d.id)
        )).scalars().all()
        active = next((v for v in versions if v.status == "active"), None)
        out.append({
            "id": d.id, "title": d.title, "doc_type": d.doc_type,
            "current_version": d.current_version, "status": d.status,
            "version_policy": d.version_policy,
            "chunk_count": active.chunk_count if active else None,
            "versions": [{"version": v.version, "status": v.status,
                          "chunk_count": v.chunk_count, "created_at": str(v.created_at)}
                         for v in versions],
            "updated_at": str(d.updated_at),
        })
    return out


@router.get("/{doc_id}/status")
async def document_status(doc_id: str, session: AsyncSession = Depends(get_async_session)):
    """入库任务状态：{status, stage, progress}。doc_id 可传文档 id 或上传返回的 task_id。"""
    from sqlalchemy import or_

    task = (await session.execute(
        select(IngestTask).where(or_(IngestTask.doc_id == doc_id, IngestTask.id == doc_id))
        .order_by(IngestTask.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if task is None:
        doc = await session.get(Document, doc_id)
        if doc is None:
            raise HTTPException(404, "文档不存在")
        return {"status": doc.status, "stage": "done", "progress": 100}
    stage_order = ["pending", "parsing", "splitting", "enhancing", "embedding", "writing", "done"]
    progress = int(stage_order.index(task.stage or "pending") / (len(stage_order) - 1) * 100) if task.status != "failed" else 0
    return {"status": task.status, "stage": task.stage, "progress": progress, "error": task.error}


@router.get("/{doc_id}/versions")
async def list_versions(doc_id: str, session: AsyncSession = Depends(get_async_session)):
    rows = (await session.execute(
        select(DocumentVersion).where(DocumentVersion.doc_id == doc_id)
        .order_by(DocumentVersion.version)
    )).scalars().all()
    return [{"version": v.version, "status": v.status, "chunk_count": v.chunk_count,
             "created_at": str(v.created_at)} for v in rows]


@router.post("/{doc_id}/versions/{version_no}/rollback")
async def rollback(doc_id: str, version_no: int, session: AsyncSession = Depends(get_async_session)):
    from app.db.session import SyncSessionLocal
    from app.ingest.version import rollback_to_version

    # rollback_to_version 是同步函数，用 SyncSession 调用
    with SyncSessionLocal() as sync_session:
        doc = sync_session.get(Document, doc_id)
        if doc is None:
            raise HTTPException(404, "文档不存在")
        ok = rollback_to_version(sync_session, doc, version_no)
        sync_session.commit()

    if not ok:
        raise HTTPException(400, "回滚失败: 版本不存在或已过清理窗口")
    return {"status": "ok", "current_version": version_no}


@router.patch("/{doc_id}")
async def update_policy(doc_id: str, version_policy: str = Form(...),
                        session: AsyncSession = Depends(get_async_session)):
    if version_policy not in ("replace", "coexist"):
        raise HTTPException(422, "version_policy 只能为 replace|coexist")
    doc = await session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "文档不存在")
    doc.version_policy = version_policy
    await session.commit()
    return {"status": "ok", "version_policy": version_policy}


@router.delete("/{doc_id}")
async def delete_document(doc_id: str, session: AsyncSession = Depends(get_async_session)):
    from app.ingest.tasks import delete_document_task

    doc = await session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "文档不存在")
    doc.status = "deleting"
    await session.commit()
    delete_document_task.apply_async(args=[doc_id], queue="high_priority")
    return {"status": "deleting"}
