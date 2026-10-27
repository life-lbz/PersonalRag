"""版本管理：版本判定 / 创建 / 灰度切换 / 回滚（§3.1.5、§5.3）。

核心抽象：doc_id=逻辑文档稳定标识，version_id=入库实例，chunks 挂 version_id。
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.entities import Chunk, Document, DocumentVersion

logger = logging.getLogger(__name__)


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_version(session: Session, kb_id: str, title: str, c_hash: str,
                    doc_id: str | None = None, doc_type: str = "general",
                    version_policy: str | None = None) -> tuple[Document, DocumentVersion, bool]:
    """版本判定（§3.1.5）：返回 (document, version, created)。
    - 显式 doc_id → 指定文档
    - 无匹配 → 新文档 v1
    - content_hash 相同 → 幂等拒绝（返回已存在版本, created=False）
    - hash 不同 → 新版本 version+1
    - version_policy：replace（覆盖式，旧版标记 archived 后续清理）/ coexist（并存式，所有版本可召回）
      仅在新文档创建时生效；已有文档的后续上传沿用原 policy。
    """
    if doc_id:
        doc = session.get(Document, doc_id)
        if doc is None:
            raise ValueError(f"指定 doc_id {doc_id} 不存在")
    else:
        doc = session.execute(
            select(Document).where(Document.kb_id == kb_id, Document.title == title)
        ).scalar_one_or_none()
        if doc is None:
            doc = Document(kb_id=kb_id, title=title or "未命名", doc_type=doc_type,
                           version_policy=version_policy or _policy_for(doc_type))
            session.add(doc)
            session.flush()

    latest = session.execute(
        select(DocumentVersion).where(DocumentVersion.doc_id == doc.id)
        .order_by(DocumentVersion.version.desc()).limit(1)
    ).scalar_one_or_none()

    if latest and latest.content_hash == c_hash:
        return doc, latest, False  # 幂等：同内容已入库

    new_version = DocumentVersion(
        doc_id=doc.id,
        version=(latest.version + 1) if latest else 1,
        content_hash=c_hash,
        status="processing",
    )
    session.add(new_version)
    session.flush()
    return doc, new_version, True


def _policy_for(doc_type: str) -> str:
    return settings.ingest.version.policy_by_doc_type.get(doc_type, settings.ingest.version.default_policy)


def promote_version(session: Session, doc: Document, version: DocumentVersion, chunk_count: int) -> None:
    """灰度切换（PG 单事务）：旧版置 archived/superseded，新版置 active 且 searchable=true。

    replace: 仅 active 版本 searchable=true（旧版置 false 走清理窗口）
    coexist: active 与 superseded 均 searchable=true（历史版本可召回, 时效由元数据过滤）
    """
    policy = doc.version_policy
    old_versions = session.execute(
        select(DocumentVersion).where(
            DocumentVersion.doc_id == doc.id, DocumentVersion.id != version.id
        )
    ).scalars().all()

    for ov in old_versions:
        if policy == "coexist":
            ov.status = "superseded"           # 不清理; searchable 保持 true
        else:
            ov.status = "archived"             # 窗口期后清理
            ov.purge_after = date.today() + timedelta(days=settings.ingest.version.purge_window_days)
            _set_version_searchable(session, ov.id, False)

    version.status = "active"
    version.chunk_count = chunk_count
    _set_version_searchable(session, version.id, True)
    doc.current_version = version.version
    doc.status = "active"
    doc.doc_type = doc.doc_type or "general"
    session.flush()


def _set_version_searchable(session: Session, version_id: str, val: bool) -> None:
    chunks = session.execute(select(Chunk).where(Chunk.version_id == version_id)).scalars().all()
    for c in chunks:
        c.searchable = val


def rollback_to_version(session: Session, doc: Document, target_version_no: int) -> bool:
    """回滚（覆盖式）：current_version 指针切回旧版 + 旧版 chunks searchable=true。"""
    target = session.execute(
        select(DocumentVersion).where(
            DocumentVersion.doc_id == doc.id, DocumentVersion.version == target_version_no
        )
    ).scalar_one_or_none()
    if target is None:
        return False
    if target.status == "archived" and target.purge_after and target.purge_after < date.today():
        return False  # 已过窗口且清理, 需从 MinIO 重走入库链

    policy = doc.version_policy
    others = session.execute(
        select(DocumentVersion).where(
            DocumentVersion.doc_id == doc.id, DocumentVersion.id != target.id
        )
    ).scalars().all()
    for ov in others:
        if policy == "coexist":
            ov.status = "superseded"
        else:
            ov.status = "archived"
            ov.purge_after = date.today() + timedelta(days=settings.ingest.version.purge_window_days)
            _set_version_searchable(session, ov.id, False)
    target.status = "active"
    _set_version_searchable(session, target.id, True)
    doc.current_version = target.version
    session.flush()
    return True
