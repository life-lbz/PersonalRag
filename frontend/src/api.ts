import type { ChatMessage, Citation, DocumentItem, IngestStatus, KnowledgeBase } from "./types";

const BASE = "/api/v1";

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text.slice(0, 200)}`);
  }
  return resp.json() as Promise<T>;
}

export async function listKBs(): Promise<KnowledgeBase[]> {
  return json(await fetch(`${BASE}/knowledge-bases`));
}

export async function createKB(name: string): Promise<{ id: string }> {
  return json(await fetch(`${BASE}/knowledge-bases`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  }));
}

export async function listDocs(kbId: string): Promise<DocumentItem[]> {
  return json(await fetch(`${BASE}/documents?kb_id=${kbId}`));
}

export async function uploadDoc(kbId: string, file: File, versionPolicy: "replace" | "coexist" = "replace"): Promise<{ task_id: string }> {
  const form = new FormData();
  form.append("file", file);
  form.append("kb_id", kbId);
  form.append("version_policy", versionPolicy);
  return json(await fetch(`${BASE}/documents/upload`, { method: "POST", body: form }));
}

export async function docStatus(docId: string): Promise<IngestStatus> {
  return json(await fetch(`${BASE}/documents/${docId}/status`));
}

export async function deleteDoc(docId: string): Promise<void> {
  await json(await fetch(`${BASE}/documents/${docId}`, { method: "DELETE" }));
}

export async function renameKB(kbId: string, name: string): Promise<KnowledgeBase> {
  return json(await fetch(`${BASE}/knowledge-bases/${kbId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  }));
}

export async function rollbackDoc(docId: string, version: number): Promise<void> {
  await json(await fetch(`${BASE}/documents/${docId}/versions/${version}/rollback`, { method: "POST" }));
}

export async function sendFeedback(logId: string, feedback: number): Promise<void> {
  await fetch(`${BASE}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ log_id: logId, feedback }),
  });
}

export interface ChatStreamHandlers {
  onDelta: (text: string) => void;
  onMeta: (route: string, logId: string) => void;
  onCitations: (citations: Citation[]) => void;
  onDone: (route: string, latency: number) => void;
  onError: (code: string, message: string) => void;
}

/** SSE 问答（POST + fetch 流式解析, 按接口契约事件分发）。 */
export async function chatStream(
  kbId: string,
  query: string,
  sessionId: string,
  mode: string,
  handlers: ChatStreamHandlers,
): Promise<void> {
  const resp = await fetch(`${BASE}/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kb_id: kbId, query, session_id: sessionId, mode }),
  });
  if (!resp.ok || !resp.body) {
    throw new Error(`chat failed: ${resp.status}`);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      try {
        const ev = JSON.parse(line.slice(5).trim());
        if (ev.error) handlers.onError(ev.error.code, ev.error.message);
        else if (ev.citations) handlers.onCitations(ev.citations);
        else if (ev.done) handlers.onDone(ev.route ?? "", ev.latency_ms ?? 0);
        else if (ev.delta) handlers.onDelta(ev.delta);
        else if (ev.route) handlers.onMeta(ev.route, ev.log_id ?? "");
      } catch {
        /* 忽略不完整事件 */
      }
    }
  }
}
