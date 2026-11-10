import { useRef } from "react";
import type { DocumentItem, KnowledgeBase } from "../types";
import {
  IconArrowLeft,
  IconFile,
  IconPlus,
  IconSpinner,
  IconTrash,
  IconUpload,
} from "./Icons";

interface Props {
  kbs: KnowledgeBase[];
  kbId: string;
  docs: DocumentItem[];
  onSelectKb: (id: string) => void;
  onCreateKb: () => void;
  onRenameKb: (id: string, name: string) => void;
  onUpload: () => void;
  onDeleteDoc: (id: string, title: string) => void;
  onRollback: (id: string, version: number) => void;
  onBack: () => void;
}

/** 状态 → 徽章色调（与 .badge-* 组件类对应） */
const STATUS_TONE: Record<string, string> = {
  processing: "badge-warning",
  active: "badge-success",
  deleting: "badge-warning",
  failed: "badge-danger",
};

const STATUS_LABEL: Record<string, string> = {
  processing: "入库中",
  active: "正常",
  deleting: "删除中",
  failed: "失败",
};

const KnowledgePage: React.FC<Props> = ({
  kbs,
  kbId,
  docs,
  onSelectKb,
  onCreateKb,
  onRenameKb,
  onUpload,
  onDeleteDoc,
  onRollback,
  onBack,
}) => {
  const current = kbs.find((k) => k.id === kbId);
  const hiddenInput = useRef<HTMLInputElement>(null);

  return (
    <main className="flex h-full min-w-0 flex-1 flex-col bg-white">
      <header className="page-header">
        <button
          onClick={onBack}
          className="flex items-center gap-1 rounded-control px-2 py-1.5 text-[13px] text-ink-700 transition hover:bg-black/[0.04]"
        >
          <IconArrowLeft size={14} />
          问答
        </button>
        <span className="h-4 w-px bg-hairline" />
        <h1 className="page-title">知识库</h1>
        <span className="page-meta">{kbs.length} 个</span>
        <div className="flex-1" />
        <button className="btn-outline" onClick={onCreateKb}>
          <IconPlus size={14} />
          新建知识库
        </button>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* 知识库列表 */}
        <div className="w-[248px] shrink-0 overflow-y-auto border-r border-hairline bg-canvas/50 p-3">
          {kbs.length === 0 ? (
            <div className="px-2 py-6 text-center text-[12px] text-ink-500">
              暂无知识库
              <br />
              点击右上角新建
            </div>
          ) : (
            <div className="space-y-1">
              {kbs.map((k) => {
                const active = k.id === kbId;
                return (
                  <button
                    key={k.id}
                    onClick={() => onSelectKb(k.id)}
                    onDoubleClick={() => onRenameKb(k.id, k.name)}
                    title="点击查看文档 · 双击重命名"
                    className={`group relative w-full rounded-control px-3 py-2.5 text-left transition ${
                      active
                        ? "bg-white shadow-card ring-1 ring-brand-200"
                        : "hover:bg-white/70"
                    }`}
                  >
                    {active && (
                      <span className="absolute left-0 top-1/2 h-4 w-[2px] -translate-y-1/2 rounded-r bg-brand-600" />
                    )}
                    <div className="flex items-center gap-2">
                      <span
                        className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                          active ? "bg-brand-500" : "bg-ink-400/40"
                        }`}
                      />
                      <span
                        className={`flex-1 truncate text-[13px] ${
                          active ? "font-medium text-ink-900" : "text-ink-700"
                        }`}
                      >
                        {k.name}
                      </span>
                      {active && (
                        <span className="text-[11px] text-ink-500 opacity-0 transition group-hover:opacity-100">
                          重命名
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* 文档区 */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex shrink-0 items-center justify-between px-6 pb-3 pt-5">
            <div>
              <h2 className="page-title">{current?.name ?? "未选择知识库"}</h2>
              <p className="mt-0.5 page-meta">
                {docs.length} 个文档 · 支持 pdf / docx / md / txt / csv 等
              </p>
            </div>
            <button className="btn-primary" onClick={onUpload} disabled={!kbId}>
              <IconUpload size={14} />
              上传文档
            </button>
            <input ref={hiddenInput} type="file" hidden />
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
            {docs.length === 0 ? (
              <div className="empty-state">
                <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-card bg-canvas text-ink-400">
                  <IconFile size={20} />
                </div>
                <p className="text-[13px] text-ink-500">还没有文档，上传后即可检索问答</p>
              </div>
            ) : (
              <div className="overflow-hidden rounded-card border border-hairline">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>文档</th>
                      <th>类型</th>
                      <th className="col-num">版本</th>
                      <th className="col-num">块数</th>
                      <th>策略</th>
                      <th>状态</th>
                      <th className="col-actions">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {docs.map((d) => {
                      const busy = d.status === "processing" || d.status === "deleting";
                      return (
                        <tr key={d.id}>
                          <td className="max-w-[280px]">
                            <div className="flex items-center gap-2">
                              <IconFile size={14} className="shrink-0 text-ink-400" />
                              <span className="truncate text-ink-900" title={d.title}>
                                {d.title}
                              </span>
                            </div>
                          </td>
                          <td className="text-[12px] text-ink-500">{d.doc_type}</td>
                          <td className="col-num">v{d.current_version}</td>
                          <td className="col-num">{d.chunk_count ?? "-"}</td>
                          <td className="text-[12px] text-ink-500">
                            {d.version_policy === "coexist" ? "并存式" : "覆盖式"}
                          </td>
                          <td>
                            <span
                              className={`badge ${STATUS_TONE[d.status] ?? "badge-neutral"}`}
                            >
                              {busy && <IconSpinner size={10} />}
                              {STATUS_LABEL[d.status] ?? d.status}
                            </span>
                          </td>
                          <td className="col-actions">
                            <div className="flex items-center justify-end gap-1">
                              {d.versions
                                .filter((v) => v.status !== "active")
                                .slice(0, 1)
                                .map((v) => (
                                  <button
                                    key={v.version}
                                    onClick={() => onRollback(d.id, v.version)}
                                    className="rounded-control px-2 py-1 text-[11px] text-ink-500 transition hover:bg-black/[0.04] hover:text-ink-700"
                                    title={`回滚到 v${v.version}`}
                                  >
                                    回滚 v{v.version}
                                  </button>
                                ))}
                              <button
                                onClick={() => onDeleteDoc(d.id, d.title)}
                                disabled={busy}
                                className="rounded-control p-1.5 text-ink-400 transition hover:bg-red-50 hover:text-red-500 disabled:opacity-30"
                                title="删除文档"
                              >
                                <IconTrash size={14} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
};

export default KnowledgePage;
