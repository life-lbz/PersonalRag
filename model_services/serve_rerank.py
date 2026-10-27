"""serve_rerank.py —— bge-reranker-base（方案E选定, CPU）。

启动: python model_services/serve_rerank.py   (:8002)
注意: 必须用模型收 body（pydantic），标量参数会被 FastAPI 解析为查询参数导致 422。
"""
from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

MODEL_DIR = os.environ.get("BGE_RERANKER_DIR", "C:/Users/20832/.cache/models/bge-reranker-base")
USE_FP16 = os.environ.get("BGE_USE_FP16", "0") == "1"
PORT = int(os.environ.get("RERANK_PORT", "8002"))

app = FastAPI(title="bge-reranker-base service")
_model = None


def get_model():
    global _model
    if _model is None:
        from FlagEmbedding import FlagReranker

        _model = FlagReranker(MODEL_DIR, use_fp16=USE_FP16)
    return _model


class RerankReq(BaseModel):
    query: str
    documents: list[str]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/rerank")
def rerank(req: RerankReq):
    model = get_model()
    scores = model.compute_score([[req.query, d] for d in req.documents],
                                 normalize=True, batch_size=16)
    if not isinstance(scores, list):
        scores = [scores]
    return {"scores": [float(s) for s in scores]}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
