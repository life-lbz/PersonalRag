import { useEffect, useRef, useState } from "react";
import type { ChatMessage, KnowledgeBase } from "../types";
import {
  IconChevronDown,
  IconCopy,
  IconRefresh,
  IconSend,
  IconSpark,
  IconSpinner,
  IconThumbDown,
  IconThumbUp,
} from "./Icons";
import CitationCard from "./CitationCard";

interface Props {
  kbs: KnowledgeBase[];
  kbId: string;
  messages: ChatMessage[];
  streaming: boolean;
  onKbChange: (id: string) => void;
  onSend: (query: string) => void;
  onRegenerate: (idx: number) => void;
  onFeedback: (idx: number, fb: number) => void;
  onToast: (text: string) => void;
}

const EXAMPLES = [
  "报销流程怎么走？",
  "出差住宿标准是多少？",
  "年假与调休规则是怎样的？",
];

const ChatPage: React.FC<Props> = ({
  kbs,
  kbId,
  messages,
  streaming,
  onKbChange,
  onSend,
  onRegenerate,
  onFeedback,
  onToast,
}) => {
  const [input, setInput] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const pickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  useEffect(() => {
    if (!pickerOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!pickerRef.current?.contains(e.target as Node)) setPickerOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [pickerOpen]);

  const submit = () => {
    const q = input.trim();
    if (!q || kbs.length === 0 || streaming) return;
    onSend(q);
    setInput("");
    if (areaRef.current) areaRef.current.style.height = "auto";
  };

  const hasKb = kbs.length > 0;
  const currentKb = kbs.find((k) => k.id === kbId);

  return (
    <main className="flex h-full min-w-0 flex-1 flex-col bg-white">
      {/* 顶栏 */}
      <header className="page-header justify-between">
        <h1 className="page-title">综合问答</h1>
        <div className="relative" ref={pickerRef}>
          <button
            onClick={() => setPickerOpen((v) => !v)}
            className="flex h-9 items-center gap-1.5 rounded-control px-2.5 text-[13px] text-ink-700 transition hover:bg-black/[0.04]"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-brand-500" />
            {currentKb?.name ?? "全部知识库"}
            <IconChevronDown size={13} className="text-ink-400" />
          </button>
          {pickerOpen && (
            <div className="absolute right-0 top-full z-30 mt-1 w-56 animate-fade-up overflow-hidden rounded-card border border-hairline bg-white py-1 shadow-pop">
              {kbs.length === 0 && (
                <div className="px-3 py-2 text-[12px] text-ink-500">暂无知识库</div>
              )}
              <button
                onClick={() => {
                  onKbChange("");
                  setPickerOpen(false);
                }}
                className={`flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] transition hover:bg-brand-50 ${
                  !kbId ? "text-brand-700" : "text-ink-700"
                }`}
              >
                <span className="flex-1 truncate">全部知识库</span>
                {!kbId && <span className="text-[11px]">当前</span>}
              </button>
              {kbs.length > 0 && <div className="my-1 h-px bg-hairline" />}
              {kbs.map((k) => (
                <button
                  key={k.id}
                  onClick={() => {
                    onKbChange(k.id);
                    setPickerOpen(false);
                  }}
                  className={`flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] transition hover:bg-brand-50 ${
                    k.id === kbId ? "text-brand-700" : "text-ink-700"
                  }`}
                >
                  <span className="flex-1 truncate">{k.name}</span>
                  {k.id === kbId && <span className="text-[11px]">当前</span>}
                </button>
              ))}
            </div>
          )}
        </div>
      </header>

      {/* 消息区 */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[760px] px-6 py-6">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center pt-20 text-center">
              <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-card bg-brand-50 text-brand-600">
                <IconSpark size={22} />
              </div>
              <h2 className="text-[17px] font-semibold text-ink-900">
                向 {currentKb?.name ?? "全部知识库"} 提问
              </h2>
              <p className="mt-1.5 max-w-md text-[13px] leading-relaxed text-ink-500">
                答案基于知识库检索结果生成，引用来源可溯源。支持闲聊直答、精确条文、混合检索与多跳推理。
              </p>
              <div className="mt-6 flex flex-wrap justify-center gap-2">
                {EXAMPLES.map((q) => (
                  <button
                    key={q}
                    onClick={() => onSend(q)}
                    disabled={kbs.length === 0}
                    className="rounded-full border border-hairline bg-white px-3.5 py-1.5 text-[12px] text-ink-700 transition hover:border-brand-300 hover:text-brand-700 disabled:opacity-40"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-7">
              {messages.map((m, i) =>
                m.role === "user" ? (
                  <div key={i} className="flex justify-end">
                    <div className="max-w-[80%] rounded-card bg-bubble px-4 py-2.5 text-[14px] leading-relaxed text-ink-900">
                      {m.content}
                    </div>
                  </div>
                ) : (
                  <div key={i} className="animate-fade-up">
                    <div className="mb-1.5 text-[12px] font-medium text-ink-500">助手</div>
                    {m.route && (
                      <div className="mb-1.5 text-[11px] text-ink-500">
                        通道 {m.route}
                        {m.latency_ms ? ` · ${m.latency_ms}ms` : ""}
                      </div>
                    )}
                    <div className="whitespace-pre-wrap text-[14px] leading-[1.85] text-ink-900">
                      {m.content}
                      {streaming && i === messages.length - 1 && (
                        <span className="ml-0.5 inline-block h-[15px] w-[2px] translate-y-[2px] animate-blink bg-brand-600 align-middle" />
                      )}
                    </div>

                    {m.citations && m.citations.length > 0 && (
                      <div className="mt-3.5 space-y-2">
                        {m.citations.map((c) => (
                          <CitationCard key={c.chunk_id} c={c} />
                        ))}
                      </div>
                    )}

                    {m.error && (
                      <div className="mt-2 rounded-control bg-red-50 px-3 py-2 text-[12px] text-red-600">
                        {m.error}
                      </div>
                    )}

                    {!streaming && m.content && (
                      <div className="mt-3 flex items-center gap-1 text-[12px] text-ink-500">
                        <button
                          className="flex items-center gap-1 rounded-control px-2 py-1 transition hover:bg-black/[0.04] hover:text-ink-700"
                          onClick={() => onRegenerate(i)}
                        >
                          <IconRefresh size={13} />
                          重新生成
                        </button>
                        <button
                          className="flex items-center gap-1 rounded-control px-2 py-1 transition hover:bg-black/[0.04] hover:text-ink-700"
                          onClick={() => {
                            navigator.clipboard
                              .writeText(m.content)
                              .then(() => onToast("已复制"))
                              .catch(() => onToast("复制失败"));
                          }}
                        >
                          <IconCopy size={13} />
                          复制
                        </button>
                        {m.logId && (
                          <>
                            <span className="mx-1 h-3 w-px bg-hairline" />
                            <span>有帮助</span>
                            <button
                              onClick={() => onFeedback(i, 1)}
                              className={`rounded-control p-1 transition hover:bg-black/[0.04] ${
                                m.feedback === 1 ? "text-brand-600" : ""
                              }`}
                            >
                              <IconThumbUp size={13} />
                            </button>
                            <button
                              onClick={() => onFeedback(i, -1)}
                              className={`rounded-control p-1 transition hover:bg-black/[0.04] ${
                                m.feedback === -1 ? "text-red-500" : ""
                              }`}
                            >
                              <IconThumbDown size={13} />
                            </button>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                ),
              )}
              {streaming && messages[messages.length - 1]?.role === "assistant" &&
                !messages[messages.length - 1].content && (
                  <div className="flex items-center gap-2 text-[13px] text-ink-400">
                    <IconSpinner size={14} />
                    正在检索并生成…
                  </div>
                )}
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* 输入区 */}
      <div className="shrink-0 px-6 pb-4">
        <div className="mx-auto w-full max-w-[760px]">
          <div className="rounded-card border border-hairline bg-white p-2 shadow-card transition focus-within:border-brand-300 focus-within:ring-2 focus-within:ring-brand-50">
            <textarea
              ref={areaRef}
              rows={1}
              value={input}
              disabled={!hasKb || streaming}
              placeholder={hasKb ? "输入问题，Enter 发送…" : "请先在「知识库」中创建知识库"}
              onChange={(e) => {
                setInput(e.target.value);
                const el = e.target;
                el.style.height = "auto";
                el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  submit();
                }
              }}
              className="max-h-[160px] w-full resize-none bg-transparent px-2 py-1.5 text-[14px] leading-relaxed text-ink-900 placeholder:text-ink-400 outline-none disabled:opacity-60"
            />
            <div className="flex items-center justify-between px-1 pb-0.5">
              <span className="text-[11px] text-ink-500">
                Shift + Enter 换行
              </span>
              <button
                onClick={submit}
                disabled={!hasKb || streaming || !input.trim()}
                className="flex h-8 w-8 items-center justify-center rounded-control bg-brand-600 text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-brand-200"
                title="发送"
              >
                {streaming ? <IconSpinner size={15} /> : <IconSend size={15} />}
              </button>
            </div>
          </div>
          <p className="mt-2 text-center text-[11px] text-ink-500">
            答案基于知识库检索结果生成，可用编号可溯源
          </p>
        </div>
      </div>
    </main>
  );
};

export default ChatPage;
