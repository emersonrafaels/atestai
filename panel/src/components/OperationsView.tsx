import { AlertTriangle, ChevronRight, Loader2, RefreshCw, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type RunSummary, type OperationsView as M } from "../api";
import { brl, brl4, pct, REC, TASK_LABELS, FINDING_LABELS } from "../format";
import { InfoTip, Tooltip } from "./ui/Tooltip";
import { InfoBox } from "./ui/InfoBox";
import { Card, Kpi, Meter, ago } from "./ui/Panel";

const PAGE = 8;

/** Operação: volume, custo, latência por tarefa, erros e o que a pessoa analista tem corrigido. */
export function OperationsView({ openRun }: { openRun: (id: string) => void }) {
  const [m, setM] = useState<M | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [, tick] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [mm, rr] = await Promise.all([api.metrics(), api.runs()]);
      setM(mm);
      setRuns(rr);
      setUpdated(new Date());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { const t = window.setInterval(() => tick((n) => n + 1), 30000); return () => window.clearInterval(t); }, []);

  if (!m) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-muted">
        {error ? <><AlertTriangle className="text-bad" /> <span>{error}</span><button onClick={load} className="rounded-lg border border-line bg-sheet px-3 py-1.5 text-sm">Tentar de novo</button></> : <Loader2 className="animate-spin" />}
      </div>
    );
  }

  const fb = Object.fromEntries(m.feedback.map((f) => [f.action, f.n])) as Record<string, number>;
  const decided = m.feedback_agreement.total;
  const acceptRate = decided ? (m.feedback_agreement.accepted ?? 0) / decided : null;
  const errorsRate = m.with_errors !== null && m.assessments ? m.with_errors / (m.assessments + m.with_errors) : null;

  return (
    <div className="mx-auto max-w-[1180px] space-y-6 px-6 py-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="largo text-[28px] font-bold">Operação</h2>
          <p className="text-sm text-muted">Tudo o que já passou pelo Atest.AI neste ambiente, lido do banco.</p>
        </div>
        <div className="flex items-center gap-3 text-sm">
          {updated && <span className="text-muted">Atualizado {ago(updated)}</span>}
          <button onClick={load} disabled={loading} className="flex items-center gap-1.5 rounded-lg border border-line bg-sheet px-3 py-1.5 font-medium hover:bg-paper disabled:opacity-60">
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Atualizar
          </button>
        </div>
      </div>
      {error && <p className="text-sm text-bad">{error}</p>}

      <InfoBox id="operacao">Números acumulados de todas as execuções gravadas no banco. Execuções no modo simulado entram no volume, mas não no custo.</InfoBox>

      <section data-tour="ops-kpis" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
        <Kpi label="Pareceres emitidos" value={m.assessments.toLocaleString("pt-BR")} sub={`${m.tickets} chamados · ${m.runs} execuções`} />
        <Kpi label="Tempo médio por parecer" value={m.avg_duration_s !== null ? `${m.avg_duration_s.toFixed(1)} s` : "—"} sub="do checklist ao parecer"
          help={<InfoTip text="Inclui a espera da API. No modo batch, inclui a espera do lote." />} />
        <Kpi label="Custo com a API" value={brl(m.cost_brl)} sub={`US$ ${m.cost_usd.toFixed(4)}`} />
        <Kpi label="Custo médio por chamado" value={m.avg_cost_brl ? brl4(m.avg_cost_brl) : "—"} sub="só execuções no modo API"
          help={<InfoTip text="Custo total da API dividido pelos pareceres gerados no modo API." />} />
        <Kpi label="Valor em questão" value={brl(m.amount_at_issue)} sub="soma de todos os pareceres" help={<InfoTip term="amount" />} />
        <Kpi label="Aceite do parecer" value={acceptRate !== null ? pct(acceptRate) : "—"} tone={acceptRate === null ? undefined : acceptRate >= 0.8 ? "ok" : acceptRate >= 0.6 ? "warn" : "bad"}
          sub={decided ? `${decided} decisões registradas` : "nenhuma decisão registrada"}
          help={<InfoTip text="Percentual das decisões em que a pessoa analista aceitou o parecer como veio. Abaixo de 80% vale investigar os apontamentos contestados." />} />
      </section>

      {errorsRate !== null && m.with_errors! > 0 && (
        <InfoBox tone="warn" title={`${m.with_errors} chamado${m.with_errors === 1 ? "" : "s"} terminou com erro`}>
          {pct(errorsRate, 1)} das análises falharam (ex.: planilha ilegível ou falha na API). Veja as execuções com erro na lista abaixo.
        </InfoBox>
      )}

      <Volume days={m.by_day} />

      <section className="grid gap-5 lg:grid-cols-2">
        <Recommendations m={m} />
        <Card title="Custo por esteira" sub="Pareceres e custo da API, separados por SETA e SISR.">
          {m.cost_by_workstream.length ? (
            <ul className="space-y-3 text-sm">
              {m.cost_by_workstream.map((w) => {
                const max = Math.max(...m.cost_by_workstream.map((x) => x.cost_brl), 0.0001);
                return (
                  <li key={w.workstream}>
                    <div className="mb-1 flex items-baseline justify-between gap-2">
                      <span className={`rounded px-1.5 text-[12px] font-semibold ${w.workstream === "SETA" ? "bg-blueprint-soft text-blueprint" : "bg-[#ece6f6] text-lock"}`}>{w.workstream}</span>
                      <span className="tabular-nums"><b>{brl4(w.cost_brl)}</b> <span className="text-muted">· {w.n} pareceres · média {brl4(w.avg_brl)}</span></span>
                    </div>
                    <Meter value={w.cost_brl} max={max} color={w.workstream === "SETA" ? "#2450b8" : "#6250d6"} />
                  </li>
                );
              })}
            </ul>
          ) : <p className="text-sm text-muted">Sem custo de API registrado ainda.</p>}
        </Card>
      </section>

      <Card tour="ops-feedback" title="Decisões da pessoa analista"
        sub="Como as pessoas analistas reagem aos pareceres. Apontamentos contestados são os primeiros candidatos a ajuste na régua ou nos prompts.">
        {decided ? (
          <div className="grid gap-6 md:grid-cols-2">
            <div>
              <div className="flex h-3 overflow-hidden rounded-full">
                {([["accept", "#008300"], ["adjust", "#2a78d6"], ["disagree", "#e34948"]] as const).map(([k, c]) => (
                  <div key={k} style={{ width: `${(100 * (fb[k] ?? 0)) / decided}%`, background: c }} />
                ))}
              </div>
              <ul className="mt-3 space-y-1.5 text-sm">
                {([["accept", "Aceitos como vieram", "#008300"], ["adjust", "Ajustados (apontamentos corrigidos)", "#2a78d6"], ["disagree", "Discordâncias", "#e34948"]] as const).map(([k, l, c]) => (
                  <li key={k} className="flex items-center gap-2"><i className="size-2.5 rounded-full" style={{ background: c }} />{l}
                    <b className="ml-auto tabular-nums">{fb[k] ?? 0}</b><span className="w-10 text-right tabular-nums text-muted">{pct((fb[k] ?? 0) / decided)}</span></li>
                ))}
              </ul>
              <p className="mt-3 text-[13px] text-muted">Em <b className="text-ink">{m.feedback_agreement.different_decision ?? 0}</b> casos a decisão final foi diferente da recomendação do Atest.AI.</p>
            </div>
            <div>
              <h4 className="mb-2 text-sm font-semibold">Apontamentos contestados</h4>
              {m.unfounded_findings.length ? (
                <ul className="space-y-2 text-sm">
                  {[...m.unfounded_findings].sort((a, b) => b.n - a.n).map((a, i) => {
                    const max = m.unfounded_findings.reduce((s, x) => Math.max(s, x.n), 1);
                    return (
                      <li key={a.kind}>
                        <div className="mb-0.5 flex justify-between gap-2"><span>{FINDING_LABELS[a.kind] ?? a.kind}{i === 0 && <span className="ml-1.5 rounded bg-[#fdf1dc] px-1 text-[10px] font-semibold uppercase text-warn">revisar primeiro</span>}</span><b className="tabular-nums">{a.n}</b></div>
                        <Meter value={a.n} max={max} color="#eda100" height={6} />
                      </li>
                    );
                  })}
                </ul>
              ) : <p className="text-sm text-muted">Nenhum apontamento contestado até agora.</p>}
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted">Nenhuma decisão registrada ainda. Elas aparecem aqui quando alguém registra a decisão no fim do parecer.</p>
        )}
      </Card>

      <Tasks m={m} />
      <Runs runs={runs} openRun={openRun} />
    </div>
  );
}

