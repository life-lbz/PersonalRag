import type { ChatMessage, Citation, DocumentItem, IngestStatus, KnowledgeBase } from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

// ---- 访问令牌（L5 鉴权）：存 localStorage，所有请求统一带 Authorization ----
const TOKEN_KEY = "rag_api_token";

export class UnauthorizedError extends Error {
  constructor() {
    super("unauthorized");
  }
}

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token.trim());
}

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = getToken();
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

async function json<T>(resp: Response): Promise<T> {
  if (resp.status === 401) {
    throw new UnauthorizedError();
  }
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text.slice(0, 200)}`);
  }
  return resp.json() as Promise<T>;
}

export async function listKBs(): Promise<KnowledgeBase[]> {
  return json(await fetch(`${BASE}/knowledge-bases`, { headers: authHeaders() }));
}

export async function createKB(name: string): Promise<{ id: string }> {
  return json(await fetch(`${BASE}/knowledge-bases`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ name }),
  }));
}

export async function listDocs(kbId: string): Promise<DocumentItem[]> {
  return json(await fetch(`${BASE}/documents?kb_id=${kbId}`, { headers: authHeaders() }));
}

export async function uploadDoc(kbId: string, file: File, versionPolicy: "replace" | "coexist" = "replace"): Promise<{ task_id: string }> {
  const form = new FormData();
  form.append("file", file);
  form.append("kb_id", kbId);
  form.append("version_policy", versionPolicy);
  return json(await fetch(`${BASE}/documents/upload`, { method: "POST", headers: authHeaders(), body: form }));
}

export async function docStatus(docId: string): Promise<IngestStatus> {
  return json(await fetch(`${BASE}/documents/${docId}/status`, { headers: authHeaders() }));
}

export async function deleteDoc(docId: string): Promise<void> {
  await json(await fetch(`${BASE}/documents/${docId}`, { method: "DELETE", headers: authHeaders() }));
}

export async function renameKB(kbId: string, name: string): Promise<KnowledgeBase> {
  return json(await fetch(`${BASE}/knowledge-bases/${kbId}`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ name }),
  }));
}

export async function rollbackDoc(docId: string, version: number): Promise<void> {
  await json(await fetch(`${BASE}/documents/${docId}/versions/${version}/rollback`, { method: "POST", headers: authHeaders() }));
}

export async function sendFeedback(logId: string, feedback: number): Promise<void> {
  await fetch(`${BASE}/feedback`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
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

/** SSE 问答（POST + fetch 流式读取 getReader, 真正增量到达即回调）。
 *  kbId 传 null 表示「全部知识库」综合问答。 */
export async function chatStream(
  kbId: string | null,
  query: string,
  sessionId: string,
  mode: string,
  handlers: ChatStreamHandlers,
): Promise<void> {
  const resp = await fetch(`${BASE}/chat/completions`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ kb_id: kbId, query, session_id: sessionId, mode }),
  });
  if (resp.status === 401) {
    throw new UnauthorizedError();
  }
  if (!resp.ok || !resp.body) {
    throw new Error(`chat failed: ${resp.status}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const processEvent = (raw: string) => {
    const line = raw.trim();
    if (!line.startsWith("data:")) return;
    let ev: Record<string, unknown>;
    try {
      ev = JSON.parse(line.slice(5).trim());
    } catch {
      return;
    }
    if (ev.error) handlers.onError((ev.error as { code: string; message: string }).code, (ev.error as { message: string }).message);
    else if (ev.citations) handlers.onCitations(ev.citations as Citation[]);
    else if (ev.done) handlers.onDone((ev.route as string) ?? "", (ev.latency_ms as number) ?? 0);
    else if (ev.delta) handlers.onDelta(ev.delta as string);
    else if (ev.route) handlers.onMeta(ev.route as string, (ev.log_id as string) ?? "");
  };

  try {
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // SSE 事件以 \n\n 分隔，按边界切分
      let idx: number;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const event = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        if (event.trim()) processEvent(event);
      }
    }
    // 处理缓冲区里最后残留的事件
    if (buffer.trim()) processEvent(buffer);
  } finally {
    reader.releaseLock();
  }
}
