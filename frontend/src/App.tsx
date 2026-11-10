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
  setToken,
  UnauthorizedError,
  uploadDoc,
} from "./api";
import { deriveTitle, loadSessions, newSession, saveSessions } from "./sessions";
import type { ChatMessage, DocumentItem, KnowledgeBase, PageKey, Session } from "./types";
import ChatPage from "./components/ChatPage";
import KnowledgePage from "./components/KnowledgePage";
import Sidebar from "./components/Sidebar";
import { ConfirmDialog, ModalShell, PromptDialog, Toast } from "./components/Modal";
import { IconUpload } from "./components/Icons";

/** 开发环境才输出错误日志，生产不把细节打到 console（L2）。 */
const logError = (...args: unknown[]) => {
  if (import.meta.env.DEV) console.error(...args);
};

// 名称校验（与后端规则保持一致）
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

type Dialog =
  | { kind: "none" }
  | { kind: "create-kb" }
  | { kind: "rename-kb"; id: string; name: string }
  | { kind: "delete-doc"; id: string; title: string }
  | { kind: "upload" }
  | { kind: "token" };

const App: React.FC = () => {
  // ---- 数据 ----
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [kbId, setKbId] = useState("");
  const [docs, setDocs] = useState<DocumentItem[]>([]);

  // ---- 会话 ----
  const [sessions, setSessions] = useState<Session[]>(() => loadSessions());
  const [activeId, setActiveId] = useState<string>(() => loadSessions()[0]?.id ?? "");
  const [page, setPage] = useState<PageKey>("chat");
  const [streaming, setStreaming] = useState(false);

  // ---- UI ----
  const [dialog, setDialog] = useState<Dialog>({ kind: "none" });
  const [tokenOpen, setTokenOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [uploadPolicy, setUploadPolicy] = useState<"replace" | "coexist">("replace");
  const tokenInputRef = useRef<HTMLInputElement>(null);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const toastTimer = useRef<number | undefined>(undefined);

  const showToast = useCallback((text: string) => {
    setToast(text);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 1800);
  }, []);

  const activeSession = sessions.find((s) => s.id === activeId);
  // 知识库页 / 文档操作必须落到某个具体库：未选（即「全部知识库」）时回落到第一个
  const kbTargetId = kbId || kbs[0]?.id || "";

  // ---- 会话持久化（防抖，避免流式期间高频写盘）----
  useEffect(() => {
    const t = window.setTimeout(() => saveSessions(sessions), 300);
    return () => window.clearTimeout(t);
  }, [sessions]);

  const patchSession = useCallback((id: string, patch: (s: Session) => Partial<Session>) => {
    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, ...patch(s), updatedAt: Date.now() } : s)),
    );
  }, []);

  // ---- 数据加载 ----
  const catchAuth = useCallback((e: unknown) => {
    if (e instanceof UnauthorizedError) setTokenOpen(true);
    else logError(e);
  }, []);

  const refreshKBs = useCallback(async () => {
    const list = await listKBs();
    setKbs(list);
    // 默认停在「全部知识库」；仅当原先选中的库已不存在时归零
    setKbId((prev) => (prev && list.some((k) => k.id === prev) ? prev : ""));
  }, []);

  const refreshDocs = useCallback(async () => {
    if (!kbTargetId) {
      setDocs([]);
      return;
    }
    setDocs(await listDocs(kbTargetId));
  }, [kbTargetId]);

  useEffect(() => {
    refreshKBs().catch(catchAuth);
  }, [refreshKBs, catchAuth]);

  useEffect(() => {
    refreshDocs().catch(catchAuth);
  }, [refreshDocs, catchAuth]);

  // 切换会话时同步该会话绑定的知识库（空字符串 = 全部知识库）
  useEffect(() => {
    if (!activeSession) return;
    setKbId(activeSession.kbId ?? "");
  }, [activeSession?.id, activeSession?.kbId]);

  // 轮询入库/删除状态（一次列表请求刷新全部）
  useEffect(() => {
    const pending = docs.some((d) => d.status === "processing" || d.status === "deleting");
    if (!pending) return;
    const hasDeleting = docs.some((d) => d.status === "deleting");
    const timer = window.setInterval(() => refreshDocs().catch(catchAuth), hasDeleting ? 1500 : 3000);
    return () => window.clearInterval(timer);
  }, [docs, refreshDocs, catchAuth]);

  const notifyError = (action: string, e: unknown) => {
    if (e instanceof UnauthorizedError) {
      setTokenOpen(true);
      return;
    }
    showToast(`${action}失败：${e instanceof Error ? e.message : String(e)}`);
  };

  // ---- 令牌 ----
  const submitToken = async (val: string) => {
    if (!val.trim()) return;
    setToken(val);
    try {
      await refreshKBs();
      setTokenOpen(false);
      showToast("令牌已保存");
    } catch (e) {
      if (e instanceof UnauthorizedError) showToast("令牌无效，请重新输入");
      else setTokenOpen(false);
    }
  };

  // ---- 知识库 ----
  const handleCreateKB = () => setDialog({ kind: "create-kb" });
  const handleRenameKB = (id: string, name: string) => setDialog({ kind: "rename-kb", id, name });

  const handleSelectKb = (id: string) => {
    setKbId(id);
    if (activeSession) patchSession(activeSession.id, () => ({ kbId: id }));
  };

  // ---- 文档 ----
  const openUpload = () => {
    if (!kbTargetId) {
      showToast("请先创建或选择知识库");
      return;
    }
    setUploadPolicy("replace");
    setDialog({ kind: "upload" });
  };

  const handleUploadFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setDialog({ kind: "none" });
    try {
      await uploadDoc(kbTargetId, file, uploadPolicy);
      await refreshDocs();
      showToast(`已提交入库：${file.name}`);
    } catch (err) {
      notifyError("上传文档", err);
    }
  };

  const handleDeleteDoc = (id: string, title: string) =>
    setDialog({ kind: "delete-doc", id, title });

  const handleRollback = async (id: string, version: number) => {
    try {
      await rollbackDoc(id, version);
      await refreshDocs();
      showToast(`已回滚到 v${version}`);
    } catch (e) {
      notifyError("版本回滚", e);
    }
  };

  // ---- 会话 ----
  const handleNewSession = () => {
    const empty = sessions.find((s) => s.messages.length === 0);
    if (empty) {
      setActiveId(empty.id);
      return;
    }
    const s = newSession(kbId);
    setSessions((prev) => [s, ...prev]);
    setActiveId(s.id);
  };

  const handleDeleteSession = (id: string) => {
    setSessions((prev) => prev.filter((s) => s.id !== id));
    if (id === activeId) setActiveId("");
  };

  // ---- 对话 ----
  const runChat = useCallback(
    async (sid: string, query: string) => {
      setStreaming(true);
      let logId = "";
      const updateLast = (patch: Partial<ChatMessage>) =>
        patchSession(sid, (s) => {
          const msgs = [...s.messages];
          msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], ...patch };
          return { messages: msgs };
        });

      // 用会话绑定的知识库（空字符串 = 全部知识库），避免切换后错乱
      const boundKb = sessions.find((s) => s.id === sid)?.kbId;
      const sessionKb = boundKb ?? kbId;
      let acc = "";
      try {
        await chatStream(sessionKb || null, query, sid, "auto", {
          onDelta: (t) => {
            acc += t;
            updateLast({ content: acc });
          },
          onMeta: (route, id) => {
            logId = id;
            updateLast({ route });
          },
          onCitations: (citations) => updateLast({ citations }),
          onDone: (route, latency) =>
            updateLast({ route: route || undefined, latency_ms: latency, logId: logId || undefined }),
          onError: (code, message) => updateLast({ error: `${code}: ${message}` }),
        });
      } catch (e) {
        if (e instanceof UnauthorizedError) setTokenOpen(true);
        updateLast({ error: e instanceof UnauthorizedError ? "访问令牌缺失或无效" : String(e) });
      } finally {
        setStreaming(false);
      }
    },
    [kbId, kbs.length, patchSession, sessions],
  );

  const handleSend = (query: string) => {
    if (streaming || kbs.length === 0) return;
    const sid = activeId || "";
    const target = sessions.find((s) => s.id === sid);

    if (!target) {
      const s = newSession(kbId);
      setSessions((prev) => [
        {
          ...s,
          title: deriveTitle(query),
          messages: [
            { role: "user", content: query },
            { role: "assistant", content: "" },
          ],
        },
        ...prev,
      ]);
      setActiveId(s.id);
      void runChat(s.id, query);
      return;
    }

    patchSession(sid, (s) => ({
      title: s.messages.length === 0 ? deriveTitle(query) : s.title,
      kbId,
      messages: [
        ...s.messages,
        { role: "user", content: query },
        { role: "assistant", content: "" },
      ],
    }));
    void runChat(sid, query);
  };

  const handleRegenerate = (idx: number) => {
    if (streaming || !activeSession) return;
    const msgs = activeSession.messages;
    let q = "";
    for (let i = idx - 1; i >= 0; i--) {
      if (msgs[i].role === "user") {
        q = msgs[i].content;
        break;
      }
    }
    if (!q) return;
    const sid = activeSession.id;
    patchSession(sid, (s) => ({ messages: s.messages.slice(0, idx - 1) }));
    patchSession(sid, (s) => ({
      messages: [...s.messages, { role: "user", content: q }, { role: "assistant", content: "" }],
    }));
    void runChat(sid, q);
  };

  const handleFeedback = async (idx: number, fb: number) => {
    const msg = activeSession?.messages[idx];
    if (!msg?.logId || !activeSession) return;
    try {
      await sendFeedback(msg.logId, fb);
      patchSession(activeSession.id, (s) => {
        const msgs = [...s.messages];
        msgs[idx] = { ...msgs[idx], feedback: fb };
        return { messages: msgs };
      });
    } catch (e) {
      notifyError("提交反馈", e);
    }
  };

  return (
    <div className="flex h-full">
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        page={page}
        kbLabel={kbId ? (kbs.find((k) => k.id === kbId)?.name ?? "") : kbs.length ? "全部" : ""}
        kbNames={kbs.map((k) => k.name)}
        onNew={handleNewSession}
        onSelect={setActiveId}
        onGoKnowledge={() => setPage("knowledge")}
        onGoChat={() => setPage("chat")}
        onTogglePin={(id) =>
          patchSession(id, (s) => ({ pinned: !s.pinned }))
        }
        onDelete={handleDeleteSession}
      />

      {page === "chat" ? (
        <ChatPage
          kbs={kbs}
          kbId={kbId}
          messages={activeSession?.messages ?? []}
          streaming={streaming}
          onKbChange={handleSelectKb}
          onSend={handleSend}
          onRegenerate={handleRegenerate}
          onFeedback={handleFeedback}
          onToast={showToast}
        />
      ) : (
        <KnowledgePage
          kbs={kbs}
          kbId={kbTargetId}
          docs={docs}
          onSelectKb={handleSelectKb}
          onCreateKb={handleCreateKB}
          onRenameKb={handleRenameKB}
          onUpload={openUpload}
          onDeleteDoc={handleDeleteDoc}
          onRollback={handleRollback}
          onBack={() => setPage("chat")}
        />
      )}

      {/* 新建知识库 */}
      {dialog.kind === "create-kb" && (
        <PromptDialog
          title="新建知识库"
          placeholder="请输入知识库名称（2-50 字符）"
          confirmText="创建"
          validate={validateName}
          onClose={() => setDialog({ kind: "none" })}
          onConfirm={async (name) => {
            try {
              const kb = await createKB(name);
              await refreshKBs();
              setKbId(kb.id);
              setDialog({ kind: "none" });
              showToast(`已创建：${name}`);
            } catch (e) {
              notifyError("新建知识库", e);
            }
          }}
        />
      )}

      {/* 重命名知识库 */}
      {dialog.kind === "rename-kb" && (
        <PromptDialog
          title="重命名知识库"
          defaultValue={dialog.name}
          confirmText="保存"
          validate={validateName}
          onClose={() => setDialog({ kind: "none" })}
          onConfirm={async (name) => {
            if (name === dialog.name) {
              setDialog({ kind: "none" });
              return;
            }
            try {
              await renameKB(dialog.id, name);
              await refreshKBs();
              setDialog({ kind: "none" });
              showToast("已重命名");
            } catch (e) {
              notifyError("重命名知识库", e);
            }
          }}
        />
      )}

      {/* 删除文档 */}
      {dialog.kind === "delete-doc" && (
        <ConfirmDialog
          title="确认删除"
          message={`确认删除「${dialog.title}」？将级联删除全部版本与向量，操作不可撤销。`}
          confirmText="删除"
          danger
          onClose={() => setDialog({ kind: "none" })}
          onConfirm={async () => {
            try {
              await deleteDoc(dialog.id);
              await refreshDocs();
              setDialog({ kind: "none" });
              showToast("已删除");
            } catch (e) {
              notifyError("删除文档", e);
            }
          }}
        />
      )}

      {/* 上传：先选版本策略 */}
      {dialog.kind === "upload" && (
        <ModalShell
          title="上传文档"
          onClose={() => setDialog({ kind: "none" })}
          footer={
            <>
              <button className="btn-ghost" onClick={() => setDialog({ kind: "none" })}>
                取消
              </button>
              <button className="btn-primary" onClick={() => uploadInputRef.current?.click()}>
                <IconUpload size={14} />
                选择文件…
              </button>
            </>
          }
        >
          <p className="mb-3 leading-relaxed">
            同名文件重复上传时，版本策略决定新旧版本的共存方式：
          </p>
          <div className="space-y-2">
            {(
              [
                ["replace", "覆盖式", "新版生效，旧版本标记归档并在保留窗口后清理（推荐）"],
                ["coexist", "并存式", "所有版本均可被检索到，适合法规 / 合同类时效文献"],
              ] as const
            ).map(([val, label, desc]) => (
              <label
                key={val}
                onClick={() => setUploadPolicy(val)}
                className={`flex cursor-pointer gap-3 rounded-card border p-3 transition ${
                  uploadPolicy === val
                    ? "border-brand-400 bg-brand-50/60"
                    : "border-hairline hover:border-brand-200"
                }`}
              >
                <span
                  className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                    uploadPolicy === val ? "border-brand-600" : "border-ink-400/50"
                  }`}
                >
                  {uploadPolicy === val && <span className="h-2 w-2 rounded-full bg-brand-600" />}
                </span>
                <span>
                  <span className="block text-[13px] font-medium text-ink-900">{label}</span>
                  <span className="mt-0.5 block text-[12px] leading-relaxed text-ink-500">
                    {desc}
                  </span>
                </span>
              </label>
            ))}
          </div>
          <input
            ref={uploadInputRef}
            type="file"
            hidden
            onChange={handleUploadFile}
            accept=".pdf,.docx,.md,.txt,.json,.csv,.html,.xlsx,.pptx,.eml"
          />
        </ModalShell>
      )}

      {/* 访问令牌 */}
      {tokenOpen && (
        <ModalShell
          title="输入访问令牌"
          closable={false}
          footer={
            <button
              className="btn-primary"
              onClick={() => submitToken(tokenInputRef.current?.value ?? "")}
            >
              确定
            </button>
          }
        >
          <p className="mb-3 leading-relaxed">
            系统已开启访问鉴权，请输入 API Token 后继续使用。令牌会保存在本浏览器。
          </p>
          <input
            ref={tokenInputRef}
            className="field"
            type="password"
            autoFocus
            placeholder="API Token"
            onKeyDown={(e) => {
              if (e.key === "Enter") submitToken((e.target as HTMLInputElement).value);
            }}
          />
        </ModalShell>
      )}

      <Toast text={toast} />
    </div>
  );
};

export default App;
