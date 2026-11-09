import { AlertTriangle, Info, Lightbulb, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

const TONES = {
  info: { icon: Info, cls: "border-blueprint/25 bg-blueprint-soft/70 text-ink", iconCls: "text-blueprint" },
  tip: { icon: Lightbulb, cls: "border-[#e9cf8f] bg-[#fdf6e4] text-ink", iconCls: "text-warn" },
  warn: { icon: AlertTriangle, cls: "border-bad/30 bg-[#fbefed] text-ink", iconCls: "text-bad" },
} as const;

const KEY = (id: string) => `atest.infobox.${id}`;
export const RESET_EVENT = "atest:infobox-reset";

/** Volta a exibir todas as caixas de dica que a pessoa fechou. */
export function resetInfoBoxes() {
  try {
    Object.keys(localStorage).filter((k) => k.startsWith("atest.infobox.")).forEach((k) => localStorage.removeItem(k));
  } catch { /* armazenamento indisponível */ }
  window.dispatchEvent(new Event(RESET_EVENT));
}

function isHidden(id?: string) {
  if (!id) return false;
  try { return localStorage.getItem(KEY(id)) === "1"; } catch { return false; }
}

interface Props {
  /** com id, a caixa pode ser fechada e a escolha fica lembrada neste navegador */
  id?: string;
  tone?: keyof typeof TONES;
  title?: ReactNode;
  children: ReactNode;
  className?: string;
}

/** Caixa de contexto: explica o que a pessoa está vendo e o que fazer a seguir. */
export function InfoBox({ id, tone = "info", title, children, className = "" }: Props) {
  const [hidden, setHidden] = useState(() => isHidden(id));
  useEffect(() => {
    const reset = () => setHidden(false);
    window.addEventListener(RESET_EVENT, reset);
    return () => window.removeEventListener(RESET_EVENT, reset);
  }, []);
  if (hidden) return null;
  const t = TONES[tone];
  const Icon = t.icon;
  const close = () => {
    setHidden(true);
    try { if (id) localStorage.setItem(KEY(id), "1"); } catch { /* armazenamento indisponível */ }
  };
  return (
    <div role="note" className={`flex gap-3 rounded-xl border px-4 py-3 text-sm leading-relaxed ${t.cls} ${className}`}>
      <Icon size={18} className={`mt-0.5 shrink-0 ${t.iconCls}`} aria-hidden />
      <div className="min-w-0 flex-1">
        {title && <div className="font-semibold">{title}</div>}
        <div className={title ? "text-ink/80" : ""}>{children}</div>
      </div>
      {id && (
        <button type="button" onClick={close} aria-label="Fechar dica" title="Fechar dica"
          className="-mr-1 -mt-0.5 h-fit rounded-md p-1 text-muted hover:bg-ink/5 hover:text-ink">
          <X size={15} />
        </button>
      )}
    </div>
  );
}
