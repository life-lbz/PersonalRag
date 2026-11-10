import type { Session } from "./types";

const KEY = "rag_sessions_v1";

export function loadSessions(): Session[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const list = JSON.parse(raw) as Session[];
    return Array.isArray(list) ? list.filter((s) => s && s.id) : [];
  } catch {
    return [];
  }
}

export function saveSessions(list: Session[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(list.slice(0, 200)));
  } catch {
    /* 超出配额时静默降级，不影响对话 */
  }
}

export function newSession(kbId: string): Session {
  const now = Date.now();
  return {
    id: crypto.randomUUID(),
    title: "新对话",
    pinned: false,
    kbId,
    createdAt: now,
    updatedAt: now,
    messages: [],
  };
}

/** 从首条用户问题生成标题。 */
export function deriveTitle(text: string): string {
  const t = text.trim().replace(/\s+/g, " ");
  return t.length > 24 ? `${t.slice(0, 24)}…` : t || "新对话";
}
