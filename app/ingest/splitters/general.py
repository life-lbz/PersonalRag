"""general 父子切分器：child=256/parent=1024/overlap=0.1，中文断句感知，标题路径前置。

同时承担 paper(hierarchy)/book(group) 结构切分（StructureSplitter 复用本模块）。
"""
from __future__ import annotations

from app.ingest.parsers.base import Block, ParsedDocument
from app.ingest.tokenizer import count_tokens

from ..config_ingest import get_splitter_general_config
from .base import Chunk
from .sentences import split_sentences


def _chapter_prefix(chapter_path: list[str]) -> str:
    return " > ".join(chapter_path) if chapter_path else ""


def iter_logical_units(blocks: list[Block]):
    """产出 (chapter_path, unit_type, content, metadata)。
    unit_type: heading 后的连续文本归组；表格独立；图片独立。"""
    chapter_path: list[str] = []
    for b in blocks:
        if b.block_type == "heading":
            level = max(1, b.level or 1)
            chapter_path = chapter_path[: level - 1]
            chapter_path.append(b.content.strip())
            continue
        yield chapter_path, b


def make_parent(text_units: list[str], parent_id: str | None, chapter_path: list[str],
                metadata: dict, doc_id: str, is_parent: bool = False) -> Chunk:
    prefix = _chapter_prefix(chapter_path)
    content = f"{prefix}\n{text_units[0]}" if prefix else text_units[0]
    for u in text_units[1:]:
        content += "\n" + u
    md = dict(metadata)
    md["chapter_path"] = list(chapter_path)
    return Chunk(doc_id=doc_id, parent_id=parent_id, content=content,
                 token_count=count_tokens(content), is_parent=is_parent, metadata=md)


def split_general(doc: ParsedDocument, doc_id: str, version_id: str = "") -> tuple[list[Chunk], list[Chunk]]:
    """返回 (子块列表[含检索块], 父块列表)。父子切分：父块=上下文单元(1024)，子块=检索单元(256)。"""
    cfg = get_splitter_general_config()
    child_tokens, parent_tokens = cfg["child_tokens"], cfg["parent_tokens"]
    overlap_ratio = cfg.get("overlap_ratio", 0.1)
    table_ctx_window = cfg.get("table_context_window", 256)

    parents: list[Chunk] = []
    children: list[Chunk] = []
    all_units = list(iter_logical_units(doc.blocks))
    last_heading_idx = -1

    # 第一步：按 parent_tokens 累积父块（heading 优先断开）
    parent_groups: list[list[tuple[list[str], object]]] = []  # [ [(chapter_path, block), ...] ]
    cur_group: list[tuple[list[str], object]] = []
    cur_tokens = 0
    prev_path: list[str] | None = None
    for chapter_path, b in all_units:
        heading_break = prev_path is not None and chapter_path != prev_path
        bt = count_tokens(b.content)
        if cur_group and (heading_break or cur_tokens + bt > parent_tokens):
            parent_groups.append(cur_group)
            cur_group, cur_tokens = [], 0
        cur_group.append((chapter_path, b))
        cur_tokens += bt
        prev_path = chapter_path
    if cur_group:
        parent_groups.append(cur_group)

    # 第二步：父块内切子块
    text_units_cache: list[tuple[list[str], list[str], dict]] = []  # 供表格上下文用: (path, sentences, md)
    for group in parent_groups:
        group_path = group[0][0]
        parent_chunk = make_parent([b.content for _, b in group], None, group_path,
                                   group[0][1].metadata or {}, doc_id, is_parent=True)
        parent_idx = len(parents)
        parents.append(parent_chunk)

        sentences_with_meta: list[tuple[list[str], str, object]] = []
        for chapter_path, b in group:
            if b.block_type == "table":
                sentences_with_meta.append((chapter_path, b.content, b))
            else:
                for s in split_sentences(b.content):
                    sentences_with_meta.append((chapter_path, s, b))

        # 句子累积到 child_tokens，带 overlap
        child_buf: list[tuple[str, object]] = []  # (sentence, block)
        child_tokens_acc = 0
        prev_sent_for_overlap: list[str] = []
        for chapter_path, sent, blk in sentences_with_meta:
            st = count_tokens(sent)
            if child_buf and child_tokens_acc + st > child_tokens:
                _emit_child(children, parent_idx, group_path, child_buf, doc_id, blk)
                # overlap: 取上一子块尾部句子
                keep = max(1, int(child_tokens * overlap_ratio / max(st, 1)))
                child_buf = child_buf[-keep:] if keep > 0 else []
                child_tokens_acc = sum(count_tokens(s) for s, _ in child_buf)
            child_buf.append((sent, blk))
            child_tokens_acc += st
        if child_buf:
            _emit_child(children, parent_idx, group_path, child_buf, doc_id, group[-1][1])

    _apply_table_context(children, table_ctx_window)
    return children, parents


def _emit_child(children: list[Chunk], parent_idx: int, chapter_path: list[str],
                buf: list[tuple[str, object]], doc_id: str, last_blk) -> None:
    prefix = _chapter_prefix(chapter_path)
    content = "\n".join(s for s, _ in buf)
    if prefix:
        content = f"{prefix}\n{content}"
    md = dict(getattr(last_blk, "metadata", {}) or {})
    md["chapter_path"] = list(chapter_path)
    md["page"] = getattr(last_blk, "page", None)
    if any(getattr(b, "block_type", "") == "table" for _, b in buf):
        md["block_type"] = "table"
    children.append(
        Chunk(doc_id=doc_id, parent_id=f"PARENT_{parent_idx}", content=content,
              token_count=count_tokens(content), metadata=md)
    )


