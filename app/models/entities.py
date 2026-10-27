"""PostgreSQL ORM 模型，依据《RAG系统方案设计文档.md》§4.1。"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def gen_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    retrieval_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    """逻辑文档（稳定标识，不含版本信息）。"""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    kb_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("knowledge_bases.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(512))
    doc_type: Mapped[str] = mapped_column(String(32))
    current_version: Mapped[int] = mapped_column(Integer, default=0)  # active 版本指针
    version_policy: Mapped[str] = mapped_column(String(16), default="replace")  # replace|coexist
    status: Mapped[str] = mapped_column(String(16), default="processing")
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DocumentVersion(Base):
    """文档版本（每次入库一行）。"""

    __tablename__ = "document_versions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    doc_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("documents.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_uri: Mapped[str | None] = mapped_column(Text)  # 该版本 MinIO 原文件
    content_hash: Mapped[str | None] = mapped_column(String(64))  # 版本判定+幂等依据
    status: Mapped[str] = mapped_column(String(16), default="processing")  # processing/active/archived/superseded
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    purge_after: Mapped[date | None] = mapped_column(Date)  # archived 版本的清理窗口
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)  # 法规: effective_date/version_no 等
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = ({"comment": "UNIQUE(doc_id, version)"},)


class Chunk(Base):
    """切片（挂 version_id，版本间隔离）。"""

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # hash(version_id+content)
    version_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("document_versions.id"), nullable=False)
    doc_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("documents.id"), nullable=False)  # 冗余, 便于按文档级联
    chunk_index: Mapped[int | None] = mapped_column(Integer)
    parent_id: Mapped[str | None] = mapped_column(String(64))
    prev_id: Mapped[str | None] = mapped_column(String(64))
    next_id: Mapped[str | None] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer)
    chapter_path: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    milvus_id: Mapped[str | None] = mapped_column(String(64))
    searchable: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)


class LawArticle(Base):
    """法规扩展（领域插件）。"""

    __tablename__ = "law_articles"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    doc_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("documents.id"), nullable=False)
    law_name: Mapped[str | None] = mapped_column(String(256))
    law_level: Mapped[str | None] = mapped_column(String(32))
    doc_number: Mapped[str | None] = mapped_column(String(64))
    article_no: Mapped[str | None] = mapped_column(String(32))
    chapter_path: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    effective_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String(16))
    version: Mapped[str | None] = mapped_column(String(32))


class IngestTask(Base):
    """入库任务。"""

    __tablename__ = "ingest_tasks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    doc_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("documents.id"))
    version_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("document_versions.id"))
    stage: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(16))  # pending/running/done/failed
    error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class QueryLog(Base):
    """检索日志（评估/反馈回流）。"""

    __tablename__ = "query_logs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    session_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    query: Mapped[str | None] = mapped_column(Text)
    route: Mapped[str | None] = mapped_column(String(16))
    plan: Mapped[dict | None] = mapped_column(JSONB)
    retrieved_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String(64)))
    rerank_scores: Mapped[list[float] | None] = mapped_column(ARRAY(Float))
    answer: Mapped[str | None] = mapped_column(Text)
    feedback: Mapped[int | None] = mapped_column(Integer)  # 1赞/-1踩/null
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
