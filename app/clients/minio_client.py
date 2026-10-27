"""MinIO 客户端：原文件存取。"""
from __future__ import annotations

import io
from urllib.parse import quote

from minio import Minio

from app.config import settings

_client: Minio | None = None


def get_minio() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            settings.minio.endpoint,
            access_key=settings.minio.access_key,
            secret_key=settings.minio.secret_key,
            secure=False,
        )
        if not _client.bucket_exists(settings.minio.bucket):
            _client.make_bucket(settings.minio.bucket)
    return _client


def upload_bytes(object_key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """上传字节流，返回对象 key。"""
    client = get_minio()
    client.put_object(
        settings.minio.bucket, object_key, io.BytesIO(data), length=len(data), content_type=content_type
    )
    return object_key


def download_bytes(object_key: str) -> bytes:
    client = get_minio()
    resp = client.get_object(settings.minio.bucket, object_key)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()


def delete_object(object_key: str) -> None:
    client = get_minio()
    client.remove_object(settings.minio.bucket, object_key)


def presigned_get_url(object_key: str, expires_hours: int = 1) -> str:
    client = get_minio()
    from datetime import timedelta

    return client.presigned_get_object(
        settings.minio.bucket, object_key, expires=timedelta(hours=expires_hours)
    )


def build_object_key(kb_id: str, doc_id: str, filename: str) -> str:
    """对象 key 规则：kb/{kb_id}/doc/{doc_id}/{filename}。"""
    safe_name = quote(filename, safe="")
    return f"kb/{kb_id}/doc/{doc_id}/{safe_name}"
