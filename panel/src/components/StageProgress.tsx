import { Check } from "lucide-react";
import type { TicketState } from "../api";
import { STAGES } from "../format";

/** Progresso do pipeline de um chamado: a sequência real checklist → escopo → orçamento → fotos → score → parecer. */
export function StageProgress({ state, compact = false }: { state: TicketState; compact?: boolean }) {
  const returnedAtChecklist = state.assessment?.recommendation === "checklist_returned";
  return (
    <ol className={`flex items-center ${compact ? "gap-1" : "gap-2"}`} aria-label="Etapas da análise">
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
        return (
          <li key={e.id} className="flex items-center gap-2">
            <span className={`flex h-7 items-center gap-1.5 rounded-full border px-3 text-[13px] ${
              pulada ? "border-line text-muted/60 line-through"
                : made ? "border-blueprint bg-blueprint text-white"
                : current ? "border-blueprint text-blueprint pulso"
                : "border-line text-muted"}`}>
              {made && !pulada && <Check size={13} strokeWidth={3} />}
              {e.label}
            </span>
            {i < STAGES.length - 1 && <span className="h-px w-3 bg-line" />}
          </li>
        );
      })}
    </ol>
  );
}
