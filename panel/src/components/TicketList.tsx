import { CircleCheck, CircleX, Image as ImageIcon, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import type { TicketSummary, Dataset, Run } from "../api";
import { REC } from "../format";
import { StageProgress } from "./StageProgress";
import { InfoTip, Tooltip } from "./ui/Tooltip";

interface Props {
  tickets: TicketSummary[];
  selected: Set<string>;
  toggle: (id: string) => void;
  setAll: (ids: string[], mark: boolean) => void;
  focus: string | null;
  focusTicket: (id: string) => void;
  execution: Run | null;
  streamFilter: "all" | "SETA" | "SISR";
  setStreamFilter: (f: "all" | "SETA" | "SISR") => void;
  datasets: Dataset[];
  dataset: string;
  setDataset: (c: string) => void;
  collapsed: boolean;
  setCollapsed: (v: boolean) => void;
}

export function TicketList(p: Props) {
  const visible = p.tickets.filter((c) => (p.streamFilter === "all" || c.workstream === p.streamFilter) && (p.dataset === "all" || c.dataset === p.dataset));
  const allMarked = visible.length > 0 && visible.every((c) => p.selected.has(c.ticket_id));
  const markedVisible = visible.filter((c) => p.selected.has(c.ticket_id)).length;
  if (p.collapsed) return <Rail {...p} visible={visible} />;
  return (
    <aside data-tour="ticket-list" className="flex min-h-0 flex-col border-r border-line bg-sheet">
      <div className="flex items-center gap-2 border-b border-line px-4 pt-3 pb-2 text-sm">
        <Tooltip content="Recolher a lista (atalho: [ )">
          <button onClick={() => p.setCollapsed(true)} aria-label="Recolher a lista de chamados" aria-expanded="true"
            className="-ml-1.5 rounded-md p-1 text-muted hover:bg-paper hover:text-ink"><PanelLeftClose size={18} /></button>
        </Tooltip>
        <label htmlFor="dataset" className="text-muted">Conjunto</label>
        <InfoTip text="Demonstração traz os casos do deck; Validação, chamados com defeitos injetados; Enviados, os que você mandou pelo painel." />
        <select id="dataset" value={p.dataset} onChange={(e) => p.setDataset(e.target.value)}
          className="flex-1 rounded-md border border-line bg-sheet px-2 py-1">
          {p.datasets.filter((c) => c.name !== "all").map((c) => <option key={c.name} value={c.name}>{c.label.split(" (")[0]} ({c.n})</option>)}
          <option value="all">Todos ({p.tickets.length})</option>
        </select>
      </div>
      <div className="flex items-center justify-between gap-2 border-b border-line px-4 py-2">
        <div className="flex rounded-lg bg-paper p-0.5 text-sm" role="tablist" aria-label="Esteira">
          {(["all", "SETA", "SISR"] as const).map((f) => (
            <button key={f} role="tab" aria-selected={p.streamFilter === f} onClick={() => p.setStreamFilter(f)}
              className={`rounded-md px-3 py-1 ${p.streamFilter === f ? "bg-sheet font-semibold shadow-sm" : "text-muted"}`}>
              {f === "all" ? "Todos" : f}
            </button>
          ))}
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-muted">
          <input type="checkbox" className="size-4 accent-[var(--color-blueprint)]" checked={allMarked}
            onChange={(e) => p.setAll(visible.map((c) => c.ticket_id), e.target.checked)} />
          Marcar todos
        </label>
      </div>
      <div className="flex items-center justify-between border-b border-line bg-paper/50 px-4 py-1.5 text-[12px] text-muted">
        <span>{visible.length} chamado{visible.length === 1 ? "" : "s"}</span>
        <span className={markedVisible ? "font-medium text-blueprint" : ""}>{markedVisible} marcado{markedVisible === 1 ? "" : "s"} para analisar</span>
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {!visible.length && (
          <li className="px-6 py-10 text-center text-sm text-muted">Nenhum chamado neste filtro. Troque o conjunto ou a esteira acima.</li>
        )}
        {visible.map((c) => {
          const st = p.execution?.tickets[c.ticket_id];
          const done = st?.assessment;
          const active = p.focus === c.ticket_id;
          return (
            <li key={c.ticket_id}
              className={`relative flex gap-3 border-b border-line/70 px-4 py-3 ${active ? "bg-blueprint-soft" : "hover:bg-paper/60"}`}>
              {active && <span className="absolute inset-y-0 left-0 w-1 bg-blueprint" />}
              <input type="checkbox" aria-label={`Selecionar chamado ${c.ticket_id}`} className="mt-1 size-4 shrink-0 accent-[var(--color-blueprint)]"
                checked={p.selected.has(c.ticket_id)} onChange={() => p.toggle(c.ticket_id)} />
              <button className="min-w-0 flex-1 text-left" onClick={() => p.focusTicket(c.ticket_id)}>
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-semibold tabular-nums">{c.ticket_id}</span>
                  <span className="flex gap-1">
                    {c.origin === "upload" && <Tooltip content="Enviado pelo painel (Novo chamado)"><span className="rounded bg-[#fdf1dc] px-1.5 text-[11px] font-semibold text-warn">Enviado</span></Tooltip>}
                    <span className={`rounded px-1.5 text-[11px] font-semibold ${c.workstream === "SETA" ? "bg-blueprint-soft text-blueprint" : "bg-[#ece6f6] text-lock"}`}>
                      {c.workstream}
                    </span>
                  </span>
                </div>
                <div className="mt-0.5 text-[13px] font-medium">
                  {c.category_label} <span className="text-muted">— {c.symptom_label}</span>
                </div>
                <p className="mt-1 line-clamp-2 text-[13px] leading-snug text-muted">{c.scope}</p>
                <div className="mt-2 flex items-center gap-3 text-[12px] text-muted">
                  <span className="flex items-center gap-1"><ImageIcon size={13} /> {c.n_photos}</span>
                  {!done && !st && c.last && (
                    <span className="font-medium" style={{ color: REC[c.last.recommendation].color }}>
                      Último: {c.last.score !== null ? `score ${c.last.score}` : "↩"} · {REC[c.last.recommendation].short}{c.last.feedback ? " · com decisão" : ""}
                    </span>
                  )}
                  {c.expected && !done && !c.last && <span title="Decisão esperada, definida por especialistas">Gabarito: {REC[c.expected.recommendation].short}{c.expected.score !== null ? ` (score ${c.expected.score})` : ""}</span>}
                  {st && st.status !== "done" && st.status !== "error" && (
                    <span className="flex items-center gap-2">{st.status === "queue" ? "Na fila" : <StageProgress state={st} compact />}</span>
                  )}
                  {st?.status === "error" && <span className="font-medium text-bad">Erro</span>}
                  {done && (
                    <span className="flex items-center gap-1.5 font-semibold" style={{ color: REC[done.recommendation].color }}>
                      {done.score !== null ? `score ${done.score}` : "↩"} · {REC[done.recommendation].short}
                      {st?.comparison && (st.comparison.recommendation_ok
                        ? <CircleCheck size={14} className="text-ok" aria-label="igual ao gabarito" />
                        : <CircleX size={14} className="text-bad" aria-label="diferente do gabarito" />)}
                    </span>
                  )}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}

/** Lista recolhida: uma faixa estreita com o status de cada chamado; clique abre o chamado, o botão expande. */
function Rail(p: Props & { visible: TicketSummary[] }) {
  const marked = p.visible.filter((c) => p.selected.has(c.ticket_id)).length;
  return (
    <aside data-tour="ticket-list" aria-label="Lista de chamados (recolhida)"
      className="flex min-h-0 items-center gap-2 border-b border-line bg-sheet px-3 py-2 md:flex-col md:border-b-0 md:border-r md:px-0 md:py-3">
      <Tooltip side="bottom" content="Mostrar a lista de chamados (atalho: [ )">
        <button onClick={() => p.setCollapsed(false)} aria-label="Mostrar a lista de chamados" aria-expanded="false"
          className="rounded-md p-1.5 text-muted hover:bg-paper hover:text-ink"><PanelLeftOpen size={18} /></button>
      </Tooltip>
      <Tooltip content={`${p.visible.length} chamados no filtro · ${marked} marcados para analisar`}>
        <span className="flex cursor-help items-center gap-1 text-[11px] font-semibold tabular-nums text-muted md:flex-col md:gap-0">
          <span>{p.visible.length}</span>
          {marked > 0 && <span className="rounded-full bg-blueprint px-1.5 text-white">{marked}</span>}
        </span>
      </Tooltip>
      <span className="hidden h-px w-6 bg-line md:block" />
      <ul className="flex min-h-0 flex-1 gap-1.5 overflow-auto md:flex-col md:items-center md:pb-2">
        {p.visible.map((c) => {
          const st = p.execution?.tickets[c.ticket_id];
          const rec = st?.assessment?.recommendation ?? (!st ? c.last?.recommendation : undefined);
          const running = st && st.status !== "done" && st.status !== "error";
          const active = p.focus === c.ticket_id;
          const score = st?.assessment ? st.assessment.score : !st ? c.last?.score : null;
          return (
            <li key={c.ticket_id}>
              <Tooltip content={<><b>{c.ticket_id}</b> · {c.category_label}<br />{rec ? `${REC[rec].label}${score != null ? ` · score ${score}` : ""}` : running ? "analisando…" : "ainda não analisado"}{p.selected.has(c.ticket_id) ? " · marcado" : ""}</>}>
                <button onClick={() => p.focusTicket(c.ticket_id)} aria-label={`Abrir chamado ${c.ticket_id}`} aria-current={active ? "true" : undefined}
                  className={`relative flex h-8 w-10 items-center justify-center rounded-md text-[11px] font-semibold tabular-nums transition-colors ${active ? "bg-blueprint text-white" : "bg-paper text-ink/80 hover:bg-blueprint-soft"}`}>
                  {c.ticket_id.slice(-3)}
                  <i className={`absolute -right-0.5 -top-0.5 size-2.5 rounded-full ring-2 ring-sheet ${running ? "pulso bg-blueprint" : ""}`}
                    style={rec && !running ? { background: REC[rec].mark } : !running ? { background: "var(--color-line)" } : undefined} />
                  {p.selected.has(c.ticket_id) && <i className="absolute -bottom-0.5 left-1/2 h-0.5 w-4 -translate-x-1/2 rounded bg-blueprint" />}
                </button>
              </Tooltip>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
