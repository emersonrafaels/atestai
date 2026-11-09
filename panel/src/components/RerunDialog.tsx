import { History, RefreshCw, X } from "lucide-react";
import { useEffect } from "react";
import { createPortal } from "react-dom";
import type { TicketSummary } from "../api";
import { REC } from "../format";

interface Props {
  /** chamados marcados que já têm parecer salvo */
  saved: TicketSummary[];
  /** total de chamados marcados para analisar */
  total: number;
  useSaved: () => void;
  rerun: () => void;
  onClose: () => void;
}

const when = (s: string) => new Date(s).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });

/** Antes de chamar a API: alguns chamados já têm parecer salvo. Reaproveitar ou executar o agente de novo? */
export function RerunDialog({ saved, total, useSaved, rerun, onClose }: Props) {
  const rest = total - saved.length;

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  return createPortal(
    <div className="fixed inset-0 z-[55] flex items-start justify-center overflow-y-auto bg-ink/60 p-4 sm:p-6 sm:pt-24" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="rerun-title" aria-describedby="rerun-desc" tabIndex={-1}
        className="surgir w-full max-w-lg rounded-2xl bg-sheet shadow-2xl outline-none" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div>
            <h2 id="rerun-title" className="largo text-xl font-bold">
              {saved.length === 1 ? "Este chamado já tem parecer salvo" : `${saved.length} chamados já têm parecer salvo`}
            </h2>
            <p id="rerun-desc" className="mt-0.5 text-sm text-muted">
              Usar o resultado anterior evita uma nova chamada à API, sem custo.
              {rest > 0 && <> Os outros {rest} chamado{rest === 1 ? "" : "s"} marcado{rest === 1 ? "" : "s"} são analisados de qualquer forma.</>}
            </p>
          </div>
          <button aria-label="Cancelar" onClick={onClose} className="rounded-full p-1.5 hover:bg-paper"><X size={18} /></button>
        </header>

        <ul className="max-h-64 divide-y divide-line/70 overflow-y-auto px-6 py-2 text-sm">
          {saved.map((t) => {
            const last = t.last!;
            const rec = REC[last.recommendation];
            return (
              <li key={t.ticket_id} className="flex items-center justify-between gap-3 py-2">
                <span>
                  <b className="font-semibold tabular-nums">{t.ticket_id}</b>
                  <span className="block text-[12px] text-muted">{last.generated_at ? when(last.generated_at) : "data desconhecida"}</span>
                </span>
                <span className="flex items-center gap-1.5 font-medium" style={{ color: rec?.color }}>
                  <i className="size-2.5 rounded-full" style={{ background: rec?.color }} />
                  {rec?.short ?? last.recommendation}{last.score !== null ? ` · score ${last.score}` : ""}
                </span>
              </li>
            );
          })}
        </ul>

        <footer className="flex flex-col-reverse gap-2 border-t border-line px-6 py-4 sm:flex-row sm:justify-end">
          <button onClick={rerun}
            className="flex items-center justify-center gap-1.5 rounded-lg border border-line px-3 py-1.5 font-medium hover:bg-paper">
            <RefreshCw size={15} /> Executar novamente
          </button>
          <button autoFocus onClick={useSaved}
            className="flex items-center justify-center gap-1.5 rounded-lg bg-blueprint px-4 py-1.5 font-semibold text-white hover:bg-[#1d44a0]">
            <History size={15} /> Usar resultado anterior
          </button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
