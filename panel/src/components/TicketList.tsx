import { Check, Image as ImageIcon, Info, Loader2, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import { useState } from "react";
import type { TicketSummary, Dataset, Run } from "../api";
import { REC, MAINTENANCE_LABEL, STAGE_LABEL, STAGE_SHORT, envLabel } from "../format";
import { StageProgress } from "./StageProgress";
import { ScorePill } from "./ScoreBadge";
import { InfoTip, Tooltip } from "./ui/Tooltip";
import { Switch } from "./ui/Switch";

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
  // filtros de classificação: etapa da esteira e tipo de manutenção
  const [stage, setStage] = useState<"all" | "quote" | "execution">("all");
  const [kind, setKind] = useState<"all" | "corrective" | "preventive">("all");
  const [onlyMarked, setOnlyMarked] = useState(false);
  const [showAllMarked, setShowAllMarked] = useState(false);
  const marked = p.tickets.filter((c) => p.selected.has(c.ticket_id));
  const filtered = p.tickets.filter((c) => (p.streamFilter === "all" || c.workstream === p.streamFilter) && (p.dataset === "all" || c.dataset === p.dataset)
    && (stage === "all" || c.moment === stage) && (kind === "all" || c.maintenance_type === kind));
  // "só marcados" ignora os outros filtros: mostra tudo o que vai para a análise
  const visible = onlyMarked && marked.length ? marked : filtered;
  const hiddenMarked = marked.filter((c) => !filtered.includes(c));
  const inScope = p.tickets.filter((c) => (p.streamFilter === "all" || c.workstream === p.streamFilter) && (p.dataset === "all" || c.dataset === p.dataset));
  const count = (f: (c: TicketSummary) => boolean) => inScope.filter(f).length;
  const allMarked = visible.length > 0 && visible.every((c) => p.selected.has(c.ticket_id));
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
        <Tooltip content={`Marca ou desmarca os ${visible.length} chamados que aparecem na lista agora`}>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-muted">
            <input type="checkbox" className="size-4 accent-[var(--color-blueprint)]" checked={allMarked}
              onChange={(e) => p.setAll(visible.map((c) => c.ticket_id), e.target.checked)} />
            Marcar todos
          </label>
        </Tooltip>
      </div>
      <div className="grid grid-cols-2 gap-2 border-b border-line px-4 py-2 text-[13px]">
        <label className="min-w-0">
          <span className="mb-0.5 flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted">Etapa <InfoTip term="stage" size={11} /></span>
          <select value={stage} onChange={(e) => setStage(e.target.value as typeof stage)} className={`w-full rounded-md border bg-sheet px-1.5 py-1 ${stage !== "all" ? "border-blueprint text-blueprint" : "border-line"}`}>
            <option value="all">Todas ({inScope.length})</option>
            <option value="quote">{STAGE_LABEL.quote} ({count((c) => c.moment === "quote")})</option>
            <option value="execution">{STAGE_LABEL.execution} ({count((c) => c.moment === "execution")})</option>
          </select>
        </label>
        <label className="min-w-0">
          <span className="mb-0.5 flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted">Tipo <InfoTip term="maintenance" size={11} /></span>
          <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} className={`w-full rounded-md border bg-sheet px-1.5 py-1 ${kind !== "all" ? "border-blueprint text-blueprint" : "border-line"}`}>
            <option value="all">Todos ({inScope.length})</option>
            <option value="corrective">Corretiva ({count((c) => c.maintenance_type === "corrective")})</option>
            <option value="preventive">Preventiva ({count((c) => c.maintenance_type === "preventive")})</option>
          </select>
        </label>
      </div>
      <div className="flex items-center justify-between border-b border-line bg-paper/50 px-4 py-1.5 text-[12px] text-muted">
        <span>
          {onlyMarked && marked.length ? "Mostrando só os marcados" : <>{visible.length} chamado{visible.length === 1 ? "" : "s"}</>}
          {!onlyMarked && (stage !== "all" || kind !== "all") && <button onClick={() => { setStage("all"); setKind("all"); }} className="ml-1.5 font-medium text-blueprint hover:underline">limpar filtros</button>}
        </span>
        <label className={`flex items-center gap-1.5 ${marked.length ? "cursor-pointer" : "opacity-50"}`}>
          <Switch size="sm" on={onlyMarked && marked.length > 0} disabled={!marked.length} onChange={setOnlyMarked} label="Mostrar só os marcados" />
          Só marcados
        </label>
      </div>
      <MarkedTray marked={marked} hidden={hiddenMarked} focus={p.focus} expanded={showAllMarked} setExpanded={setShowAllMarked}
        open={p.focusTicket} unmark={p.toggle} clear={() => { p.setAll(marked.map((c) => c.ticket_id), false); setOnlyMarked(false); }} />
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {!visible.length && (
          <li className="px-6 py-10 text-center text-sm text-muted">Nenhum chamado neste filtro. Troque o conjunto, a esteira, a etapa ou o tipo acima.</li>
        )}
        {visible.map((c) => {
          const st = p.execution?.tickets[c.ticket_id];
          const done = st?.assessment;
          const active = p.focus === c.ticket_id;
          const isMarked = p.selected.has(c.ticket_id);
          return (
            <li key={c.ticket_id}
              className={`relative flex gap-3 border-b border-line/70 px-4 py-3 transition-colors ${active ? "bg-blueprint-soft" : isMarked ? "bg-[#f3f6fd] hover:bg-blueprint-soft/70" : "hover:bg-paper/60"}`}>
              {active && <span className="absolute inset-y-0 left-0 w-1 bg-blueprint" />}
              {!active && isMarked && <span className="absolute inset-y-0 left-0 w-1 bg-blueprint/30" />}
              <label className="-m-2 flex h-fit cursor-pointer p-2" title={isMarked ? "Desmarcar (sai da próxima análise)" : "Marcar para analisar"}>
                <input type="checkbox" aria-label={`${isMarked ? "Desmarcar" : "Marcar"} chamado ${c.ticket_id} para analisar`} className="mt-1 size-4 shrink-0 cursor-pointer accent-[var(--color-blueprint)]"
                  checked={isMarked} onChange={() => p.toggle(c.ticket_id)} />
              </label>
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
                <div className="mt-1 flex flex-wrap gap-1 text-[11px] font-semibold">
                  <span className={`rounded px-1.5 ${c.maintenance_type === "preventive" ? "bg-[#e3f2ea] text-ok" : "bg-[#fdf1dc] text-warn"}`}>{MAINTENANCE_LABEL[c.maintenance_type] ?? c.maintenance_type}</span>
                  <span className="rounded bg-paper px-1.5 text-ink/70" title={STAGE_LABEL[c.moment]}>{STAGE_SHORT[c.moment] ?? c.moment}</span>
                </div>
                {c.scenario && <p className="mt-1 text-[12px] font-semibold text-blueprint">Cenário: {c.scenario.title}</p>}
                <p className="mt-1 line-clamp-2 text-[13px] leading-snug text-muted">{c.scope}</p>
                <div className="mt-2 flex items-center gap-3 text-[12px] text-muted">
                  <span className="flex items-center gap-1"><ImageIcon size={13} /> {c.n_photos}</span>
                  {!done && !st && c.last && (
                    <span className="flex items-center gap-1.5"><span className="text-[11px] uppercase tracking-wide">último</span><ScorePill score={c.last.score} recommendation={c.last.recommendation} decided={!!c.last.feedback} muted /></span>
                  )}
                  {st && st.status !== "done" && st.status !== "error" && (
                    <span className="flex items-center gap-2">{st.status === "queue" ? "Na fila" : <StageProgress state={st} compact />}</span>
                  )}
                  {st?.status === "error" && <span className="font-medium text-bad">Erro</span>}
                  {done && (
                    <ScorePill score={done.score} recommendation={done.recommendation} />
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

/**
 * Lista recolhida: uma faixa com um "cartão" por chamado (fim do número, score e cor da recomendação, esteira
 * e marcação). Clique abre; Shift+clique marca ou desmarca para a próxima análise; o botão do topo expande.
 */
function Rail(p: Props & { visible: TicketSummary[] }) {
  const marked = p.visible.filter((c) => p.selected.has(c.ticket_id)).length;
  const analysed = p.visible.filter((c) => p.execution?.tickets[c.ticket_id]?.assessment || c.last).length;
  return (
    <aside data-tour="ticket-list" aria-label="Lista de chamados (recolhida)"
      className="flex min-h-0 items-center gap-2 border-b border-line bg-sheet px-3 py-2 md:flex-col md:items-stretch md:gap-0 md:border-b-0 md:border-r md:p-0">
      <div className="flex items-center gap-2 md:flex-col md:gap-1.5 md:border-b md:border-line md:px-2 md:py-2.5">
        <Tooltip side="bottom" content="Mostrar a lista de chamados (atalho: [ )">
          <button onClick={() => p.setCollapsed(false)} aria-label="Mostrar a lista de chamados" aria-expanded="false"
            className="flex size-9 items-center justify-center rounded-lg border border-line text-muted transition-colors hover:border-blueprint hover:bg-blueprint-soft hover:text-blueprint">
            <PanelLeftOpen size={18} />
          </button>
        </Tooltip>
        <Tooltip content={<>{p.visible.length} chamados no filtro<br />{analysed} já analisados · {marked} marcados para analisar</>}>
          <div className="flex cursor-help items-center gap-1.5 md:flex-col md:gap-1">
            <span className="text-[13px] font-bold tabular-nums leading-none">{p.visible.length}</span>
            <span className="hidden text-[10px] uppercase tracking-wide text-muted md:block">chamados</span>
            {marked > 0 && (
              <span className="flex items-center gap-0.5 rounded-full bg-blueprint px-1.5 py-px text-[10px] font-semibold tabular-nums text-white">
                <Check size={10} strokeWidth={3} />{marked}
              </span>
            )}
          </div>
        </Tooltip>
      </div>

      <ul className="flex min-h-0 flex-1 gap-1.5 overflow-auto md:flex-col md:items-center md:px-2 md:py-2">
        {p.visible.map((c) => {
          const st = p.execution?.tickets[c.ticket_id];
          const a = st?.assessment;
          const rec = a?.recommendation ?? (!st ? c.last?.recommendation : undefined);
          const score = a ? a.score : !st ? c.last?.score ?? null : null;
          const running = !!st && st.status !== "done" && st.status !== "error";
          const failed = st?.status === "error";
          const active = p.focus === c.ticket_id;
          const isMarked = p.selected.has(c.ticket_id);
          return (
            <li key={c.ticket_id} className="md:w-full">
              <Tooltip className="flex" content={
                <>
                  <b>{c.ticket_id}</b> · {c.workstream}<br />
                  {MAINTENANCE_LABEL[c.maintenance_type] ?? c.maintenance_type} · {c.category_label} · {c.symptom_label} · {STAGE_LABEL[c.moment] ?? c.moment}<br />
                  <span className="opacity-80">{c.branch}{c.environment ? ` · local: ${envLabel(c.environment)}` : ""}</span><br />
                  {running ? "Analisando…" : failed ? "Erro na análise" : rec ? <>{REC[rec].label}{score !== null ? ` · score ${score}` : ""}</> : "Ainda não analisado"}
                  {isMarked ? " · marcado" : ""}
                  <span className="mt-1 block opacity-70">Clique para abrir · Shift+clique para {isMarked ? "desmarcar" : "marcar"}</span>
                </>
              }>
                <button
                  onClick={(e) => (e.shiftKey ? p.toggle(c.ticket_id) : p.focusTicket(c.ticket_id))}
                  aria-label={`Abrir chamado ${c.ticket_id}`} aria-current={active ? "true" : undefined}
                  className={`relative flex w-14 flex-col items-center overflow-hidden rounded-lg border py-1 leading-tight transition-colors md:w-full ${
                    active ? "border-blueprint bg-blueprint text-white shadow-sm" : "border-line bg-sheet hover:border-blueprint/50 hover:bg-blueprint-soft"}`}>
                  {/* esteira: faixa à esquerda */}
                  <span className={`absolute inset-y-0 left-0 w-1 ${c.workstream === "SETA" ? "bg-blueprint" : "bg-lock"} ${active ? "opacity-0" : "opacity-70"}`} />
                  <span className="text-[12px] font-bold tabular-nums">{c.ticket_id.slice(-4)}</span>
                  <span className={`mt-0.5 flex items-center gap-1 text-[10px] font-semibold tabular-nums ${active ? "text-white/90" : "text-muted"}`}>
                    {running ? <Loader2 size={10} className="animate-spin" /> : failed ? <span className="text-bad">erro</span> : rec ? (
                      <>
                        <i className="size-2 rounded-full ring-1 ring-white/70" style={{ background: REC[rec].mark }} />
                        {score !== null ? score : "↩"}
                      </>
                    ) : "—"}
                  </span>
                  {isMarked && (
                    <span className={`absolute right-0.5 top-0.5 flex size-3.5 items-center justify-center rounded-full ${active ? "bg-white text-blueprint" : "bg-blueprint text-white"}`}>
                      <Check size={9} strokeWidth={4} />
                    </span>
                  )}
                </button>
              </Tooltip>
            </li>
          );
        })}
      </ul>

      <Tooltip side="top" content={
        <span className="block space-y-1">
          <b className="block">Legenda</b>
          <span className="flex items-center gap-1.5"><i className="h-3 w-1 rounded bg-[#2450b8]" /> SETA <i className="ml-2 h-3 w-1 rounded bg-[#5b3a9e]" /> SISR</span>
          {(["approve", "approve_with_caveats", "return_to_supplier", "return_locked", "detailed_review", "checklist_returned"] as const).map((r) => (
            <span key={r} className="flex items-center gap-1.5"><i className="size-2 rounded-full" style={{ background: REC[r].mark }} />{REC[r].label}</span>
          ))}
          <span className="block opacity-80">Número = score · ✓ = marcado para analisar</span>
        </span>
      }>
        <span role="button" tabIndex={0} aria-label="Legenda das cores"
          className="hidden cursor-help items-center justify-center gap-1 border-t border-line py-2 text-[11px] text-muted hover:text-ink md:flex">
          <Info size={13} /> legenda
        </span>
      </Tooltip>
    </aside>
  );
}


/**
 * Painel dos marcados para analisar: total (inclusive os que o filtro esconde), um selo por chamado para abrir
 * ou desmarcar, e "Limpar". É o que vai para o botão Analisar.
 */
function MarkedTray({ marked, hidden, focus, expanded, setExpanded, open, unmark, clear }: {
  marked: TicketSummary[]; hidden: TicketSummary[]; focus: string | null; expanded: boolean; setExpanded: (v: boolean) => void;
  open: (id: string) => void; unmark: (id: string) => void; clear: () => void;
}) {
  if (!marked.length) {
    return <div className="border-b border-line px-4 py-2 text-[12px] text-muted">Nenhum chamado marcado. Marque as caixas para escolher o que analisar.</div>;
  }
  const LIMIT = 6;
  const shown = expanded ? marked : marked.slice(0, LIMIT);
  return (
    <section aria-label="Chamados marcados para analisar" className="border-b border-line bg-[#f3f6fd] px-4 py-2.5">
      <div className="mb-1.5 flex items-center justify-between gap-2 text-[13px]">
        <span className="flex items-center gap-1.5 font-semibold text-blueprint">
          <span className="flex size-5 items-center justify-center rounded bg-blueprint text-white"><Check size={13} strokeWidth={3} /></span>
          {marked.length} marcado{marked.length === 1 ? "" : "s"} para analisar
        </span>
        <button onClick={clear} className="rounded-md px-1.5 py-0.5 text-[12px] font-medium text-muted hover:bg-sheet hover:text-bad">Limpar</button>
      </div>
      {hidden.length > 0 && (
        <p className="mb-1.5 text-[12px] text-warn">{hidden.length} {hidden.length === 1 ? "está" : "estão"} fora do filtro atual (selo tracejado).</p>
      )}
      <ul className="flex flex-wrap gap-1.5">
        {shown.map((c) => {
          const outside = hidden.includes(c);
          return (
            <li key={c.ticket_id}>
              <span className={`flex items-center rounded-full text-[12px] font-semibold tabular-nums ${
                focus === c.ticket_id ? "bg-blueprint text-white" : outside ? "border border-dashed border-blueprint/50 bg-sheet text-blueprint" : "bg-sheet text-blueprint ring-1 ring-blueprint/25"}`}>
                <Tooltip content={<>{c.category_label} · {c.symptom_label}{outside ? <><br />Fora do filtro atual</> : null}<br />Clique para abrir</>}>
                  <button onClick={() => open(c.ticket_id)} className="py-0.5 pl-2 pr-1">{c.ticket_id}</button>
                </Tooltip>
                <button onClick={() => unmark(c.ticket_id)} aria-label={`Desmarcar ${c.ticket_id}`} title="Desmarcar"
                  className={`mr-0.5 rounded-full p-0.5 ${focus === c.ticket_id ? "hover:bg-white/20" : "hover:bg-[#f8e4e2] hover:text-bad"}`}>
                  <X size={12} strokeWidth={2.5} />
                </button>
              </span>
            </li>
          );
        })}
        {marked.length > LIMIT && (
          <li>
            <button onClick={() => setExpanded(!expanded)} className="rounded-full px-2 py-0.5 text-[12px] font-medium text-blueprint hover:bg-sheet">
              {expanded ? "mostrar menos" : `+${marked.length - LIMIT} outros`}
            </button>
          </li>
        )}
      </ul>
    </section>
  );
}
