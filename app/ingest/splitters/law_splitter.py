"""法规条文切分器：条不切；chunk 前缀 `《法名》章节路径 > 第X条`；章/节生成摘要父块。"""
from __future__ import annotations

from app.ingest.tokenizer import count_tokens

from .base import Chunk


def split_law(doc, doc_id: str) -> tuple[list[Chunk], list[Chunk]]:
    children: list[Chunk] = []
    parents: list[Chunk] = []
    law_name = (doc.metadata or {}).get("law_name", "")
    chapter_path: list[str] = []

    for b in doc.blocks:
        if b.block_type == "heading":
            level = max(1, b.level or 1)
            chapter_path = chapter_path[: level - 1]
            chapter_path.append(b.content.strip())
            # 章/节生成摘要父块
            head = " > ".join([law_name, *chapter_path]) if law_name else " > ".join(chapter_path)
            parents.append(Chunk(doc_id=doc_id, content=head, token_count=count_tokens(head),
                                 is_parent=True, metadata={"chapter_path": list(chapter_path)}))
            continue

        article_no = (b.metadata or {}).get("article_no", "")
        prefix_parts = [p for p in [law_name, *chapter_path] if p]
        prefix = " > ".join(prefix_parts)
        content = f"{prefix} > {article_no}\n{b.content}" if prefix or article_no else b.content
        md = dict(b.metadata or {})
        md["chapter_path"] = list(chapter_path)
        c = Chunk(doc_id=doc_id, content=content, token_count=count_tokens(content), metadata=md)
        c.parent_id = None  # 条即上下文单元（父块=条本体，prev/next 链由 finalize_chunk_ids 重建）
        children.append(c)
    return children, parents
