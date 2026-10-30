"""基础测试（M8）：不依赖 PG/Redis/Milvus/模型服务，聚焦纯函数与 API 参数校验。

运行：pytest -q
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.documents import _check_signature
from app.config import settings
from app.db.session import get_async_session
from app.ingest.splitters.base import Chunk, finalize_chunk_ids, make_chunk_id
from app.ingest.store import _to_milvus_sparse
from app.ingest.version import _policy_for
from app.main import app


def test_signature_pdf():
    assert _check_signature(".pdf", b"%PDF-1.7\nrest") is None
    assert _check_signature(".pdf", b"MZ\x90\x00") is not None


def test_signature_rejects_disguised_binary():
    assert _check_signature(".txt", "正常文本".encode()) is None
    assert _check_signature(".txt", b"MZ\x90\x00\x00binary") is not None


def test_signature_json_html():
    assert _check_signature(".json", b'{"a": 1}') is None
    assert _check_signature(".json", b"not json") is not None
    assert _check_signature(".html", b"<!DOCTYPE html><html></html>") is None
    assert _check_signature(".html", b"plain") is not None


def test_chunk_id_and_neighbor_chain():
    chunks = [Chunk(doc_id="d", content="a", token_count=1),
              Chunk(doc_id="d", content="b", token_count=1)]
    finalize_chunk_ids(chunks, "v1")
    assert chunks[0].next_id == chunks[1].chunk_id
    assert chunks[1].prev_id == chunks[0].chunk_id
    assert make_chunk_id("v1", "a") == make_chunk_id("v1", "a")
    assert make_chunk_id("v1", "a") != make_chunk_id("v2", "a")


def test_sparse_conversion_skips_bad_keys():
    assert _to_milvus_sparse({"1": 0.5, "x": 0.3, "2": "0.7"}) == {1: 0.5, 2: 0.7}


def test_version_policy_by_doc_type():
    assert _policy_for("law") == "coexist"
    assert _policy_for("general") == "replace"


def test_chat_rejects_unknown_kb():
    class _FakeSession:
        async def get(self, model, pk):
            return None

    async def _fake_session():
        yield _FakeSession()

    app.dependency_overrides[get_async_session] = _fake_session
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/chat/completions",
                json={"kb_id": "missing", "query": "hi"},
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_auth_middleware(monkeypatch):
    """L5: 开启鉴权后业务接口需 token，/health 保持公开。"""
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "tokens", ["secret-token"])
    with TestClient(app) as client:
        assert client.get("/api/v1/documents?kb_id=x").status_code == 401
        assert client.get("/health").status_code == 200
