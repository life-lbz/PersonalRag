import type { Citation } from "../types";

/**
 * 引用卡片：编号 + 文档名 + 相似度 + 页码 + 片段摘要。
 * 相似度取 rerank 分数，保留两位小数；缺失时不渲染该项。
 */
const CitationCard: React.FC<{ c: Citation }> = ({ c }) => (
  <div className="rounded-card border border-hairline bg-white px-3.5 py-2.5 transition hover:border-brand-200">
    <div className="flex items-baseline gap-2">
      <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded bg-brand-50 text-[10px] font-semibold text-brand-700">
        {c.n}
      </span>
      <span className="truncate text-[13px] font-medium text-ink-900">{c.doc_title}</span>
      {typeof c.rerank_score === "number" && (
        <span className="shrink-0 text-[11px] text-ink-500">
          相似度 {c.rerank_score.toFixed(2)}
        </span>
      )}
      {c.page != null && <span className="shrink-0 text-[11px] text-ink-500">第 {c.page} 页</span>}
    </div>
    {c.snippet && (
      <p className="mt-1 line-clamp-2 pl-6 text-[12px] leading-relaxed text-ink-500">{c.snippet}</p>
    )}
  </div>
);

export default CitationCard;
