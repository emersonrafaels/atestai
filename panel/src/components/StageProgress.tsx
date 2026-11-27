import { Check } from "lucide-react";
import type { TicketState } from "../api";
import { STAGES } from "../format";

/** Progresso do pipeline de um chamado: a sequência real checklist → escopo → orçamento → fotos → documentos → score → parecer. */
export function StageProgress({ state, compact = false }: { state: TicketState; compact?: boolean }) {
  const returnedAtChecklist = state.assessment?.recommendation === "checklist_returned";
  return (
    <ol className={compact ? "flex items-center gap-1" : "grid overflow-x-auto pb-1"} aria-label="Etapas da análise"
      style={compact ? undefined : { gridTemplateColumns: `repeat(${STAGES.length}, minmax(4.5rem, 1fr))` }}>
      {STAGES.map((e, i) => {
        const made = state.completed_stages.includes(e.id) || state.status === "done";
        const pulada = returnedAtChecklist && i > 0;
        const current = state.status === "running" && state.stage === e.id;
        if (compact) {
          return (
            <li key={e.id} title={e.label}
              className={`h-1.5 w-5 rounded-full ${pulada ? "bg-line" : made ? "bg-blueprint" : current ? "bg-blueprint pulso" : "bg-line"}`} />
          );
        }
        // etapa seguinte já alcançada: a linha de ligação fica preenchida até ela
        const next = STAGES[i + 1];
        const reached = next && !pulada && (state.completed_stages.includes(next.id) || state.status === "done" || (state.status === "running" && state.stage === next.id));
        return (
          <li key={e.id} className="relative flex min-w-0 flex-col items-center text-center" aria-current={current ? "step" : undefined}>
            {i < STAGES.length - 1 && (
              <span aria-hidden className={`absolute left-1/2 top-3 h-0.5 w-full -translate-y-1/2 ${reached ? "bg-blueprint" : "bg-line"}`} />
            )}
            <span className={`relative z-10 flex size-6 items-center justify-center rounded-full border text-[11px] font-bold tabular-nums ${
              pulada ? "border-dashed border-line bg-paper text-muted/60"
                : made ? "border-blueprint bg-blueprint text-white"
                : current ? "border-2 border-blueprint bg-sheet text-blueprint pulso"
                : "border-line bg-sheet text-muted"}`}>
              {pulada ? "–" : made ? <Check size={13} strokeWidth={3} /> : i + 1}
            </span>
            <span className={`mt-1.5 px-0.5 text-[12px] leading-tight ${
              pulada ? "text-muted/60 line-through" : current ? "font-semibold text-blueprint" : made ? "text-ink" : "text-muted"}`}>
              {e.label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
