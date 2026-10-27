"""切分输出统一结构：Chunk（依据《RAG系统方案设计文档.md》§3.1.3）。"""
from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field

from app.ingest.tokenizer import count_tokens


def make_chunk_id(version_id: str, content: str) -> str:
    """hash(version_id + content)：同版本重跑可去重，跨版本内容相同也不冲突(P0-1)。"""
    return hashlib.sha256(f"{version_id}:{content}".encode()).hexdigest()


class Chunk(BaseModel):
    chunk_id: str = ""
    doc_id: str
    parent_id: str | None = None
    prev_id: str | None = None      # 同层相邻(滑窗扩展用)
    next_id: str | None = None
    content: str                    # 已注入章节路径前缀
    token_count: int = 0
    is_parent: bool = False         # 父块(仅上下文组装用, 不入向量索引)
    metadata: dict = Field(default_factory=dict)

    def model_post_init(self, __context) -> None:  # noqa: N805
        if not self.chunk_id:
            self.chunk_id = make_chunk_id("", self.content)
        if not self.token_count:
            self.token_count = count_tokens(self.content)


def finalize_chunk_ids(chunks: list[Chunk], version_id: str) -> list[Chunk]:
    """用 version_id 生成正式 chunk_id 并按列表顺序重建 prev/next 链。"""
    for c in chunks:
        c.chunk_id = make_chunk_id(version_id, c.content)
    for prev, cur in zip(chunks, chunks[1:]):
        prev.next_id = cur.chunk_id
        cur.prev_id = prev.chunk_id
    return chunks
