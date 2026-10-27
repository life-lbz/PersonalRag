"""知识库 API。"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.models.entities import KnowledgeBase

router = APIRouter(prefix="/api/v1/knowledge-bases", tags=["knowledge-bases"])

# 合法名称：2-50 字符，允许中文/英文/数字/下划线/短横线，禁止问号等特殊字符
# 禁止：控制字符、连续空白、前后空白、纯空白
_NAME_RE = re.compile(r"^[\u4e00-\u9fa5A-Za-z0-9_\-]{2,50}$")


def _validate_name(name: str, label: str = "名称") -> str:
    name = name.strip()
    if not name:
        raise HTTPException(400, f"{label}不能为空")
    if not _NAME_RE.match(name):
        raise HTTPException(
            400, f"{label}只能包含中文、英文、数字、下划线(_)、短横线(-)，长度 2-50 字符"
        )
    # 黑名单：问号、星号、斜杠、反斜杠、冒号、分号、引号等
    BAD_CHARS = "?*\\/:;'\"<>|#$%&@+=~`!^[]{}()"
    for ch in name:
        if ch in BAD_CHARS:
            raise HTTPException(400, f"{label}不能包含非法字符: {ch}")
    return name


class KBCreate(BaseModel):
    name: str
    retrieval_config: dict = {}

    @field_validator("name")
    @classmethod
    def _clean(cls, v: str) -> str:
        return v.strip()


@router.post("")
async def create_kb(body: KBCreate, session: AsyncSession = Depends(get_async_session)):
    _validate_name(body.name, "知识库名称")
    kb = KnowledgeBase(name=body.name, retrieval_config=body.retrieval_config)
    session.add(kb)
    await session.commit()
    await session.refresh(kb)
    return {"id": kb.id, "name": kb.name, "retrieval_config": kb.retrieval_config}


@router.get("")
async def list_kbs(session: AsyncSession = Depends(get_async_session)):
    rows = (await session.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at))).scalars().all()
    return [{"id": k.id, "name": k.name, "created_at": str(k.created_at)} for k in rows]


@router.delete("/{kb_id}")
async def delete_kb(kb_id: str, session: AsyncSession = Depends(get_async_session)):
    from app.models.entities import Document

    docs = (await session.execute(select(Document).where(Document.kb_id == kb_id))).scalars().all()
    if docs:
        raise HTTPException(400, "知识库下仍有文档, 请先删除文档")
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    await session.delete(kb)
    await session.commit()
    return {"status": "ok"}


class KBRename(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _clean(cls, v: str) -> str:
        return v.strip()


@router.patch("/{kb_id}")
async def rename_kb(kb_id: str, body: KBRename, session: AsyncSession = Depends(get_async_session)):
    """重命名知识库（保留所有文档/版本/向量）。"""
    _validate_name(body.name, "知识库名称")
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    kb.name = body.name.strip()
    await session.commit()
    await session.refresh(kb)
    return {"id": kb.id, "name": kb.name, "created_at": str(kb.created_at)}