def _apply_table_context(children: list[Chunk], window: int) -> None:
    """表格块入库时附加前后窗口正文作为检索字段（展示仍回表格本体）。"""
    for i, c in enumerate(children):
        if c.metadata.get("block_type") != "table":
            continue
        before = children[i - 1].content if i > 0 else ""
        after = children[i + 1].content if i + 1 < len(children) else ""
        ctx = (before[-window * 4:] if before else "") + "\n" + (after[: window * 4] if after else "")
        c.metadata["context_text"] = f"{c.content}\n【上下文】{ctx.strip()}" if ctx.strip() else c.content


# ---------- 结构切分（paper: hierarchy / book: group）----------
def split_structure(doc: ParsedDocument, doc_id: str, mode: str = "hierarchy") -> tuple[list[Chunk], list[Chunk]]:
    """hierarchy: 块带完整父标题路径；group: 相邻小节合并成组。"""
    children, parents = split_general(doc, doc_id)
    if mode == "group":
        for c in children:
            c.content = c.content  # group 模式下 general 的分组累积已近似小节合并
    return children, parents


def split_qa(doc: ParsedDocument, doc_id: str) -> tuple[list[Chunk], list[Chunk]]:
    """问答对成块：识别 Q/A 结构（**问** / 答：或 Q:/A:）。"""
    import re

    qa_re = re.compile(r"(?:^|\n)\s*(?:Q|问)\s*[:：.、]\s*(.+?)(?:\n\s*(?:A|答)\s*[:：.、]\s*(.+?))(?=\n\s*(?:Q|问)\s*[:：]|$)", re.S)
    children: list[Chunk] = []
    parents: list[Chunk] = []
    full_text = "\n\n".join(b.content for b in doc.blocks)
    for m in qa_re.finditer(full_text):
        q, a = m.group(1).strip(), (m.group(2) or "").strip()
        content = f"问：{q}\n答：{a}"
        children.append(Chunk(doc_id=doc_id, content=content, token_count=count_tokens(content),
                              metadata={"qa_question": q}))
        parents.append(Chunk(doc_id=doc_id, content=content, token_count=count_tokens(content), is_parent=True))
    if not children:  # 无 QA 结构降级 general
        return split_general(doc, doc_id)
    return children, parents


def split_table(doc: ParsedDocument, doc_id: str) -> tuple[list[Chunk], list[Chunk]]:
    """表格逐行切块+表头注入；非表格块走 general。"""
    import re as _re

    from .base import Chunk as C

    children: list[Chunk] = []
    parents: list[Chunk] = []
    chapter_path: list[str] = []
    for b in doc.blocks:
        if b.block_type == "heading":
            level = max(1, b.level or 1)
            chapter_path = chapter_path[: level - 1]
            chapter_path.append(b.content.strip())
            continue
        prefix = _chapter_prefix(chapter_path)
        if b.block_type == "table":
            rows, header = _parse_html_rows(b.content)
            for row in rows:
                line = "；".join(f"{h}:{v}" for h, v in zip(header, row) if v)
                content = f"{prefix}\n{line}" if prefix else line
                md = dict(b.metadata or {})
                md.update({"block_type": "table", "chapter_path": list(chapter_path), "page": b.page})
                children.append(C(doc_id=doc_id, content=content, token_count=count_tokens(content), metadata=md))
            if rows:
                header_line = " | ".join(header)
                parents.append(C(doc_id=doc_id, content=f"{prefix}\n{header_line}".strip(),
                                 token_count=count_tokens(f"{prefix}\n{header_line}"), is_parent=True,
                                 metadata={"block_type": "table"}))
        else:
            chunk = C(doc_id=doc_id,
                      content=f"{prefix}\n{b.content}" if prefix else b.content,
                      token_count=count_tokens(b.content),
                      metadata={"chapter_path": list(chapter_path), "page": b.page})
            children.append(chunk)
            parents.append(C(doc_id=doc_id, content=chunk.content, token_count=chunk.token_count,
                             is_parent=True, metadata=dict(chunk.metadata)))
    _apply_table_context(children, 256)
    return children, parents


def _parse_html_rows(html: str) -> tuple[list[list[str]], list[str]]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        return [], []
    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)
    header = rows[0] if rows else []
    body = rows[1:] if len(rows) > 1 else []
    return body, header


def split_page(doc: ParsedDocument, doc_id: str) -> tuple[list[Chunk], list[Chunk]]:
    """presentation：每页一块。"""
    children, parents = [], []
    for b in doc.blocks:
        page_no = b.metadata.get("slide") or b.page
        content = b.content
        c = Chunk(doc_id=doc_id, content=content, token_count=count_tokens(content),
                  metadata={"page": page_no, **(b.metadata or {})})
        children.append(c)
        parents.append(Chunk(doc_id=doc_id, content=content, token_count=count_tokens(content),
                             is_parent=True, metadata=dict(c.metadata)))
    return children, parents


def split_email(doc: ParsedDocument, doc_id: str) -> tuple[list[Chunk], list[Chunk]]:
    """eml：头部字段+正文+附件清单整块。"""
    content = "\n\n".join(b.content for b in doc.blocks)
    c = Chunk(doc_id=doc_id, content=content, token_count=count_tokens(content),
              metadata={"doc_type": "email"})
    return [c], [Chunk(doc_id=doc_id, content=content, token_count=count_tokens(content), is_parent=True)]
