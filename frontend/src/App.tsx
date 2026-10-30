import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  chatStream,
  createKB,
  deleteDoc,
  listDocs,
  listKBs,
  renameKB,
  rollbackDoc,
  sendFeedback,
  uploadDoc,
} from "./api";
import type { ChatMessage, DocumentItem, KnowledgeBase } from "./types";

/** 开发环境才输出错误日志，生产不把细节打到 console（L2）。 */
const logError = (...args: unknown[]) => {
  if (import.meta.env.DEV) {
    console.error(...args);
  }
};

const App: React.FC = () => {
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [kbId, setKbId] = useState<string>("");
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [sessionId] = useState(() => crypto.randomUUID());
  const bottomRef = useRef<HTMLDivElement>(null);
  const uploadInputRef = useRef<HTMLInputElement>(null);

  // Modal 状态（替换 prompt/confirm）
  const [modal, setModal] = useState<{
    open: boolean;
    title: string;
    type: "input" | "confirm";
    message?: string;
    inputValue?: string;
    inputPlaceholder?: string;
    confirmText?: string;
    danger?: boolean;
    onConfirm: (val?: string) => void;
  }>({ open: false, title: "", type: "confirm", onConfirm: () => {} });

  const closeModal = () => setModal((m) => ({ ...m, open: false }));

  // 上传 Modal 状态
  const [uploadModal, setUploadModal] = useState<{
    open: boolean;
    policy: "replace" | "coexist";
  }>({ open: false, policy: "replace" });

  const refreshKBs = useCallback(async () => {
    const list = await listKBs();
    setKbs(list);
    if (list.length > 0) setKbId((prev) => prev || list[0].id);
  }, []);

  const refreshDocs = useCallback(async () => {
    if (!kbId) return;
    setDocs(await listDocs(kbId));
  }, [kbId]);

  useEffect(() => {
    refreshKBs().catch(logError);
  }, [refreshKBs]);

  useEffect(() => {
    refreshDocs().catch(logError);
  }, [refreshDocs]);

  // 轮询入库/删除状态（有 processing/deleting 文档时）：一次列表请求刷新全部，避免按文档逐个请求（M3）
  useEffect(() => {
    const hasPending = docs.some((d) => d.status === "processing" || d.status === "deleting");
    if (!hasPending) return;
    // 删除任务通常较快，用更短的间隔（1.5s）；入库较慢用 3s
    const hasDeleting = docs.some((d) => d.status === "deleting");
    const interval = hasDeleting ? 1500 : 3000;
    const timer = setInterval(() => {
      refreshDocs().catch(logError);
    }, interval);
    return () => clearInterval(timer);
  }, [docs, refreshDocs]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const notifyError = (action: string, e: unknown) => {
    alert(`${action}失败: ${e instanceof Error ? e.message : String(e)}`);
  };

  // 前端名称校验（和后端规则保持一致）
  const validateName = (name: string): string | null => {
    const trimmed = name.trim();
    if (!trimmed) return "名称不能为空";
    if (trimmed.length < 2) return "名称至少 2 个字符";
    if (trimmed.length > 50) return "名称最多 50 个字符";
    const bad = "?*\\/:;'\"<>|#$%&@+=~`!^[]{}()";
    for (const ch of trimmed) {
      if (bad.includes(ch)) return `名称不能包含非法字符: ${ch}`;
    }
    if (!/^[\u4e00-\u9fa5A-Za-z0-9_\-]+$/.test(trimmed)) {
      return "名称只能包含中文、英文、数字、下划线(_)、短横线(-)";
    }
    return null;
  };

  const handleCreateKB = () => {
    setModal({
      open: true,
      title: "新建知识库",
      type: "input",
      inputPlaceholder: "请输入知识库名称（2-50 字符）",
      confirmText: "创建",
      onConfirm: async (val) => {
        const name = val?.trim() ?? "";
        const err = validateName(name);
        if (err) { alert(err); return; }
        closeModal();
        try {
          const kb = await createKB(name);
          await refreshKBs();
          setKbId(kb.id);
        } catch (e) {
          notifyError("新建知识库", e);
        }
      },
    });
  };

  const handleRenameKB = (id: string, currentName: string) => {
    setModal({
      open: true,
      title: "重命名知识库",
      type: "input",
      inputValue: currentName,
      confirmText: "保存",
      onConfirm: async (val) => {
        const name = val?.trim() ?? "";
        const err = validateName(name);
        if (err) { alert(err); return; }
        if (name === currentName) { closeModal(); return; }
        closeModal();
        try {
          await renameKB(id, name);
          await refreshKBs();
        } catch (e) {
          notifyError("重命名知识库", e);
        }
      },
    });
  };

  // 打开上传 Modal（选版本策略）
  const openUpload = () => {
    if (!kbId) { alert("请先选择知识库"); return; }
    setUploadModal({ open: true, policy: "replace" });
  };

  const closeUpload = () => setUploadModal((u) => ({ ...u, open: false }));

  // Modal 里选完策略后 → 触发 Modal 内的 file input（Modal 关闭时该 input 已卸载，H4）
  const handleUploadConfirm = () => uploadInputRef.current?.click();

  // 选完文件 → 真正上传
  const handleUploadFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";  // 先重置，允许再次选择同一文件
    if (!file) return;
    const policy = uploadModal.policy;
    closeUpload();
    try {
      await uploadDoc(kbId, file, policy);
      await refreshDocs();
    } catch (err) {
      notifyError("上传文档", err);
    }
  };

  const handleDeleteDoc = (id: string) => {
    setModal({
      open: true,
      title: "确认删除",
      type: "confirm",
      message: "确认删除该文档（级联删除全部版本和向量）？此操作不可撤销。",
      confirmText: "删除",
      danger: true,
      onConfirm: async () => {
        closeModal();
        try {
          await deleteDoc(id);
          await refreshDocs();
        } catch (e) {
          notifyError("删除文档", e);
        }
      },
    });
  };

  const handleRollback = async (id: string, version: number) => {
    try {
      await rollbackDoc(id, version);
      await refreshDocs();
    } catch (e) {
      notifyError("版本回滚", e);
    }
  };

  const handleSend = async () => {
    const query = input.trim();
    if (!query || !kbId || streaming) return;
    setInput("");
    setStreaming(true);
    setMessages((m) => [...m, { role: "user", content: query }, { role: "assistant", content: "" }]);

    let logId = "";
    const updateLast = (patch: Partial<ChatMessage>) => {
      setMessages((m) => {
        const next = [...m];
        next[next.length - 1] = { ...next[next.length - 1], ...patch };
        return next;
      });
    };

    let acc = "";
    try {
      await chatStream(kbId, query, sessionId, "auto", {
        onDelta: (t) => {
          acc += t;
          updateLast({ content: acc });
        },
        onMeta: (route, id) => {
          logId = id;
          updateLast({ route });
        },
        onCitations: (citations) => updateLast({ citations }),
        onDone: (route, latency) => updateLast({ route: route || undefined, latency_ms: latency, logId: logId || undefined }),
        onError: (code, message) => updateLast({ error: `${code}: ${message}` }),
      });
    } catch (e) {
      updateLast({ error: String(e) });
    } finally {
      setStreaming(false);
    }
  };

  const handleFeedback = async (idx: number, fb: number) => {
    const msg = messages[idx];
    if (!msg?.logId) return;
    await sendFeedback(msg.logId, fb);
    setMessages((m) => {
      const next = [...m];
      next[idx] = { ...next[idx], feedback: fb };
      return next;
    });
  };

  const statusLabel: Record<string, string> = {
    processing: "入库中", active: "正常", deleting: "删除中", failed: "失败",
  };
  const versionLabel: Record<string, string> = {
    processing: "处理中", active: "生效中", archived: "已归档", superseded: "已更替",
  };

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="panel">
          <div className="panel-head">
            <h2>知识库</h2>
            <button onClick={handleCreateKB}>+ 新建</button>
          </div>
          <div className="kb-list">
            {kbs.map((k) => (
              <button
                key={k.id}
                className={`kb-item ${k.id === kbId ? "active" : ""}`}
                onClick={() => { setKbId(k.id); setMessages([]); }}
                onDoubleClick={(e) => { e.stopPropagation(); handleRenameKB(k.id, k.name); }}
                title="点击切换 · 双击重命名"
              >
                <span className="kb-name">{k.name}</span>
                <span className="kb-edit" onClick={(e) => { e.stopPropagation(); handleRenameKB(k.id, k.name); }}
                      title="重命名">✎</span>
              </button>
            ))}
            {kbs.length === 0 && <div className="empty">暂无知识库</div>}
          </div>
        </div>
        <div className="panel grow">
          <div className="panel-head">
            <h2>文档</h2>
            <label className="upload-btn" onClick={openUpload}>
              + 上传
            </label>
          </div>
          <div className="doc-list">
            {docs.map((d) => (
              <div key={d.id} className="doc-item">
                <div className="doc-title" title={d.title}>
                  {d.title}
                  <span className={`tag tag-${d.status}`}>{statusLabel[d.status] ?? d.status}</span>
                </div>
                <div className="doc-meta">
                  {d.doc_type} · v{d.current_version} · {d.chunk_count ?? "-"} 块 · {d.version_policy === "coexist" ? "并存式" : "覆盖式"}
                </div>
                <div className="doc-actions">
                  {d.versions.filter((v) => v.status !== "active").map((v) => (
                    <button key={v.version} className="mini"
                      onClick={() => handleRollback(d.id, v.version)}
                      title={`${versionLabel[v.status] ?? v.status}, 点击回滚`}>
                      回滚到 v{v.version}
                    </button>
                  ))}
                  <button className="mini danger" onClick={() => handleDeleteDoc(d.id)}>删除</button>
                </div>
              </div>
            ))}
            {docs.length === 0 && <div className="empty">暂无文档, 点击上传</div>}
          </div>
        </div>
      </aside>

      <main className="chat">
        <header className="chat-head">
          <h1>PersonalRag 知识问答</h1>
          <span className="hint">答案基于知识库检索结果生成, 引用 [n] 可溯源</span>
        </header>
        <div className="messages">
          {messages.length === 0 && (
            <div className="welcome">
              <h2>开始提问</h2>
              <p>左侧选择知识库并上传文档, 然后在此提问。支持闲聊直答 / 精确条文 / 混合检索 / 多跳推理。</p>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              <div className="bubble">
                {m.route && m.role === "assistant" && (
                  <div className="msg-route">通道: {m.route}{m.latency_ms ? ` · ${m.latency_ms}ms` : ""}</div>
                )}
                <div className="msg-content">{m.content || (streaming ? "…" : "")}</div>
                {m.citations && m.citations.length > 0 && (
                  <div className="citations">
                    {m.citations.map((c) => (
                      <span key={c.n} className="citation" title={`${c.doc_title}${c.page ? ` 第${c.page}页` : ""}`}>
                        [{c.n}] {c.doc_title}{c.page ? ` p${c.page}` : ""}
                      </span>
                    ))}
                  </div>
                )}
                {m.error && <div className="msg-error">{m.error}</div>}
                {m.logId && m.role === "assistant" && (
                  <div className="feedback">
                    <button className={m.feedback === 1 ? "picked" : ""}
                      onClick={() => handleFeedback(i, 1)}>👍</button>
                    <button className={m.feedback === -1 ? "picked" : ""}
                      onClick={() => handleFeedback(i, -1)}>👎</button>
                  </div>
                )}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
        <footer className="composer">
          <textarea
            value={input}
            placeholder={kbId ? "输入问题, Enter 发送" : "请先创建/选择知识库"}
            disabled={!kbId || streaming}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
            }}
          />
          <button onClick={handleSend} disabled={!kbId || streaming || !input.trim()}>发送</button>
        </footer>
      </main>

      {/* Modal（替换原生 prompt/confirm） */}
      {modal.open && (
        <div className="modal-mask" onClick={closeModal}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">{modal.title}</div>
            {modal.message && <div className="modal-message">{modal.message}</div>}
            {modal.type === "input" && (
              <input
                className="modal-input"
                autoFocus
                defaultValue={modal.inputValue ?? ""}
                placeholder={modal.inputPlaceholder}
                onKeyDown={(e) => {
                  if (e.key === "Enter") modal.onConfirm((e.target as HTMLInputElement).value);
                  if (e.key === "Escape") closeModal();
                }}
              />
            )}
            <div className="modal-actions">
              <button onClick={closeModal}>取消</button>
              {modal.type === "input" ? (
                <button
                  className="primary"
                  onClick={() => {
                    const input = document.querySelector(".modal-input") as HTMLInputElement;
                    modal.onConfirm(input?.value);
                  }}
                >
                  {modal.confirmText ?? "确定"}
                </button>
              ) : (
                <button className={modal.danger ? "danger" : "primary"} onClick={() => modal.onConfirm()}>
                  {modal.confirmText ?? "确定"}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 上传 Modal（选版本策略 → 选文件） */}
      {uploadModal.open && (
        <div className="modal-mask" onClick={closeUpload}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">上传文档</div>
            <div className="modal-message">选择同名文件重复上传时, 版本策略决定新旧版本的共存方式:</div>
            <div className="policy-radio">
              <label className={`policy-opt ${uploadModal.policy === "replace" ? "checked" : ""}`}
                     onClick={() => setUploadModal((u) => ({ ...u, policy: "replace" }))}>
                <input type="radio" checked={uploadModal.policy === "replace"} readOnly />
                <div className="policy-main">
                  <strong>覆盖式</strong>
                  <span>新版生效, 旧版本标记归档, 后续清理 (推荐)</span>
                </div>
              </label>
              <label className={`policy-opt ${uploadModal.policy === "coexist" ? "checked" : ""}`}
                     onClick={() => setUploadModal((u) => ({ ...u, policy: "coexist" }))}>
                <input type="radio" checked={uploadModal.policy === "coexist"} readOnly />
                <div className="policy-main">
                  <strong>并存式</strong>
                  <span>所有版本均可被检索到, 适合法规/合同类时效文献</span>
                </div>
              </label>
            </div>
            <div className="modal-actions">
              <button onClick={closeUpload}>取消</button>
              <button className="primary" onClick={handleUploadConfirm}>选择文件…</button>
            </div>
            {/* 文件选择器随 Modal 一起挂载/卸载，取消后不会再弹出系统文件框 */}
            <input
              ref={uploadInputRef}
              type="file"
              hidden
              onChange={handleUploadFile}
              accept=".pdf,.docx,.md,.txt,.json,.csv,.html"
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default App;