// ---------------------------------------------------------------------------- volume por dia
function Volume({ days }: { days: M["by_day"] }) {
  const [metric, setMetric] = useState<"n" | "cost_brl">("n");
  const data = [...days].sort((a, b) => a.day.localeCompare(b.day)).slice(-30);
  const max = Math.max(...data.map((d) => d[metric]), metric === "n" ? 1 : 0.0001);
  const total = data.reduce((s, d) => s + d[metric], 0);
  const fmt = (v: number) => (metric === "n" ? v.toLocaleString("pt-BR") : brl4(v));
  const day = (s: string) => new Date(`${s}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
  return (
    <Card title="Volume por dia" sub={data.length ? `Últimos ${data.length} dia${data.length === 1 ? "" : "s"} com atividade · total ${fmt(total)}` : undefined}
      aside={
        <div className="flex rounded-lg bg-paper p-0.5 text-sm">
          {([["n", "Pareceres"], ["cost_brl", "Custo"]] as const).map(([k, l]) => (
            <button key={k} onClick={() => setMetric(k)} aria-pressed={metric === k}
              className={`rounded-md px-3 py-1 ${metric === k ? "bg-sheet font-semibold shadow-sm" : "text-muted hover:text-ink"}`}>{l}</button>
          ))}
        </div>
      }>
      {data.length ? (
        <div className="flex h-40 items-end gap-1.5 border-b border-line">
          {data.map((d) => (
            <Tooltip key={d.day} className="flex h-full min-w-0 max-w-14 flex-1 flex-col justify-end" content={`${day(d.day)}: ${d.n} pareceres · ${brl4(d.cost_brl)}`}>
              <div className="flex h-full flex-col justify-end">
                {data.length <= 10 && <span className="mb-0.5 text-center text-[11px] font-medium tabular-nums">{metric === "n" ? d.n : brl(d.cost_brl)}</span>}
                <div className="rounded-t bg-[#2a78d6] transition-[height] duration-300 hover:bg-blueprint" style={{ height: `${Math.max(2, (100 * d[metric]) / max * 0.85)}%` }} />
                <span className="mt-1 truncate text-center text-[10px] tabular-nums text-muted">{day(d.day)}</span>
                <span className="sr-only">{fmt(d[metric])}</span>
              </div>
            </Tooltip>
          ))}
        </div>
      ) : <p className="text-sm text-muted">Sem atividade registrada ainda.</p>}
    </Card>
  );
}

function Recommendations({ m }: { m: M }) {
  const total = m.by_recommendation.reduce((s, r) => s + r.n, 0);
  const sorted = [...m.by_recommendation].sort((a, b) => b.n - a.n);
  return (
    <Card title="Recomendações" sub={total ? `${total} pareceres` : undefined}>
      {total ? (
        <>
          <div className="flex h-3 overflow-hidden rounded-full">
            {sorted.map((r) => (
              <div key={r.recommendation} style={{ width: `${(100 * r.n) / total}%` }}>
                <Tooltip className="block h-full" content={`${REC[r.recommendation].label}: ${r.n} (${pct(r.n / total)})`}>
                  <div className="h-full" style={{ background: REC[r.recommendation].mark }} />
                </Tooltip>
              </div>
            ))}
          </div>
          <ul className="mt-3 space-y-1.5 text-sm">
            {sorted.map((r) => (
              <li key={r.recommendation} className="flex items-center gap-2">
                <i className="size-2.5 rounded-full" style={{ background: REC[r.recommendation].mark }} />{REC[r.recommendation].label}
                <b className="ml-auto tabular-nums">{r.n}</b><span className="w-10 text-right tabular-nums text-muted">{pct(r.n / total)}</span>
              </li>
            ))}
          </ul>
        </>
      ) : <p className="text-sm text-muted">Nenhum parecer ainda.</p>}
    </Card>
  );
}

// ---------------------------------------------------------------------------- tarefas
function Tasks({ m }: { m: M }) {
  const [sort, setSort] = useState<"cost_usd" | "calls" | "avg_duration_s">("cost_usd");
  const rows = [...m.by_task].sort((a, b) => b[sort] - a[sort]);
  const totalCost = m.by_task.reduce((s, t) => s + t.cost_usd, 0) || 1;
  const th = (k: typeof sort, l: string) => (
    <th className="px-3 py-2 text-right font-medium">
      <button onClick={() => setSort(k)} className={`inline-flex items-center gap-0.5 ${sort === k ? "font-semibold text-ink" : "hover:text-ink"}`}>{l}{sort === k && " ↓"}</button>
    </th>
  );
  return (
    <Card tour="ops-tasks" title="Chamadas ao modelo por tarefa" sub="Clique no cabeçalho para ordenar. Só entram chamadas reais à API.">
      {rows.length ? (
        <div className="-mx-5 overflow-x-auto">
          <table className="w-full min-w-[820px] text-sm">
            <thead className="text-left text-[13px] text-muted">
              <tr>
                <th className="px-5 py-2 font-medium">Tarefa</th><th className="px-3 py-2 font-medium">Modelo</th>
                {th("calls", "Chamadas")}{th("avg_duration_s", "Latência média")}
                <th className="px-3 py-2 text-right font-medium">Tokens (entrada / saída)</th>
                <th className="px-3 py-2 text-right font-medium"><Tooltip content="Parte dos tokens de entrada lida do cache de prompt (mais barata)"><span className="cursor-help">Cache</span></Tooltip></th>
                <th className="px-3 py-2 text-right font-medium">Via batch</th>
                {th("cost_usd", "Custo")}
                <th className="w-32 px-5 py-2 font-medium">% do custo</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {rows.map((t) => {
                const cacheRate = t.input_tokens + t.cache_read_tokens ? t.cache_read_tokens / (t.input_tokens + t.cache_read_tokens) : 0;
                return (
                  <tr key={t.task + t.model} className="border-t border-line/70">
                    <td className="px-5 py-2">{TASK_LABELS[t.task] ?? t.task}</td><td className="px-3 py-2 text-[13px] text-muted">{t.model}</td>
                    <td className="px-3 py-2 text-right">{t.calls}</td><td className="px-3 py-2 text-right">{t.avg_duration_s.toFixed(1)} s</td>
                    <td className="px-3 py-2 text-right">{t.input_tokens.toLocaleString("pt-BR")} / {t.output_tokens.toLocaleString("pt-BR")}</td>
                    <td className="px-3 py-2 text-right">{pct(cacheRate)}</td>
                    <td className="px-3 py-2 text-right">{t.via_batch}</td>
                    <td className="px-3 py-2 text-right">US$ {t.cost_usd.toFixed(4)}</td>
                    <td className="px-5 py-2"><div className="flex items-center gap-2"><Meter value={t.cost_usd} max={totalCost} height={6} /><span className="w-9 text-right text-[12px] text-muted">{pct(t.cost_usd / totalCost)}</span></div></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : <p className="text-sm text-muted">Ainda não houve chamadas reais à API. Execuções no modo simulado não entram aqui.</p>}
    </Card>
  );
}

// ---------------------------------------------------------------------------- execuções
function Runs({ runs, openRun }: { runs: RunSummary[]; openRun: (id: string) => void }) {
  const [filter, setFilter] = useState<"all" | "api" | "simulated" | "errors">("all");
  const [q, setQ] = useState("");
  const [shown, setShown] = useState(PAGE);
  const list = useMemo(() => runs.filter((e) =>
    (filter === "all" || (filter === "errors" ? e.errors && Object.keys(e.errors).length > 0 : e.mode === filter)) &&
    (!q || `${e.id} ${e.label ?? ""} ${e.tickets.join(" ")}`.toLowerCase().includes(q.toLowerCase()))), [runs, filter, q]);
  const nErr = runs.filter((e) => e.errors && Object.keys(e.errors).length).length;
  return (
    <Card tour="ops-runs" title="Execuções recentes" sub="Clique numa execução para abrir os pareceres dela na Análise."
      aside={
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <div className="flex rounded-lg bg-paper p-0.5">
            {([["all", "Todas"], ["api", "API"], ["simulated", "Simulado"], ["errors", `Com erro${nErr ? ` (${nErr})` : ""}`]] as const).map(([k, l]) => (
              <button key={k} onClick={() => { setFilter(k); setShown(PAGE); }} aria-pressed={filter === k}
                className={`rounded-md px-2.5 py-1 ${filter === k ? "bg-sheet font-semibold shadow-sm" : "text-muted hover:text-ink"}`}>{l}</button>
            ))}
          </div>
          <label className="flex items-center gap-1.5 rounded-lg border border-line px-2 py-1 focus-within:border-blueprint">
            <Search size={14} className="text-muted" />
            <input value={q} onChange={(e) => { setQ(e.target.value); setShown(PAGE); }} placeholder="Execução ou chamado" className="w-36 bg-transparent outline-none" />
          </label>
        </div>
      }>
      {!list.length ? (
        <p className="text-sm text-muted">{runs.length ? "Nenhuma execução com este filtro." : "Nenhuma execução ainda. Analise um chamado para começar."}</p>
      ) : (
        <ul className="-mx-5 divide-y divide-line/70 border-t border-line/70">
          {list.slice(0, shown).map((e) => {
            const nErrors = e.errors ? Object.keys(e.errors).length : 0;
            return (
              <li key={e.id}>
                <button onClick={() => openRun(e.id)} className="group grid w-full grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1 px-5 py-2.5 text-left text-sm hover:bg-paper/60 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_auto_auto]">
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{e.label || e.id}</span>
                    <span className="block text-[12px] text-muted">{new Date(e.created_at).toLocaleString("pt-BR")}{e.label ? ` · ${e.id}` : ""}</span>
                  </span>
                  <span className="hidden flex-wrap items-center gap-1.5 md:flex">
                    <span className={`rounded px-1.5 text-[11px] font-semibold ${e.mode === "api" ? "bg-blueprint-soft text-blueprint" : "bg-paper text-muted"}`}>{e.mode === "api" ? (e.batch_mode === "batch" ? "API batch" : "API") : "Simulado"}</span>
                    <span className="text-[12px] text-muted">fase {e.phase} · {e.tickets.length} chamado{e.tickets.length === 1 ? "" : "s"}</span>
                    {e.status === "running" && <span className="flex items-center gap-1 text-[12px] text-blueprint"><Loader2 size={12} className="animate-spin" /> rodando</span>}
                  </span>
                  <span className="flex items-center gap-3 text-[13px] tabular-nums">
                    {e.evaluation && <Tooltip content="Recomendações iguais ao gabarito"><span className="cursor-help">gabarito <b>{e.evaluation.exact_recommendation}/{e.evaluation.n}</b></span></Tooltip>}
                    {nErrors > 0 && <Tooltip content={Object.entries(e.errors!).slice(0, 4).map(([t, msg]) => `${t}: ${msg}`).join(" · ")}><span className="flex cursor-help items-center gap-1 font-medium text-bad"><AlertTriangle size={13} />{nErrors}</span></Tooltip>}
                    <span className="w-20 text-right">{e.mode === "api" ? brl4(e.cost_brl) : "—"}</span>
                  </span>
                  <ChevronRight size={16} className="hidden text-muted transition group-hover:translate-x-0.5 group-hover:text-ink md:block" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {list.length > shown && (
        <button onClick={() => setShown((s) => s + PAGE)} className="mt-3 w-full rounded-lg border border-line py-1.5 text-sm font-medium text-muted hover:bg-paper hover:text-ink">
          Mostrar mais ({list.length - shown})
        </button>
      )}
    </Card>
  );
}
