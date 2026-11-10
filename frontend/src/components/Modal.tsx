import { useEffect, useRef, useState, type ReactNode } from "react";
import { IconSpinner } from "./Icons";

interface ShellProps {
  title: string;
  children: ReactNode;
  footer: ReactNode;
  onClose?: () => void;
  closable?: boolean;
  width?: number;
}

export const ModalShell: React.FC<ShellProps> = ({
  title,
  children,
  footer,
  onClose,
  closable = true,
  width = 440,
}) => {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && closable) onClose?.();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closable, onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/30 px-4 backdrop-blur-[2px] animate-fade-up"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && closable) onClose?.();
      }}
    >
      <div
        className="w-full overflow-hidden rounded-panel border border-hairline bg-white shadow-pop"
        style={{ maxWidth: width }}
      >
        <div className="flex items-start justify-between gap-4 border-b border-hairline px-5 py-3.5">
          <h2 className="text-[15px] font-semibold leading-6 text-ink-900">{title}</h2>
          {closable && (
            <button
              type="button"
              onClick={onClose}
              aria-label="关闭"
              className="-mr-1 -mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-control text-[13px] text-ink-400 transition hover:bg-black/[0.05] hover:text-ink-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/10"
            >
              ✕
            </button>
          )}
        </div>
        <div className="px-5 py-4 text-[13px] leading-relaxed text-ink-700">{children}</div>
        <div className="flex justify-end gap-2 border-t border-hairline bg-canvas-soft px-5 py-3">
          {footer}
        </div>
      </div>
    </div>
  );
};

interface PromptProps {
  title: string;
  message?: string;
  defaultValue?: string;
  placeholder?: string;
  confirmText?: string;
  validate?: (val: string) => string | null;
  onConfirm: (val: string) => Promise<void> | void;
  onClose: () => void;
}

export const PromptDialog: React.FC<PromptProps> = ({
  title,
  message,
  defaultValue = "",
  placeholder,
  confirmText = "确定",
  validate,
  onConfirm,
  onClose,
}) => {
  const [value, setValue] = useState(defaultValue);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    ref.current?.focus();
    ref.current?.select();
  }, []);

  const submit = async () => {
    const bad = validate?.(value) ?? null;
    if (bad) {
      setErr(bad);
      return;
    }
    setBusy(true);
    try {
      await onConfirm(value.trim());
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell
      title={title}
      onClose={onClose}
      footer={
        <>
          <button className="btn-ghost" onClick={onClose} disabled={busy}>
            取消
          </button>
          <button className="btn-primary" onClick={submit} disabled={busy}>
            {busy && <IconSpinner size={14} />}
            {confirmText}
          </button>
        </>
      }
    >
      {message && <p className="mb-3 leading-relaxed">{message}</p>}
      <input
        ref={ref}
        aria-label={title}
        className={`field ${err ? "field-invalid" : ""}`}
        value={value}
        placeholder={placeholder}
        onChange={(e) => {
          setValue(e.target.value);
          setErr(null);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") void submit();
        }}
      />
      {err && <p className="error-text">{err}</p>}
    </ModalShell>
  );
};

interface ConfirmProps {
  title: string;
  message: string;
  confirmText?: string;
  danger?: boolean;
  onConfirm: () => Promise<void> | void;
  onClose: () => void;
}

export const ConfirmDialog: React.FC<ConfirmProps> = ({
  title,
  message,
  confirmText = "确定",
  danger,
  onConfirm,
  onClose,
}) => {
  const [busy, setBusy] = useState(false);
  return (
    <ModalShell
      title={title}
      onClose={onClose}
      footer={
        <>
          <button className="btn-ghost" onClick={onClose} disabled={busy}>
            取消
          </button>
          <button
            className={danger ? "btn-danger" : "btn-primary"}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm();
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy}
          >
            {busy && <IconSpinner size={14} />}
            {confirmText}
          </button>
        </>
      }
    >
      <p className="leading-relaxed">{message}</p>
    </ModalShell>
  );
};

/** 右上角轻提示。 */
export const Toast: React.FC<{ text: string | null }> = ({ text }) => {
  if (!text) return null;
  return (
    <div className="pointer-events-none fixed left-1/2 top-6 z-[60] -translate-x-1/2 animate-fade-up">
      <div className="rounded-full bg-ink-900/90 px-4 py-2 text-xs text-white shadow-pop">{text}</div>
    </div>
  );
};
