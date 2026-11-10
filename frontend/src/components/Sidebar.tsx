import type { PageKey, Session } from "../types";
import { IconBook, IconChat, IconPin, IconPlus, IconTrash } from "./Icons";

interface Props {
  sessions: Session[];
  activeId: string;
  page: PageKey;
  kbLabel: string;
  kbNames: string[];
  onNew: () => void;
  onSelect: (id: string) => void;
  onGoKnowledge: () => void;
  onGoChat: () => void;
  onTogglePin: (id: string) => void;
  onDelete: (id: string) => void;
}

const SessionRow: React.FC<{
  s: Session;
  active: boolean;
  onClick: () => void;
  onTogglePin: () => void;
  onDelete: () => void;
}> = ({ s, active, onClick, onTogglePin, onDelete }) => (
  <div
    onClick={onClick}
    className={`group relative flex cursor-pointer items-center gap-2 rounded-control px-2.5 py-[7px] text-[13px] transition ${
      active ? "bg-white text-ink-900 shadow-card" : "text-ink-700 hover:bg-black/[0.04]"
    }`}
  >
    <IconChat size={14} className={active ? "text-brand-600" : "text-ink-400"} />
    <span className="flex-1 truncate">{s.title}</span>
    <div className="absolute right-1.5 hidden items-center gap-0.5 rounded-control bg-inherit pl-2 group-hover:flex">
      <button
        title={s.pinned ? "取消置顶" : "置顶"}
        onClick={(e) => {
          e.stopPropagation();
          onTogglePin();
        }}
        className={`rounded p-1 transition hover:bg-black/10 ${
          s.pinned ? "text-brand-600" : "text-ink-400"
        }`}
      >
        <IconPin size={13} />
      </button>
      <button
        title="删除会话"
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        className="rounded-control p-1 text-ink-400 transition hover:bg-red-50 hover:text-red-500"
      >
        <IconTrash size={13} />
      </button>
    </div>
  </div>
);

const Sidebar: React.FC<Props> = ({
  sessions,
  activeId,
  page,
  kbLabel,
  kbNames,
  onNew,
  onSelect,
  onGoKnowledge,
  onGoChat,
  onTogglePin,
  onDelete,
}) => {
  // 与任一知识库同名的会话在列表中不重复展示（数据仍保留在本地存储）
  const visible = sessions.filter((s) => !kbNames.includes(s.title));
  const pinned = visible.filter((s) => s.pinned).sort((a, b) => b.updatedAt - a.updatedAt);
  const recent = visible.filter((s) => !s.pinned).sort((a, b) => b.updatedAt - a.updatedAt);

  return (
    <aside className="flex h-full w-[264px] shrink-0 flex-col border-r border-hairline bg-canvas">
      {/* 品牌 */}
      <div className="flex items-center gap-2.5 px-4 pb-3 pt-4">
        <div className="flex h-7 w-7 items-center justify-center rounded-control bg-brand-600 text-[13px] font-bold text-white">
          G
        </div>
        <span className="text-[15px] font-semibold tracking-tight text-ink-900">知识库问答</span>
      </div>

      {/* 主操作 */}
      <div className="px-3">
        <button
          onClick={() => {
            onGoChat();
            onNew();
          }}
          className="flex h-9 w-full items-center gap-2 rounded-control border border-hairline bg-white px-3 text-[13px] font-medium text-ink-900 shadow-card transition hover:border-brand-300 hover:text-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-100"
        >
          <IconPlus size={14} />
          新对话
        </button>

        <button
          onClick={onGoKnowledge}
          className={`mt-2 flex h-9 w-full items-center gap-2 rounded-control px-3 text-[13px] transition ${
            page === "knowledge"
              ? "bg-white font-medium text-ink-900 shadow-card"
              : "text-ink-700 hover:bg-black/[0.04]"
          }`}
        >
          <IconBook size={15} className={page === "knowledge" ? "text-brand-600" : "text-ink-400"} />
          <span className="flex-1 text-left">知识库</span>
          <span className="max-w-[92px] truncate rounded-md bg-canvas px-1.5 py-0.5 text-[11px] text-ink-500 ring-1 ring-inset ring-hairline">
            {kbLabel || "未选择"}
          </span>
        </button>
      </div>

      {/* 会话列表 */}
      <div className="mt-4 flex-1 overflow-y-auto px-3 pb-3">
        {pinned.length > 0 && (
          <div className="mb-3">
            <div className="group-label mb-1">
              置顶
            </div>
            <div className="space-y-0.5">
              {pinned.map((s) => (
                <SessionRow
                  key={s.id}
                  s={s}
                  active={page === "chat" && s.id === activeId}
                  onClick={() => {
                    onGoChat();
                    onSelect(s.id);
                  }}
                  onTogglePin={() => onTogglePin(s.id)}
                  onDelete={() => onDelete(s.id)}
                />
              ))}
            </div>
          </div>
        )}

        <div>
          <div className="group-label mb-1">
            最近
          </div>
          {recent.length === 0 ? (
            <div className="px-1.5 py-2 text-[12px] text-ink-500">
              还没有对话，点击「新对话」开始
            </div>
          ) : (
            <div className="space-y-0.5">
              {recent.map((s) => (
                <SessionRow
                  key={s.id}
                  s={s}
                  active={page === "chat" && s.id === activeId}
                  onClick={() => {
                    onGoChat();
                    onSelect(s.id);
                  }}
                  onTogglePin={() => onTogglePin(s.id)}
                  onDelete={() => onDelete(s.id)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 用户 */}
      <div className="flex items-center gap-2.5 border-t border-hairline px-4 py-3">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-100 text-[11px] font-semibold text-brand-700">
          L
        </div>
        <span className="text-[13px] text-ink-700">life</span>
      </div>
    </aside>
  );
};

export default Sidebar;
