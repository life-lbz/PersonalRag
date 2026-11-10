import { describe, expect, it, beforeEach } from "vitest";
import { deriveTitle, loadSessions, newSession, saveSessions } from "./sessions";
import type { Session } from "./types";

const KEY = "rag_sessions_v1";

const makeSession = (over: Partial<Session> = {}): Session => ({
  id: over.id ?? "s-1",
  title: over.title ?? "对话",
  pinned: over.pinned ?? false,
  kbId: over.kbId ?? "kb-1",
  createdAt: over.createdAt ?? 1,
  updatedAt: over.updatedAt ?? 1,
  messages: over.messages ?? [],
});

describe("newSession", () => {
  it("生成带默认字段的新会话，并绑定指定知识库", () => {
    const s = newSession("kb-abc");
    expect(s.kbId).toBe("kb-abc");
    expect(s.title).toBe("新对话");
    expect(s.pinned).toBe(false);
    expect(s.messages).toEqual([]);
    expect(s.createdAt).toBe(s.updatedAt);
  });

  it("每次生成的会话 id 唯一", () => {
    const ids = new Set(Array.from({ length: 50 }, () => newSession("kb").id));
    expect(ids.size).toBe(50);
  });
});

describe("deriveTitle", () => {
  it("短问题原样作为标题", () => {
    expect(deriveTitle("报销流程怎么走？")).toBe("报销流程怎么走？");
  });

  it("超过 24 个字符时截断并追加省略号", () => {
    const long = "一".repeat(30);
    const title = deriveTitle(long);
    expect(title).toBe(`${"一".repeat(24)}…`);
    expect(title.length).toBe(25);
  });

  it("压缩连续空白与换行", () => {
    expect(deriveTitle("  年假\n\n  与调休  ")).toBe("年假 与调休");
  });

  it("空字符串回退为默认标题", () => {
    expect(deriveTitle("   ")).toBe("新对话");
  });
});

describe("saveSessions / loadSessions", () => {
  beforeEach(() => localStorage.clear());

  it("保存后能原样读回", () => {
    const list = [
      makeSession({ id: "a", title: "会话 A" }),
      makeSession({ id: "b", title: "会话 B", pinned: true }),
    ];
    saveSessions(list);
    expect(loadSessions()).toEqual(list);
  });

  it("无本地数据时返回空数组", () => {
    expect(loadSessions()).toEqual([]);
  });

  it("JSON 损坏时安全返回空数组", () => {
    localStorage.setItem(KEY, "{not-json");
    expect(loadSessions()).toEqual([]);
  });

  it("过滤掉缺少 id 的非法条目", () => {
    localStorage.setItem(
      KEY,
      JSON.stringify([
        makeSession({ id: "ok" }),
        { title: "没有 id" },
        null,
        makeSession({ id: "ok2" }),
      ]),
    );
    const list = loadSessions();
    expect(list.map((s) => s.id)).toEqual(["ok", "ok2"]);
  });

  it("非数组结构返回空数组", () => {
    localStorage.setItem(KEY, JSON.stringify({ id: "x" }));
    expect(loadSessions()).toEqual([]);
  });

  it("最多持久化 200 条，超出部分丢弃", () => {
    const many = Array.from({ length: 250 }, (_, i) => makeSession({ id: `s-${i}` }));
    saveSessions(many);
    const list = loadSessions();
    expect(list).toHaveLength(200);
    expect(list[0].id).toBe("s-0");
    expect(list[199].id).toBe("s-199");
  });

  it("消息内容随会话一并持久化（含引用与反馈）", () => {
    const list = [
      makeSession({
        id: "with-msg",
        messages: [
          { role: "user", content: "问题" },
          {
            role: "assistant",
            content: "回答",
            citations: [{ n: 1, chunk_id: "c1", doc_title: "文档", page: 2, rerank_score: 0.87 }],
            feedback: 1,
            logId: "log-1",
          },
        ],
      }),
    ];
    saveSessions(list);
    expect(loadSessions()[0].messages).toEqual(list[0].messages);
  });
});
