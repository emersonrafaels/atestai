import { ChevronRight } from "lucide-react";
import type { Assessment } from "../api";
import { brl4, STAGES, TASK_LABELS } from "../format";

/** Cada chamada ao modelo deste chamado: tarefa, modelo, tempo, tokens e o JSON devolvido. */
export function LlmCallsTab({ p }: { p: Assessment }) {
  const totalIn = p.llm_calls.reduce((s, c) => s + c.input_tokens, 0);
  const totalOut = p.llm_calls.reduce((s, c) => s + c.output_tokens, 0);
  const totalStages = Object.values(p.stage_durations_s).reduce((s, v) => s + v, 0) || 1;
  const COLORS = ["#2450b8", "#4f74c9", "#7a97d8", "#a5b9e6", "#c4d1ee", "#dbe3f5"];
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-4">
        <Card label="Chamadas ao modelo" value={String(p.llm_calls.length)} />
        <Card label="Tokens (entrada / saída)" value={`${totalIn.toLocaleString("pt-BR")} / ${totalOut.toLocaleString("pt-BR")}`} />
        <Card label="Custo da análise" value={p.mode === "api" ? brl4(p.cost_brl) : "simulado"} sub={p.mode === "api" ? `US$ ${p.cost_usd.toFixed(5)}${p.batch_mode === "batch" ? ", com 50% de desconto do envio em lote" : ""}` : undefined} />
        <Card label="Tempo total" value={`${p.duration_s.toFixed(1)} s`} sub={p.batch_mode === "batch" ? "inclui a espera dos lotes" : undefined} />
      </div>
      <div>
        <div className="mb-1 text-sm text-muted">Tempo por etapa</div>
        <div className="flex h-6 overflow-hidden rounded-md text-[11px] text-white">
          {STAGES.filter((e) => p.stage_durations_s[e.id] !== undefined).map((e, i) => (
            <div key={e.id} title={`${e.label}: ${p.stage_durations_s[e.id].toFixed(2)} s`} className="flex items-center justify-center overflow-hidden whitespace-nowrap px-1"
              style={{ width: `${Math.max(4, (100 * p.stage_durations_s[e.id]) / totalStages)}%`, background: COLORS[i], color: i > 2 ? "#12233f" : "white" }}>
              {(100 * p.stage_durations_s[e.id]) / totalStages > 9 ? `${e.label} ${p.stage_durations_s[e.id].toFixed(1)}s` : ""}
            </div>
          ))}
        </div>
      </div>
      <p className="text-sm text-muted">
        Prompts versão {p.prompts_version} · régua {p.rubric_version}.
        {p.mode === "simulated" && " Respostas simuladas: servem para demonstrar o fluxo, não para medir qualidade."}
      </p>
      <ol className="space-y-2">
        {p.llm_calls.map((c, i) => (
          <li key={i}>
            <details className="group rounded-xl border border-line bg-sheet">
              <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3">
                <ChevronRight size={16} className="shrink-0 transition group-open:rotate-90" />
                <span className="w-6 text-sm tabular-nums text-muted">{i + 1}</span>
                <span className="flex-1 font-medium">{TASK_LABELS[c.task] ?? c.task}</span>
                <span className="hidden text-sm text-muted md:inline">{c.model}</span>
                {c.via_batch && <span className="rounded bg-blueprint-soft px-1.5 text-[11px] font-semibold text-blueprint" title={c.batch_id ? `Lote ${c.batch_id}` : ""}>lote</span>}
                <span className="w-20 text-right text-sm tabular-nums text-muted">
                  {c.from_cache ? "cache" : `${c.duration_s.toFixed(2)} s`}
                </span>
                <span className="w-24 text-right text-sm tabular-nums text-muted">{c.simulated ? "—" : `US$ ${c.cost_usd.toFixed(5)}`}</span>
                <span className="w-32 text-right text-sm tabular-nums text-muted">{c.input_tokens.toLocaleString("pt-BR")} → {c.output_tokens.toLocaleString("pt-BR")}</span>
              </summary>
              <pre className="json max-h-[420px] overflow-auto border-t border-line bg-paper/60 px-4 py-3"
                dangerouslySetInnerHTML={{ __html: highlight(c.response) }} />
            </details>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Card({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-line bg-sheet p-3">
      <div className="text-[13px] text-muted">{label}</div>
      <div className="mt-0.5 text-lg font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-[12px] text-muted">{sub}</div>}
    </div>
  );
}

function highlight(obj: unknown): string {
  const esc = JSON.stringify(obj, null, 2).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g, (m) => {
    const cls = /^"/.test(m) ? (/:$/.test(m) ? "k" : "s") : /true|false|null/.test(m) ? "b" : "n";
    return `<span class="${cls}">${m}</span>`;
  });
}
