import { CircleCheck, CircleX, FlaskConical, Loader2, Play, Search, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type AppSettings, type Dataset, type Recommendation, type Run, type RunSummary, type ValidationReport } from "../api";
import { brl, brl4, pct, REC, FINDING_LABELS, providerLabel } from "../format";
import { InfoTip, Tooltip } from "./ui/Tooltip";
import { InfoBox } from "./ui/InfoBox";
import { Card, Kpi, Meter, SectionNav, type DeltaInfo } from "./ui/Panel";

interface Props {
  config: AppSettings;
  openCase: (runId: string, ticket: string) => void;
}

/** Validação em lote: roda um conjunto inteiro e mede o produto contra o gabarito, com a leitura de ciência de dados. */
export function ValidationView({ config, openCase }: Props) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [dataset, setDataset] = useState(config.validation.dataset);
  const [sample, setSample] = useState<number | null>(null);
  const [mode, setMode] = useState<"simulated" | "api">("simulated");
  const [batchMode, setBatchMode] = useState<"sync" | "batch">(config.batch_mode);
  const [noise, setNoise] = useState(0.15);
  const [execution, setRun] = useState<Run | null>(null);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const timer = useRef<number | null>(null);

  const loadHistory = useCallback(() => api.validations().then(setHistory).catch(() => undefined), []);
  useEffect(() => {
    api.datasets().then(setDatasets);
    loadHistory().then(() => undefined);
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [loadHistory]);

  const open = useCallback(async (id: string) => {
    setError(null);
    try {
      setReport(await api.validation(id));
      setRun(await api.execution(id, true));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    if (!report && history.length && !execution) open(history[0].id);
  }, [history, report, execution, open]);

  const nDataset = datasets.find((c) => c.name === dataset)?.n ?? 0;
  const size = sample && sample < nDataset ? sample : nDataset;

  const run = async () => {
    setError(null);
    setReport(null);
    try {
      const label = `${datasets.find((c) => c.name === dataset)?.label.split(" (")[0] ?? dataset}${sample && sample < nDataset ? `, amostra ${sample}` : ""}${mode === "simulated" ? `, ruído ${Math.round(noise * 100)}%` : ""}`;
      const ex = await api.run({ dataset, sample: sample && sample < nDataset ? sample : null, mode, batch_mode: batchMode, phase: 2,
        simulated_noise: mode === "simulated" ? noise : 0, label });
      setRun(ex);
      setStartedAt(Date.now());
      if (timer.current) window.clearInterval(timer.current);
      timer.current = window.setInterval(async () => {
        const e = await api.execution(ex.id, true);
        setRun(e);
        if (e.status === "completed") {
          window.clearInterval(timer.current!);
          setTimeout(async () => {
            try { setReport(await api.validation(ex.id)); } catch (er) { setError((er as Error).message); }
            loadHistory();
          }, 300);
        }
      }, 800);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const total = execution ? Object.keys(execution.tickets).length : 0;
  const done = execution ? Object.values(execution.tickets).filter((c) => c.status === "done" || c.status === "error").length : 0;
  const failed = execution ? Object.values(execution.tickets).filter((c) => c.status === "error").length : 0;
  const running = execution?.status === "running";
  const eta = running && startedAt && done > 0 ? Math.round(((Date.now() - startedAt) / done) * (total - done) / 1000) : null;

  // estimativa de custo na API a partir da última rodada paga
  const lastApi = history.find((h) => h.mode === "api" && h.tickets.length);
  const perTicket = lastApi ? lastApi.cost_brl / lastApi.tickets.length : null;

  // a rodada aberta e a anterior a ela, para as variações
  const idx = execution ? history.findIndex((h) => h.id === execution.id) : -1;
  const prev = idx >= 0 ? history[idx + 1] ?? null : null;

  return (
    <div className="mx-auto max-w-[1240px] space-y-6 px-6 py-6">
      <div>
        <h2 className="largo text-[28px] font-bold">Validação em lote</h2>
        <p className="text-sm text-muted">Roda um conjunto de chamados com gabarito e mede o Atest.AI como um modelo: concordância, erros por tipo, calibração do score e custo.</p>
      </div>

      <InfoBox id="validacao" title="Como ler esta tela">
        1. Configure e rode uma validação. 2. Veja se o <b>portão de qualidade</b> passou. 3. Clique na matriz de confusão ou num tipo de apontamento para filtrar os <b>casos divergentes</b> e abrir o parecer de cada um.
        Passe o mouse nos ícones <b>(i)</b> para entender cada métrica.
      </InfoBox>

      <section data-tour="val-config" className="rounded-xl border border-line bg-sheet p-5">
        <div className="grid gap-5 lg:grid-cols-[1fr_auto]">
          <div className="grid gap-4 text-sm sm:grid-cols-2 xl:grid-cols-4">
            <label>
              <span className="mb-1 block font-medium">Conjunto</span>
              <select value={dataset} onChange={(e) => { setDataset(e.target.value); setSample(null); }} disabled={running} className="w-full rounded-md border border-line bg-sheet px-2 py-1.5">
                {datasets.map((c) => <option key={c.name} value={c.name}>{c.label.split(" (")[0]} ({c.n})</option>)}
              </select>
            </label>
            <label>
              <span className="mb-1 flex justify-between font-medium"><span>Amostra</span><span className="tabular-nums text-muted">{size === nDataset ? `todos os ${nDataset}` : `${size} de ${nDataset}`}</span></span>
              <input type="range" min={5} max={Math.max(5, nDataset)} step={1} value={sample ?? nDataset} disabled={running} onChange={(e) => setSample(Number(e.target.value))}
                className="w-full accent-[var(--color-blueprint)]" />
              <span className="flex gap-1.5 text-[12px]">
                {[10, 30].filter((v) => v < nDataset).map((v) => (
                  <button key={v} type="button" onClick={() => setSample(v)} className={`rounded px-1.5 ${size === v ? "bg-blueprint-soft font-medium text-blueprint" : "text-muted hover:text-ink"}`}>{v}</button>
                ))}
                <button type="button" onClick={() => setSample(null)} className={`rounded px-1.5 ${size === nDataset ? "bg-blueprint-soft font-medium text-blueprint" : "text-muted hover:text-ink"}`}>todos</button>
              </span>
            </label>
            <fieldset>
              <legend className="mb-1 flex items-center gap-1 font-medium">Modo <InfoTip term="mode" /></legend>
              <div className="flex rounded-lg bg-paper p-0.5">
                {(["simulated", "api"] as const).map((m) => (
                  <Tooltip key={m} className="flex flex-1" content={m === "api" && !config.api_available ? `Sem chave para: ${config.missing_keys.join(", ")}` : m === "api" ? "Chama o modelo de verdade: mede a qualidade real e gera custo" : "Sem custo: mostra o fluxo e as métricas com erro simulado"}>
                    <button type="button" disabled={running || (m === "api" && !config.api_available)} onClick={() => setMode(m)}
                      className={`flex-1 rounded-md px-3 py-1 ${mode === m ? "bg-sheet font-semibold shadow-sm" : "text-muted hover:text-ink"} disabled:pointer-events-none disabled:opacity-40`}>
                      {m === "simulated" ? "Simulado" : `API (${config.providers.map(providerLabel).join(", ")})`}
                    </button>
                  </Tooltip>
                ))}
              </div>
            </fieldset>
            {mode === "simulated" ? (
              <label>
                <span className="mb-1 flex items-center gap-1 font-medium">Erro simulado: {Math.round(noise * 100)}% <InfoTip term="noise" /></span>
                <input type="range" min={0} max={0.4} step={0.05} value={noise} disabled={running} onChange={(e) => setNoise(Number(e.target.value))} className="w-full accent-[var(--color-blueprint)]" />
                <span className={`text-[12px] ${noise === 0 ? "font-medium text-warn" : "text-muted"}`}>
                  {noise === 0 ? "Com 0%, o simulador devolve o gabarito: tudo dá 100%." : "Acima de 0%, o simulador erra como um modelo real."}
                </span>
              </label>
            ) : (
              <fieldset>
                <legend className="mb-1 flex items-center gap-1 font-medium">Envio <InfoTip term="batch" /></legend>
                <div className="flex rounded-lg bg-paper p-0.5">
                  {(["sync", "batch"] as const).map((t) => (
                    <button key={t} type="button" disabled={running} onClick={() => setBatchMode(t)}
                      className={`flex-1 rounded-md px-3 py-1 ${batchMode === t ? "bg-sheet font-semibold shadow-sm" : "text-muted hover:text-ink"}`}>
                      {t === "sync" ? "Síncrono" : "Lote −50%"}
                    </button>
                  ))}
                </div>
              </fieldset>
            )}
          </div>
          <div className="flex flex-col items-stretch justify-end gap-1.5 lg:items-end">
            <button data-tour="val-run" onClick={run} disabled={running || !nDataset}
              className="flex items-center justify-center gap-2 rounded-lg bg-blueprint px-5 py-2.5 font-semibold text-white transition-colors hover:bg-[#1d44a0] disabled:opacity-50">
              {running ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />} {running ? "Rodando…" : `Rodar ${size} chamados`}
            </button>
            <span className="text-[12px] text-muted">
              {mode === "simulated" ? "Sem custo de API" : perTicket !== null
                ? `Estimativa: ~${brl(perTicket * size * (batchMode === "batch" && lastApi?.batch_mode !== "batch" ? 0.5 : 1))}`
                : "Custo estimado aparece após a 1ª rodada na API"}
            </span>
          </div>
        </div>

        {execution && running && (
          <div className="mt-4 border-t border-line pt-4">
            <div className="mb-1 flex flex-wrap justify-between gap-2 text-sm">
              <span className="font-medium">{execution.label || execution.id}</span>
              <span className="tabular-nums text-muted">
                {done} de {total}{failed ? <span className="text-bad"> · {failed} com erro</span> : null}{eta !== null ? ` · ≈ ${eta < 60 ? `${eta} s` : `${Math.round(eta / 60)} min`} restantes` : ""}
              </span>
            </div>
            <Meter value={done} max={total || 1} color="var(--color-blueprint)" />
          </div>
        )}
        {error && <p className="mt-3 text-sm text-bad">{error}</p>}
      </section>

      {report ? <Report r={report} execution={execution} config={config} openCase={openCase} prev={prev} /> : running ? (
        <div className="flex items-center gap-3 rounded-xl border border-dashed border-line bg-sheet p-8 text-muted">
          <Loader2 className="shrink-0 animate-spin" /> Rodando a validação. O relatório aparece aqui assim que terminar.
        </div>
      ) : (
        <div className="flex items-center gap-3 rounded-xl border border-dashed border-line bg-sheet p-8 text-muted">
          <FlaskConical className="shrink-0" /> <span>Nenhum relatório ainda. Configure acima e clique em <b className="text-ink">Rodar</b>: no modo simulado leva poucos segundos e não tem custo.</span>
        </div>
      )}

      {history.length > 0 && <History history={history} current={execution?.id ?? null} open={open} config={config} />}
    </div>
  );
}

// ============================================================================ relatório
const gateFmt = (metric: string, v: number | null) => (v === null ? "—" : /erro/i.test(metric) ? `${v.toFixed(1)} pts` : /kappa/i.test(metric) ? v.toFixed(2) : pct(v, 1));

function Report({ r, execution, config, openCase, prev }: { r: ValidationReport; execution: Run | null; config: AppSettings; openCase: Props["openCase"]; prev: RunSummary | null }) {
  const pp = r.problem_catch;
  const api = execution?.mode === "api";
  const [pair, setPair] = useState<[Recommendation, Recommendation] | null>(null);
  const [kind, setKind] = useState<string | null>(null);
  const [q, setQ] = useState("");

  const vs = prev ? `a rodada anterior (${prev.label || prev.id})` : "";
  const pv = prev?.validation;
  const dPct = (now: number | null | undefined, before: number | null | undefined, better: "up" | "down" = "up"): DeltaInfo | null =>
    pv && now != null && before != null ? { value: 100 * (now - before), unit: "pp", better, vs } : null;

  const filtered = useMemo(() => r.mismatches.filter((d) =>
    (!pair || (d.expected === pair[0] && d.obtained === pair[1])) &&
    (!kind || d.missed.includes(kind) || d.extra.includes(kind)) &&
    (!q || `${d.ticket_id} ${d.category}`.toLowerCase().includes(q.toLowerCase()))), [r.mismatches, pair, kind, q]);
  const focusMismatches = () => document.getElementById("val-mismatches")?.scrollIntoView({ behavior: "smooth", block: "start" });

  const perfect = execution?.mode === "simulated" && execution.simulated_noise === 0;
  const problems = pp.tp + pp.fn, stops = pp.tp + pp.fp, goods = pp.tn + pp.fp;

  return (
    <div className="space-y-5">
      <SectionNav sections={[
        { id: "val-summary", label: "Resumo" },
        { id: "val-errors", label: "Onde erra" },
        { id: "val-findings", label: "Apontamentos" },
        { id: "val-catch", label: "Pegar problema" },
        { id: "val-mismatches", label: `Divergências (${r.mismatches.length})` },
        { id: "val-history", label: "Histórico" },
      ]} />

      <div id="val-summary" className="scroll-mt-16 space-y-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="largo text-xl font-bold">{execution?.label || execution?.id || "Relatório"}</h3>
          <span className="text-[13px] text-muted">
            {r.n} chamados com gabarito{r.no_ground_truth ? ` (+${r.no_ground_truth} sem)` : ""} · {execution?.mode === "api" ? `API${execution.batch_mode === "batch" ? " em lote" : ""}` : `simulado, ruído ${pct(execution?.simulated_noise ?? 0)}`}
            {execution?.created_at && ` · ${new Date(execution.created_at).toLocaleString("pt-BR")}`}
          </span>
        </div>

        {perfect && (
          <InfoBox tone="warn" title="Rodada com 0% de erro simulado">
            O simulador devolveu o próprio gabarito, então 100% em todas as métricas é o esperado e <b>não mede o modelo</b>. Para ver métricas realistas, aumente o erro simulado ou rode na API.
          </InfoBox>
        )}

        <section data-tour="val-gate" className={`rounded-xl border-2 p-4 ${r.gate_passed ? "border-ok/40 bg-[#eef7f1]" : "border-bad/40 bg-[#fbefed]"}`}>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <span className={`flex items-center gap-2 text-lg font-bold ${r.gate_passed ? "text-ok" : "text-bad"}`}>
              {r.gate_passed ? <CircleCheck /> : <CircleX />} Portão de qualidade {r.gate_passed ? "aprovado" : "reprovado"} <InfoTip term="gate" />
            </span>
            <span className="text-[12px] text-muted">configuração {execution?.signature || config.signature}</span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {r.gate.map((g) => {
              const lowerBetter = g.direction.includes("<");
              const isErr = /erro/i.test(g.metric);
              const max = isErr ? Math.max(g.limit * 2, g.value ?? 0, 1) : 1;
              return (
                <div key={g.metric} className="rounded-lg bg-sheet/80 p-3">
                  <div className="flex items-start justify-between gap-2 text-[13px]">
                    <span className="text-muted">{g.metric}</span>
                    {g.passed ? <CircleCheck size={16} className="shrink-0 text-ok" /> : <CircleX size={16} className="shrink-0 text-bad" />}
                  </div>
                  <div className={`largo mt-0.5 text-lg font-bold tabular-nums ${g.passed ? "" : "text-bad"}`}>{gateFmt(g.metric, g.value)}</div>
                  <div className="mt-1.5"><Meter value={g.value} max={max} limit={g.limit} color={g.passed ? "var(--color-ok)" : "var(--color-bad)"} height={6} /></div>
                  <div className="mt-1 text-[11px] text-muted">limite {lowerBetter ? "até" : "mínimo"} {gateFmt(g.metric, g.limit)}</div>
                </div>
              );
            })}
          </div>
        </section>

        <section data-tour="val-kpis" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <Kpi help={<InfoTip term="accuracy" />} label="Acurácia da recomendação" value={pct(r.accuracy.value, 1)} delta={dPct(r.accuracy.value, pv?.accuracy.value)}
            sub={<>IC 95%: {pct(r.accuracy.ci_low)} a {pct(r.accuracy.ci_high)}<br />{Math.round(r.accuracy.value * r.n)} de {r.n} chamados</>} />
          <Kpi help={<InfoTip term="kappa" />} label="Kappa de Cohen" value={r.kappa?.toFixed(2) ?? "—"}
            delta={pv && r.kappa !== null && pv.kappa !== null ? { value: r.kappa - pv.kappa, unit: "", better: "up", vs } : null}
            sub={<>{kappaLabel(r.kappa)}<br />acurácia balanceada {pct(r.balanced_accuracy, 1)}</>} />
          <Kpi help={<InfoTip term="catch" />} label="Pegar problema" value={pct(pp.f1, 1)} badge={<span className="rounded bg-paper px-1.5 text-[11px] font-semibold text-muted">F1</span>}
            delta={dPct(pp.f1, pv?.problem_catch_f1)}
            sub={<>cobertura (recall) <b className="text-ink">{pct(pp.recall)}</b>: pegou {pp.tp} de {problems}<br />precisão <b className="text-ink">{pct(pp.precision)}</b>: {pp.tp} de {stops} paradas certas</>} />
          <Kpi help={<InfoTip term="f1" />} label="Apontamentos" value={pct(r.findings_micro.f1, 1)} badge={<span className="rounded bg-paper px-1.5 text-[11px] font-semibold text-muted">F1</span>}
            delta={dPct(r.findings_micro.f1, pv?.finding_f1)}
            sub={<>cobertura {pct(r.findings_micro.recall)} · precisão {pct(r.findings_micro.precision)}<br />macro F1 {pct(r.finding_macro_f1, 1)}</>} />
          <Kpi help={<InfoTip term="mae" />} label="Erro médio do score" value={r.score_mae === null ? "—" : `${r.score_mae.toFixed(1)} pts`}
            delta={pv && r.score_mae !== null && pv.score_mae !== null ? { value: r.score_mae - pv.score_mae, unit: "pts", better: "down", vs } : null}
            sub={<>viés {r.score_bias === null ? "—" : `${r.score_bias > 0 ? "+" : ""}${r.score_bias.toFixed(1)}`} <InfoTip term="bias" size={12} /> · r {r.score_pearson?.toFixed(2) ?? "—"} <InfoTip term="pearson" size={12} /></>} />
          <Kpi help={<InfoTip term="p95" />} label="Custo por chamado" value={api ? brl4(r.operations.avg_cost_brl) : "—"}
            sub={api ? <>total {brl4(r.operations.total_cost_brl)}<br />latência p95 {r.operations.latency_p95_s?.toFixed(1) ?? "—"} s</> : "rodada simulada, sem custo de API"} />
        </section>
      </div>

      <section id="val-errors" className="grid scroll-mt-16 gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <Card tour="val-matrix" title="Matriz de confusão da recomendação"
          sub="Linhas: gabarito. Colunas: Atest.AI. A diagonal são os acertos. Clique numa célula fora da diagonal para ver os casos.">
          <ConfusionMatrix r={r} selected={pair} onPick={(p) => { setPair(p); setKind(null); focusMismatches(); }} />
        </Card>
        <Card title="Score: gabarito × Atest.AI" sub="Cada ponto é um chamado com score. Na diagonal, o score bate; abaixo dela, o Atest.AI foi mais rigoroso. As linhas tracejadas são as faixas 70 e 85.">
          <Scatter r={r} />
        </Card>
      </section>

      <section id="val-findings" className="grid scroll-mt-16 gap-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <Card help={<><InfoTip term="precision" /><InfoTip term="recall" /></>} title="Apontamentos por tipo"
          sub="Ordenados do pior F1 para o melhor. Clique num tipo para ver os casos em que ele faltou ou sobrou.">
          <FindingsTable r={r} selected={kind} onPick={(k) => { setKind(k); setPair(null); focusMismatches(); }} />
        </Card>
        <Card title="Acurácia por categoria" sub={<>Onde o produto erra mais: candidatos a ajuste de prompt ou checklist. A linha marca o mínimo do portão ({pct(config.validation.accuracy_min)}).</>}>
          <Bars items={[...r.by_category].sort((a, b) => a.accuracy - b.accuracy).map((c) => ({ label: categoryLabel(c.name, config), value: c.accuracy, extra: `${c.hits}/${c.n}` }))} limit={config.validation.accuracy_min} />
        </Card>
      </section>

      <section id="val-catch" className="grid scroll-mt-16 gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2" help={<InfoTip term="catch" />} title="Pegar problema: o chamado deveria parar?"
          sub="Positivo = devolver, trava, checklist ou análise detalhada. O F1 do resumo combina as duas primeiras métricas abaixo.">
          <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
            <div>
              <div className="mb-1 grid grid-cols-[70px_1fr_1fr] gap-2 text-center text-[11px] font-medium uppercase tracking-wide text-muted">
                <span /><span>Atest.AI parou</span><span>Atest.AI seguiu</span>
              </div>
              <div className="grid grid-cols-[70px_1fr_1fr] gap-2 text-center text-sm">
                <span className="flex items-center justify-end text-right text-[11px] font-medium uppercase tracking-wide text-muted">Devia parar</span>
                <Tooltip className="block" content="Verdadeiros positivos (VP): problema real que o Atest.AI segurou."><Cell label="VP · pegou" value={pp.tp} strong /></Tooltip>
                <Tooltip className="block" content="Falsos negativos (FN): problema real que passou. É o erro mais caro."><Cell label="FN · deixou passar" value={pp.fn} alert /></Tooltip>
                <span className="flex items-center justify-end text-right text-[11px] font-medium uppercase tracking-wide text-muted">Devia seguir</span>
                <Tooltip className="block" content="Falsos positivos (FP): segurou um chamado que estava bom (retrabalho)."><Cell label="FP · parou à toa" value={pp.fp} warn /></Tooltip>
                <Tooltip className="block" content="Verdadeiros negativos (VN): chamado bom que seguiu."><Cell label="VN · seguiu certo" value={pp.tn} strong /></Tooltip>
              </div>
            </div>
            <dl className="space-y-3 text-sm">
              <Rate term="recall" label="Cobertura (recall)" v={pp.recall} formula="VP ÷ (VP + FN)" detail={`pegou ${pp.tp} de ${problems} problemas reais`} color="#eb6834" />
              <Rate term="precision" label="Precisão" v={pp.precision} formula="VP ÷ (VP + FP)" detail={`${pp.tp} de ${stops} paradas estavam certas`} color="#2a78d6" />
              <Rate term="specificity" label="Especificidade" v={pp.specificity} formula="VN ÷ (VN + FP)" detail={`${pp.tn} de ${goods} chamados bons seguiram`} color="#7a97d8" />
              <Rate term="f1" label="F1" v={pp.f1} formula="2·P·C ÷ (P + C)" detail={r.problem_catch_f1_ci ? `IC 95% ${pct(r.problem_catch_f1_ci.ci_low)} a ${pct(r.problem_catch_f1_ci.ci_high)}` : "equilíbrio entre precisão e cobertura"} color="#1baf7a" />
            </dl>
          </div>
        </Card>
        <div className="space-y-5">
          <Card help={<InfoTip term="amount" />} title="Valor potencial divergente" sub="Soma do que o gabarito e o Atest.AI apontaram como potencialmente divergente.">
            <AmountCompare expected={r.expected_amount_at_issue} obtained={r.obtained_amount_at_issue} />
            <dl className="mt-3 space-y-1 text-[13px] text-muted">
              <div className="flex justify-between"><dt>Erro médio por chamado</dt><dd className="tabular-nums">{r.amount_at_issue_mae === null ? "—" : brl(r.amount_at_issue_mae)}</dd></div>
              <div className="flex justify-between"><dt>Checklist correto</dt><dd className="tabular-nums">{pct(r.checklist_accuracy, 1)}</dd></div>
            </dl>
          </Card>
          <Card title="Operação da rodada" sub={api ? "Tempo e custo." : "Rodada simulada: tempo do simulador, sem custo de API."}>
            <dl className="space-y-1.5 text-sm tabular-nums">
              <div className="flex justify-between"><dt>Latência p50 / p95</dt><dd>{r.operations.latency_p50_s?.toFixed(1) ?? "—"} s / {r.operations.latency_p95_s?.toFixed(1) ?? "—"} s</dd></div>
              {api && <div className="flex justify-between"><dt>Custo médio / p95</dt><dd>{brl4(r.operations.avg_cost_brl)} / {brl4(r.operations.p95_cost_brl)}</dd></div>}
              <div className="flex justify-between text-muted"><dt>Tokens médios (entrada / saída)</dt><dd>{Math.round(r.operations.avg_input_tokens).toLocaleString("pt-BR")} / {Math.round(r.operations.avg_output_tokens).toLocaleString("pt-BR")}</dd></div>
            </dl>
          </Card>
        </div>
      </section>

      <Card id="val-mismatches" tour="val-mismatches" title={`Casos divergentes (${filtered.length}${filtered.length !== r.mismatches.length ? ` de ${r.mismatches.length}` : ""})`}
        sub="Clique num caso para abrir o parecer na Análise e ver onde o modelo errou."
        aside={r.mismatches.length > 0 && (
          <label className="flex items-center gap-1.5 rounded-lg border border-line px-2 py-1 text-sm focus-within:border-blueprint">
            <Search size={14} className="text-muted" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Chamado ou categoria" className="w-40 bg-transparent outline-none" />
          </label>
        )}>
        {(pair || kind) && (
          <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted">Filtro:</span>
            <span className="flex items-center gap-1.5 rounded-full bg-blueprint-soft py-0.5 pl-3 pr-1 text-blueprint">
              {pair ? <>Gabarito {REC[pair[0]].short} → Atest.AI {REC[pair[1]].short}</> : <>{FINDING_LABELS[kind!] ?? kind} faltou ou sobrou</>}
              <button onClick={() => { setPair(null); setKind(null); }} aria-label="Limpar filtro" className="rounded-full p-0.5 hover:bg-blueprint/10"><X size={13} /></button>
            </span>
          </div>
        )}
        {filtered.length ? (
          <ul className="divide-y divide-line/70 text-sm">
            {filtered.map((d) => (
              <li key={d.ticket_id}>
                <button onClick={() => execution && openCase(execution.id, d.ticket_id)} className="grid w-full grid-cols-[90px_1fr] gap-x-3 gap-y-1 rounded-md px-2 py-2 text-left hover:bg-paper/60 md:grid-cols-[90px_150px_260px_1fr]">
                  <span className="font-medium tabular-nums text-blueprint">{d.ticket_id}</span>
                  <span className="text-muted">{categoryLabel(d.category, config)}</span>
                  <span className="flex items-center gap-1.5"><Point r={d.expected} />{REC[d.expected].short} → <Point r={d.obtained} />{REC[d.obtained].short}
                    <span className="text-muted tabular-nums">({d.expected_score ?? "—"} → {d.obtained_score ?? "—"})</span></span>
                  <span className="col-span-2 flex flex-wrap gap-1 text-[12px] md:col-span-1">
                    {d.missed.map((t) => <span key={`m${t}`} className="rounded bg-[#f8e4e2] px-1.5 text-bad">faltou: {FINDING_LABELS[t] ?? t}</span>)}
                    {d.extra.map((t) => <span key={`e${t}`} className="rounded bg-[#fdf1dc] px-1.5 text-warn">a mais: {FINDING_LABELS[t] ?? t}</span>)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : <p className="text-sm text-muted">{r.mismatches.length ? "Nenhum caso com este filtro." : "Nenhuma divergência nesta rodada."}</p>}
      </Card>
    </div>
  );
}

const kappaLabel = (k: number | null) => k === null ? "—" : k >= 0.8 ? "concordância muito boa" : k >= 0.6 ? "concordância boa" : k >= 0.4 ? "concordância moderada" : "concordância fraca";

function Rate({ term, label, v, formula, detail, color }: { term: "recall" | "precision" | "specificity" | "f1"; label: string; v: number | null; formula: string; detail: string; color: string }) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <dt className="flex items-center gap-1 font-medium">{label} <InfoTip term={term} size={13} /></dt>
        <dd className="font-semibold tabular-nums">{pct(v, 1)}</dd>
      </div>
      <Meter value={v} color={color} height={6} />
      <div className="mt-0.5 flex justify-between gap-2 text-[12px] text-muted"><span>{detail}</span><span className="font-mono text-[11px]">{formula}</span></div>
    </div>
  );
}

function AmountCompare({ expected, obtained }: { expected: number; obtained: number }) {
  const max = Math.max(expected, obtained, 1);
  const diff = obtained - expected;
  return (
    <div className="space-y-2 text-sm">
      {[["Gabarito", expected, "#7a97d8"], ["Atest.AI", obtained, "#2a78d6"]].map(([l, v, c]) => (
        <div key={l as string}>
          <div className="flex justify-between"><span>{l}</span><b className="tabular-nums">{brl(v as number)}</b></div>
          <Meter value={v as number} max={max} color={c as string} height={6} />
        </div>
      ))}
      {expected > 0 && (
        <p className="text-[12px] text-muted">
          O Atest.AI apontou {Math.abs(diff) < 1 ? "o mesmo valor" : `${brl(Math.abs(diff))} ${diff > 0 ? "a mais" : "a menos"} (${Math.round((100 * Math.abs(diff)) / expected)}%)`} que o gabarito.
        </p>
      )}
    </div>
  );
}

function Cell({ label, value, strong, alert, warn }: { label: string; value: number; strong?: boolean; alert?: boolean; warn?: boolean }) {
  return (
    <div className={`rounded-lg p-3 ${alert && value ? "bg-[#fbefed]" : warn && value ? "bg-[#fdf6e4]" : strong ? "bg-blueprint-soft" : "bg-paper"}`}>
      <div className={`largo text-2xl font-bold tabular-nums ${alert && value ? "text-bad" : warn && value ? "text-warn" : ""}`}>{value}</div>
      <div className="text-[12px] text-muted">{label}</div>
    </div>
  );
}

function Point({ r }: { r: keyof typeof REC }) {
  return <i className="inline-block size-2.5 shrink-0 rounded-full" style={{ background: REC[r].mark }} />;
}

const categoryLabel = (v: string, c: AppSettings) => c.categories.find((x) => x.value === v)?.label ?? v;

/** escala sequencial de um só tom (azul), do claro ao escuro */
function blue(t: number): string {
  const a = [238, 244, 252], b = [24, 74, 150];
  return `rgb(${a.map((x, i) => Math.round(x + (b[i] - x) * t)).join(",")})`;
}

function ConfusionMatrix({ r, selected, onPick }: { r: ValidationReport; selected: [Recommendation, Recommendation] | null; onPick: (p: [Recommendation, Recommendation]) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate text-center text-[13px]" style={{ borderSpacing: 2 }}>
        <thead>
          <tr>
            <th className="pb-1 text-right text-[11px] font-medium uppercase tracking-wide text-muted">gabarito ↓ · Atest.AI →</th>
            {r.classes.map((c) => <th key={c} className="px-1 pb-1 font-medium text-muted"><Point r={c} /> {REC[c].short}</th>)}
          </tr>
        </thead>
        <tbody>
          {r.matrix.map((row, i) => {
            const total = row.reduce((a, b) => a + b, 0);
            return (
              <tr key={r.classes[i]}>
                <th className="whitespace-nowrap pr-2 text-right font-medium text-muted"><Point r={r.classes[i]} /> {REC[r.classes[i]].short} <span className="font-normal">({total})</span></th>
                {row.map((v, j) => {
                  const t = total ? v / total : 0;
                  const err = i !== j && v > 0;
                  const sel = selected && selected[0] === r.classes[i] && selected[1] === r.classes[j];
                  const cell = (
                    <span className={`flex h-11 min-w-12 items-center justify-center rounded tabular-nums ${i === j ? "font-bold" : ""} ${err ? "cursor-pointer hover:ring-2 hover:ring-bad/60" : ""} ${sel ? "ring-2 ring-bad" : ""}`}
                      style={{ background: v ? (i === j ? blue(0.12 + 0.88 * t) : `rgb(227 73 72 / ${0.15 + 0.6 * t})`) : "var(--color-paper)", color: i === j && t > 0.5 ? "white" : "var(--color-ink)" }}>
                      {v || ""}
                    </span>
                  );
                  return (
                    <td key={j} className="p-0">
                      <Tooltip className="block" content={`Gabarito ${REC[r.classes[i]].label} → Atest.AI ${REC[r.classes[j]].label}: ${v} (${pct(t)} da linha)${err ? ". Clique para ver os casos." : ""}`}>
                        {err ? <button type="button" className="block w-full" onClick={() => onPick([r.classes[i], r.classes[j]])}>{cell}</button> : cell}
                      </Tooltip>
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 flex flex-wrap gap-x-4 text-[12px] text-muted">
        <span className="flex items-center gap-1.5"><i className="h-2.5 w-4 rounded-sm" style={{ background: blue(0.7) }} /> acertos</span>
        <span className="flex items-center gap-1.5"><i className="h-2.5 w-4 rounded-sm" style={{ background: "rgb(227 73 72 / 0.5)" }} /> erros (clicáveis)</span>
      </p>
    </div>
  );
}

function Scatter({ r }: { r: ValidationReport }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 420, H = 300, m = { l: 40, r: 12, t: 10, b: 34 };
  const x = (v: number) => m.l + (v / 100) * (W - m.l - m.r);
  const y = (v: number) => H - m.b - (v / 100) * (H - m.t - m.b);
  // pontos sobrepostos (mesmo par de scores) viram um círculo maior
  const groups = new Map<string, { e: number; o: number; ids: string[] }>();
  r.score_pairs.forEach((p) => {
    const k = `${p.expected}-${p.obtained}`;
    const g = groups.get(k) ?? { e: p.expected, o: p.obtained, ids: [] };
    g.ids.push(p.ticket_id);
    groups.set(k, g);
  });
  const items_list = [...groups.values()];
  const h = hover !== null ? items_list[hover] : null;
  if (!r.score_pairs.length) return <p className="text-sm text-muted">Nenhum chamado com score nesta rodada.</p>;
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Dispersão do score esperado pelo obtido">
        {[0, 25, 50, 70, 85, 100].map((v) => (
          <g key={v}>
            <line x1={x(0)} x2={x(100)} y1={y(v)} y2={y(v)} stroke="#d5dde7" strokeWidth={v === 70 || v === 85 ? 1 : 0.5} strokeDasharray={v === 70 || v === 85 ? "3 3" : undefined} />
            <text x={m.l - 6} y={y(v) + 4} textAnchor="end" fontSize="11" fill="#5e6b7e">{v}</text>
            <text x={x(v)} y={H - m.b + 16} textAnchor="middle" fontSize="11" fill="#5e6b7e">{v}</text>
          </g>
        ))}
        <line x1={x(0)} y1={y(0)} x2={x(100)} y2={y(100)} stroke="#12233f" strokeOpacity={0.35} strokeWidth={1.5} />
        <text x={x(50)} y={H - 2} textAnchor="middle" fontSize="11" fill="#5e6b7e">score do gabarito</text>
        <text x={10} y={y(50)} textAnchor="middle" fontSize="11" fill="#5e6b7e" transform={`rotate(-90 10 ${y(50)})`}>score do Atest.AI</text>
        {items_list.map((g, i) => (
          <circle key={i} cx={x(g.e)} cy={y(g.o)} r={Math.min(4 + 2.2 * Math.sqrt(g.ids.length - 1) * 2, 14)} fill={g.e === g.o ? "#2a78d6" : "#eb6834"} fillOpacity={g.e === g.o ? 0.55 : 0.85}
            stroke="white" strokeWidth={2} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} className="cursor-pointer" />
        ))}
        {items_list.map((g, i) => (
          <circle key={`h${i}`} cx={x(g.e)} cy={y(g.o)} r={16} fill="transparent" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
        ))}
      </svg>
      {h && (
        <div className="pointer-events-none absolute rounded-md bg-ink px-2.5 py-1.5 text-[12px] text-white shadow"
          style={{ left: `${(x(h.e) / W) * 100}%`, top: `${(y(h.o) / H) * 100}%`, transform: "translate(-50%, -120%)" }}>
          gabarito {h.e} → Atest.AI {h.o} · {h.ids.length} chamado(s)<br />{h.ids.slice(0, 4).join(", ")}{h.ids.length > 4 ? "…" : ""}
        </div>
      )}
      <p className="mt-1 flex gap-4 text-[12px] text-muted">
        <span className="flex items-center gap-1.5"><i className="size-2.5 rounded-full bg-[#2a78d6] opacity-60" /> score igual</span>
        <span className="flex items-center gap-1.5"><i className="size-2.5 rounded-full bg-[#eb6834]" /> score diferente</span>
      </p>
    </div>
  );
}

const SERIES = [{ k: "recall", label: "Cobertura (recall)", color: "#eb6834" }, { k: "precision", label: "Precisão", color: "#2a78d6" }, { k: "f1", label: "F1", color: "#1baf7a" }] as const;

function FindingsTable({ r, selected, onPick }: { r: ValidationReport; selected: string | null; onPick: (k: string) => void }) {
  const rows = [...r.findings].sort((a, b) => (a.f1 ?? -1) - (b.f1 ?? -1));
  const worst = rows.find((a) => a.f1 !== null && a.f1 < 1);
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-4 text-[12px] text-muted">
        {SERIES.map((s) => <span key={s.k} className="flex items-center gap-1.5"><i className="h-2 w-3 rounded-sm" style={{ background: s.color }} />{s.label}</span>)}
      </div>
      <table className="w-full text-[13px]">
        <thead className="text-left text-muted">
          <tr>
            <th className="pb-1 font-medium">Tipo</th>
            <th className="pb-1 text-right font-medium"><Tooltip content="Quantos casos reais deste tipo existem no gabarito"><span className="cursor-help">Suporte</span></Tooltip></th>
            <th className="pb-1 text-right font-medium"><Tooltip content="VP: acertou · FP: apontou sem existir · FN: deixou de apontar"><span className="cursor-help">VP / FP / FN</span></Tooltip></th>
            <th className="w-[42%] pb-1 font-medium" />
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => {
            const clickable = a.fp + a.fn > 0;
            return (
              <tr key={a.kind} onClick={clickable ? () => onPick(a.kind) : undefined}
                className={`border-t border-line/60 ${clickable ? "cursor-pointer hover:bg-paper/60" : ""} ${selected === a.kind ? "bg-blueprint-soft" : ""}`}>
                <td className="py-1.5 pr-2">
                  {FINDING_LABELS[a.kind] ?? a.kind}
                  {worst === a && <span className="ml-1.5 rounded bg-[#f8e4e2] px-1 text-[10px] font-semibold uppercase text-bad">pior</span>}
                </td>
                <td className="py-1.5 text-right tabular-nums">{a.support}</td>
                <td className="py-1.5 text-right tabular-nums text-muted">{a.tp} / <span className={a.fp ? "text-warn" : ""}>{a.fp}</span> / <span className={a.fn ? "text-bad" : ""}>{a.fn}</span></td>
                <td className="py-1.5 pl-3">
                  <div className="space-y-[2px]">
                    {SERIES.map((s) => {
                      const v = a[s.k];
                      return (
                        <div key={s.k} className="flex items-center gap-2">
                          <div className="h-[5px] flex-1 rounded-full bg-paper">
                            {v !== null && <div className="h-[5px] rounded-full" style={{ width: `${Math.max(2, 100 * v)}%`, background: s.color }} />}
                          </div>
                          <span className="w-9 text-right text-[11px] tabular-nums text-muted">{pct(v)}</span>
                        </div>
                      );
                    })}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Bars({ items, limit }: { items: { label: string; value: number; extra: string }[]; limit: number }) {
  return (
    <ul className="space-y-2.5 text-[13px]">
      {items.map((i) => {
        const below = i.value < limit;
        return (
          <li key={i.label} className="grid grid-cols-[120px_1fr_76px] items-center gap-2">
            <span className="truncate" title={i.label}>{i.label}</span>
            <Meter value={i.value} color={below ? "#e34948" : "#2a78d6"} limit={limit} height={10} />
            <span className="text-right tabular-nums"><span className={below ? "font-semibold text-bad" : ""}>{pct(i.value)}</span> <span className="text-muted">{i.extra}</span></span>
          </li>
        );
      })}
    </ul>
  );
}

// ============================================================================ histórico
function History({ history, current, open, config }: { history: RunSummary[]; current: string | null; open: (id: string) => void; config: AppSettings }) {
  const runs = history.filter((h) => h.validation);
  const chrono = [...runs].reverse().slice(-15);
  const W = 640, H = 150, m = { l: 34, r: 10, t: 10, b: 20 };
  const x = (i: number) => m.l + (chrono.length < 2 ? (W - m.l - m.r) / 2 : (i * (W - m.l - m.r)) / (chrono.length - 1));
  const y = (v: number) => H - m.b - v * (H - m.t - m.b);
  const lines = [
    { k: "acc", label: "Acurácia", color: "#2a78d6", get: (h: RunSummary) => h.validation!.accuracy.value },
    { k: "f1", label: "F1 apontamentos", color: "#eb6834", get: (h: RunSummary) => h.validation!.finding_f1 },
    { k: "catch", label: "F1 pegar problema", color: "#1baf7a", get: (h: RunSummary) => h.validation!.problem_catch_f1 },
  ];
  return (
    <Card id="val-history" title="Histórico de rodadas" sub="Clique numa rodada (no gráfico ou na tabela) para abrir o relatório dela.">
      {chrono.length > 1 && (
        <div className="mb-4">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Tendência das métricas por rodada">
            {[0, 0.5, 1].map((v) => (
              <g key={v}>
                <line x1={m.l} x2={W - m.r} y1={y(v)} y2={y(v)} stroke="#d5dde7" strokeWidth={0.6} />
                <text x={m.l - 6} y={y(v) + 4} textAnchor="end" fontSize="10" fill="#5e6b7e">{v * 100}%</text>
              </g>
            ))}
            <line x1={m.l} x2={W - m.r} y1={y(config.validation.accuracy_min)} y2={y(config.validation.accuracy_min)} stroke="#12233f" strokeOpacity={0.5} strokeDasharray="4 3" />
            <text x={W - m.r} y={y(config.validation.accuracy_min) - 4} textAnchor="end" fontSize="10" fill="#5e6b7e">mínimo de acurácia</text>
            {lines.map((l) => {
              const pts = chrono.map((h, i) => ({ i, v: l.get(h) })).filter((p) => p.v !== null) as { i: number; v: number }[];
              return (
                <g key={l.k}>
                  <polyline fill="none" stroke={l.color} strokeWidth={2} points={pts.map((p) => `${x(p.i)},${y(p.v)}`).join(" ")} />
                  {pts.map((p) => (
                    <circle key={p.i} cx={x(p.i)} cy={y(p.v)} r={chrono[p.i].id === current ? 5 : 3.5} fill={l.color} stroke="white" strokeWidth={1.5} className="cursor-pointer" onClick={() => open(chrono[p.i].id)}>
                      <title>{`${chrono[p.i].label || chrono[p.i].id}: ${l.label} ${pct(p.v, 1)}`}</title>
                    </circle>
                  ))}
                </g>
              );
            })}
          </svg>
          <div className="flex flex-wrap gap-4 text-[12px] text-muted">
            {lines.map((l) => <span key={l.k} className="flex items-center gap-1.5"><i className="h-0.5 w-4" style={{ background: l.color }} />{l.label}</span>)}
          </div>
        </div>
      )}
      <div className="-mx-5 overflow-x-auto">
        <table className="w-full min-w-[900px] text-sm">
          <thead className="text-left text-[13px] text-muted">
            <tr>
              <th className="px-5 py-2 font-medium">Rodada</th><th className="px-3 py-2 font-medium">Configuração</th>
              <th className="px-3 py-2 text-right font-medium">n</th><th className="px-3 py-2 text-right font-medium">Acurácia</th>
              <th className="px-3 py-2 text-right font-medium">Kappa</th><th className="px-3 py-2 text-right font-medium">F1 apontamentos</th>
              <th className="px-3 py-2 text-right font-medium">Erro do score</th><th className="px-3 py-2 text-right font-medium">Custo</th>
              <th className="px-5 py-2 font-medium">Portão</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {runs.map((h) => (
              <tr key={h.id} onClick={() => open(h.id)} className={`cursor-pointer border-t border-line/70 hover:bg-paper/60 ${current === h.id ? "bg-blueprint-soft" : ""}`}>
                <td className="px-5 py-2">
                  <div className="flex items-center gap-2 font-medium">{h.label || h.id}{current === h.id && <span className="rounded bg-blueprint px-1.5 text-[10px] font-semibold uppercase text-white">aberta</span>}</div>
                  <div className="text-[12px] text-muted">{new Date(h.created_at).toLocaleString("pt-BR")}</div>
                </td>
                <td className="px-3 py-2 text-[12px] text-muted">{h.mode === "api" ? `API${h.batch_mode === "batch" ? " em lote" : ""}` : "simulado"} · {h.signature}</td>
                <td className="px-3 py-2 text-right">{h.validation!.n}</td>
                <td className={`px-3 py-2 text-right ${h.validation!.accuracy.value < config.validation.accuracy_min ? "text-bad" : ""}`}>{pct(h.validation!.accuracy.value, 1)}</td>
                <td className="px-3 py-2 text-right">{h.validation!.kappa?.toFixed(2) ?? "—"}</td>
                <td className="px-3 py-2 text-right">{pct(h.validation!.finding_f1, 1)}</td>
                <td className="px-3 py-2 text-right">{h.validation!.score_mae?.toFixed(1) ?? "—"}</td>
                <td className="px-3 py-2 text-right">{h.mode === "api" ? brl4(h.cost_brl) : "—"}</td>
                <td className="px-5 py-2">
                  {h.validation!.gate_passed
                    ? <span className="inline-flex items-center gap-1 rounded-full bg-[#e3f2ea] px-2 py-0.5 text-[12px] font-semibold text-ok"><CircleCheck size={13} /> Aprovado</span>
                    : <span className="inline-flex items-center gap-1 rounded-full bg-[#f8e4e2] px-2 py-0.5 text-[12px] font-semibold text-bad"><CircleX size={13} /> Reprovado</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
