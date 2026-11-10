import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import CitationCard from "./CitationCard";
import type { Citation } from "../types";

const makeCitation = (over: Partial<Citation> = {}): Citation => ({
  n: 1,
  chunk_id: "c-1",
  doc_title: "报销与差旅规范",
  page: null,
  ...over,
});

describe("CitationCard", () => {
  it("渲染编号与文档名", () => {
    render(<CitationCard c={makeCitation({ n: 3, doc_title: "测试管理办法（试行）" })} />);
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("测试管理办法（试行）")).toBeInTheDocument();
  });

  it("有 rerank 分数时显示两位小数的相似度", () => {
    render(<CitationCard c={makeCitation({ rerank_score: 0.876 })} />);
    expect(screen.getByText("相似度 0.88")).toBeInTheDocument();
  });

  it("相似度为 0 时仍显示（0 是有效分数而非缺失）", () => {
    render(<CitationCard c={makeCitation({ rerank_score: 0 })} />);
    expect(screen.getByText("相似度 0.00")).toBeInTheDocument();
  });

  it("分数缺失时不渲染相似度", () => {
    render(<CitationCard c={makeCitation({ rerank_score: null })} />);
    expect(screen.queryByText(/相似度/)).not.toBeInTheDocument();
  });

  it("有页码时显示页码", () => {
    render(<CitationCard c={makeCitation({ page: 12 })} />);
    expect(screen.getByText("第 12 页")).toBeInTheDocument();
  });

  it("页码为 0 时显示（0 是有效页码）", () => {
    render(<CitationCard c={makeCitation({ page: 0 })} />);
    expect(screen.getByText("第 0 页")).toBeInTheDocument();
  });

  it("页码缺失时（null）不显示页码", () => {
    render(<CitationCard c={makeCitation({ page: null })} />);
    expect(screen.queryByText(/^第 .* 页$/)).not.toBeInTheDocument();
  });

  it("有摘要片段时渲染摘要", () => {
    render(<CitationCard c={makeCitation({ snippet: "报销申请须在费用发生后 30 日内提交。" })} />);
    expect(screen.getByText("报销申请须在费用发生后 30 日内提交。")).toBeInTheDocument();
  });

  it("摘要为空时不渲染摘要段落", () => {
    const { container } = render(<CitationCard c={makeCitation({ snippet: "" })} />);
    expect(container.querySelectorAll("p")).toHaveLength(0);
  });

  it("完整信息一次性全部渲染", () => {
    render(
      <CitationCard
        c={makeCitation({ n: 2, rerank_score: 1, page: 5, snippet: "命中片段内容" })}
      />,
    );
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("相似度 1.00")).toBeInTheDocument();
    expect(screen.getByText("第 5 页")).toBeInTheDocument();
    expect(screen.getByText("命中片段内容")).toBeInTheDocument();
  });
});
