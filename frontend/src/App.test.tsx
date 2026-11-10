import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ChatStreamHandlers } from "./api";

vi.mock("./api", () => {
  class UnauthorizedError extends Error {}

  const listKBs = vi.fn(async () => [{ id: "kb-1", name: "测试知识库" }]);
  const listDocs = vi.fn(async () => []);
  const chatStream = vi.fn(
    async (_kb: string | null, _q: string, _sid: string, _mode: string, h: ChatStreamHandlers) => {
      h.onMeta("hybrid", "log-1");
      h.onDelta("报销申请须在费用发生后 30 日内提交。");
      h.onCitations([
        { n: 1, chunk_id: "c-1", doc_title: "报销与差旅规范", page: 2, rerank_score: 0.91 },
      ]);
      h.onDone("hybrid", 456);
    },
  );

  return {
    UnauthorizedError,
    listKBs,
    listDocs,
    chatStream,
    createKB: vi.fn(),
    renameKB: vi.fn(),
    deleteDoc: vi.fn(),
    rollbackDoc: vi.fn(),
    uploadDoc: vi.fn(),
    sendFeedback: vi.fn(),
    setToken: vi.fn(),
    docStatus: vi.fn(),
  };
});

import App from "./App";
import { chatStream } from "./api";

const readStored = () => JSON.parse(localStorage.getItem("rag_sessions_v1") ?? "[]");

const askQuestion = async (question: string) => {
  const box = await screen.findByPlaceholderText(/输入问题/);
  fireEvent.change(box, { target: { value: question } });
  fireEvent.keyDown(box, { key: "Enter" });
};

describe("App 会话持久化", () => {
  beforeEach(() => localStorage.clear());

  it("首轮问答后把会话写入 localStorage（标题/消息/引用齐全）", async () => {
    render(<App />);
    await askQuestion("报销流程怎么走？");

    await waitFor(() => expect(screen.getByText(/30 日内提交/)).toBeInTheDocument());
    // 引用卡片与真实界面同样渲染
    expect(screen.getByText("报销与差旅规范")).toBeInTheDocument();
    expect(screen.getByText("相似度 0.91")).toBeInTheDocument();

    await waitFor(() => expect(readStored()).toHaveLength(1), { timeout: 2000 });
    const [session] = readStored();
    expect(session.title).toBe("报销流程怎么走？");
    // 未指定知识库 → 走「全部知识库」综合问答
    expect(session.kbId).toBe("");
    expect(vi.mocked(chatStream).mock.calls[0][0]).toBeNull();
    expect(session.messages).toHaveLength(2);
    expect(session.messages[0]).toMatchObject({ role: "user", content: "报销流程怎么走？" });
    expect(session.messages[1]).toMatchObject({
      role: "assistant",
      route: "hybrid",
      latency_ms: 456,
      logId: "log-1",
    });
    expect(session.messages[1].citations).toHaveLength(1);
    expect(session.messages[1].citations[0]).toMatchObject({
      doc_title: "报销与差旅规范",
      rerank_score: 0.91,
    });
  });

  it("重新挂载后从 localStorage 恢复历史消息", async () => {
    const first = render(<App />);
    await askQuestion("年假怎么算？");
    await waitFor(() => expect(readStored()).toHaveLength(1), { timeout: 2000 });
    first.unmount();

    render(<App />);
    expect(await screen.findByText(/30 日内提交/)).toBeInTheDocument();
    // 恢复后侧栏应出现该会话标题
    expect(screen.getAllByText("年假怎么算？").length).toBeGreaterThan(0);
  });

  it("连续两轮对话追加到同一会话，不新建会话", async () => {
    render(<App />);
    await askQuestion("第一个问题");
    await waitFor(() => expect(readStored()).toHaveLength(1), { timeout: 2000 });

    await askQuestion("第二个问题");
    await waitFor(() => expect(readStored()[0].messages).toHaveLength(4), { timeout: 2000 });

    const stored = readStored();
    expect(stored).toHaveLength(1);
    expect(stored[0].title).toBe("第一个问题"); // 标题保持首问
    expect(stored[0].messages.map((m: { role: string }) => m.role)).toEqual([
      "user",
      "assistant",
      "user",
      "assistant",
    ]);
  });

  it("点击「新对话」产生第二个空会话并切换过去", async () => {
    render(<App />);
    await askQuestion("已有会话");
    await waitFor(() => expect(readStored()).toHaveLength(1), { timeout: 2000 });

    fireEvent.click(await screen.findByText("新对话"));
    await waitFor(() => expect(readStored()).toHaveLength(2), { timeout: 2000 });
    expect(readStored()[0].messages).toEqual([]);
  });
});
