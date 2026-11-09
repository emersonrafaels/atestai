import { BookOpen, ClipboardCheck, Compass, Cpu, Download, HelpCircle, Images, Inbox, Loader2, Play, Plus, Receipt, RotateCcw, Trash2, X, type LucideIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type TicketDetail, type TicketSummary, type AppSettings, type Dataset, type Run, type Assessment, type Recommendation } from "./api";
import { LlmCallsTab } from "./components/LlmCallsTab";
import { TicketInputTab } from "./components/TicketInputTab";
import { PhotosTab } from "./components/PhotosTab";
import { QuoteTab } from "./components/QuoteTab";
import { AssessmentTab } from "./components/AssessmentTab";
import { StageProgress } from "./components/StageProgress";
import { TicketList } from "./components/TicketList";
import { OperationsView } from "./components/OperationsView";
import { NewTicket } from "./components/NewTicket";
import { ValidationView } from "./components/ValidationView";
import { brl4, REC, DEFAULT_RUBRIC } from "./format";
import { Tour, tourDone, type TourStep } from "./components/ui/Tour";
import { Tooltip, InfoTip } from "./components/ui/Tooltip";
import { InfoBox, resetInfoBoxes } from "./components/ui/InfoBox";
import { Lightbox, type LightboxItem } from "./components/ui/Lightbox";
import { GlossaryDialog } from "./components/ui/GlossaryDialog";
import itauLogo from "./assets/itau.png";

type Tab = "assessment" | "quote" | "photos" | "calls" | "input";
const TABS: { id: Tab; label: string; needsAssessment: boolean; icon: LucideIcon; hint: string }[] = [
  { id: "assessment", label: "Parecer", needsAssessment: true, icon: ClipboardCheck, hint: "Checklist, recomendação, conta do score, apontamentos e a sua decisão" },
  { id: "quote", label: "Orçamento × escopo", needsAssessment: true, icon: Receipt, hint: "Cada item do orçamento classificado contra o escopo e a tabela de referência" },
  { id: "photos", label: "Fotos", needsAssessment: true, icon: Images, hint: "O que cada foto mostra, se corresponde ao escopo e sinais de reaproveitamento" },
  { id: "calls", label: "Chamadas ao modelo", needsAssessment: true, icon: Cpu, hint: "Cada chamada à IA: tarefa, modelo, tempo, tokens, custo e o JSON devolvido" },
  { id: "input", label: "Entrada do chamado", needsAssessment: false, icon: Inbox, hint: "O que chegou do Salesforce: escopo, orçamento e anexos" },
];

export default function App() {
  const [config, setConfig] = useState<AppSettings | null>(null);
  const [tickets, setTickets] = useState<TicketSummary[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [streamFilter, setStreamFilter] = useState<"all" | "SETA" | "SISR">("all");
  const [focus, setFocus] = useState<string | null>(null);
  const [detail_level, setDetail] = useState<TicketDetail | null>(null);
  const [mode, setMode] = useState<"simulated" | "api">("simulated");
  const [batchMode, setBatchMode] = useState<"sync" | "batch">("sync");
  const [view, setView] = useState<"analysis" | "metrics" | "validation">("analysis");
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [dataset, setDataset] = useState("demo");
  const [showNewTicket, setShowNewTicket] = useState(false);
  const [savedAssessment, setSavedAssessment] = useState<Assessment | null>(null);
  const [phase, setPhase] = useState(2);
  const [mainModel, setMainModel] = useState("");
  const [fastModel, setFastModel] = useState("");
  const [execution, setRun] = useState<Run | null>(null);
  const [tab, setTabRaw] = useState<Tab>("input");
  const [highlight, setHighlight] = useState<{ items?: number[]; files?: string[] }>({});
  // troca de aba pelo usuário limpa o destaque; goTo (clique num apontamento) troca e destaca
  const setTab = useCallback((t: Tab | ((a: Tab) => Tab)) => { setHighlight({}); setTabRaw(t); }, []);
  const goTo = useCallback((t: "quote" | "photos" | "input", h: { items?: number[]; files?: string[] } = {}) => { setTabRaw(t); setHighlight(h); }, []);
  const [error, setError] = useState<string | null>(null);
  const [photos, setPhotos] = useState<{ items: LightboxItem[]; index: number } | null>(null);
  const openPhoto = useCallback((items: LightboxItem[], index: number) => setPhotos({ items, index }), []);
  const [tourOpen, setTourOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [glossaryOpen, setGlossaryOpen] = useState(false);
  // lista de chamados recolhível: lembrada neste navegador; atalho "[" alterna
  const [listCollapsed, setListCollapsedRaw] = useState(() => { try { return localStorage.getItem("atest.list.collapsed") === "1"; } catch { return false; } });
  const setListCollapsed = useCallback((v: boolean) => {
    setListCollapsedRaw(v);
    try { localStorage.setItem("atest.list.collapsed", v ? "1" : "0"); } catch { /* armazenamento indisponível */ }
  }, []);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.key !== "[" || e.ctrlKey || e.metaKey || e.altKey || t.closest("input, textarea, select, [contenteditable]")) return;
      setListCollapsedRaw((v) => { try { localStorage.setItem("atest.list.collapsed", v ? "0" : "1"); } catch { /* */ } return !v; });
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    api.config().then((c) => {
      setConfig(c);
      setPhase(c.phase);
      setBatchMode(c.batch_mode);
      setMainModel(c.main_model);
      setFastModel(c.fast_model);
    }).catch((e) => setError(String(e.message ?? e)));
    api.datasets().then(setDatasets).catch(() => undefined);
    api.tickets().then((cs) => {
      setTickets(cs);
      const demo = cs.filter((c) => c.dataset === "demo");
      const base = demo.length ? demo : cs;
      setSelected(new Set(base.slice(0, 3).map((c) => c.ticket_id)));
      if (base.length) setFocus(base[0].ticket_id);
    }).catch((e) => setError(String(e.message ?? e)));
  }, []);

  const reloadTickets = useCallback(() => api.tickets().then(setTickets).catch(() => undefined), []);

  useEffect(() => {
    if (!focus) return;
    setDetail(null);
    api.ticket(focus).then(setDetail).catch((e) => setError(String(e.message ?? e)));
  }, [focus]);

  const focusState = focus ? execution?.tickets[focus] : undefined;
  const focusSummary = tickets.find((c) => c.ticket_id === focus);

  // persistência: sem resultado na execução atual, mostra o último parecer salvo no banco
  const lastId = !focusState ? focusSummary?.last?.assessment_id : undefined;
  useEffect(() => {
    setSavedAssessment(null);
    if (lastId) api.assessment(lastId).then(setSavedAssessment).catch(() => setSavedAssessment(null));
  }, [lastId]);
  const assessment = focusState?.assessment ?? (focusState ? null : savedAssessment);

  useEffect(() => {
    if (!assessment && TABS.find((a) => a.id === tab)?.needsAssessment) setTab("input");
  }, [assessment, tab]);

  const track = useCallback((id: string) => {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = window.setInterval(async () => {
      try {
        const ex = await api.execution(id);
        setRun(ex);
        if (ex.status === "completed" && timer.current) {
          window.clearInterval(timer.current);
          reloadTickets();
        }
      } catch (e) {
        setError(String((e as Error).message));
        if (timer.current) window.clearInterval(timer.current);
      }
    }, 600);
  }, [reloadTickets]);

  const openRun = async (id: string, ticket?: string) => {
    try {
      const ex = await api.execution(id);
      setRun(ex);
      const target = ticket ?? Object.keys(ex.tickets)[0];
      if (target) {
        setFocus(target);
        const ds = tickets.find((c) => c.ticket_id === target)?.dataset;
        if (ds && ds !== dataset && dataset !== "all") setDataset(ds);
      }
      if (ticket) setTab("assessment");
      setView("analysis");
      if (ex.status === "running") track(id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm(`Apagar o chamado ${id}, enviado pelo painel? Os pareceres já gravados continuam no banco.`)) return;
    await api.deleteTicket(id);
    setSelected((s) => { const n = new Set(s); n.delete(id); return n; });
    const cs = await api.tickets();
    setTickets(cs);
    setFocus(cs[0]?.ticket_id ?? null);
  };

  const run = async () => {
    setError(null);
    try {
      const ids = tickets.map((c) => c.ticket_id).filter((id) => selected.has(id));
      const ex = await api.run({ tickets: ids, mode, batch_mode: batchMode, phase, main_model: mainModel, fast_model: fastModel });
      setRun(ex);
      if (!focus || !selected.has(focus)) setFocus(ids[0]);
      track(ex.id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  // quando o chamado em foco termina, abre o parecer
  const focusDone = focusState?.status === "done";
  useEffect(() => {
    if (focusDone) setTab((a) => (a === "input" ? "assessment" : a));
  }, [focusDone, focus]);

  const running = execution?.status === "running";
  const summary = useMemo(() => count(execution), [execution]);

  const downloadJson = () => {
    if (!assessment) return;
    const blob = new Blob([JSON.stringify(assessment, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `parecer_${assessment.ticket_id}.json`;
    a.click();
  };

  const rubric = config?.rubric ?? DEFAULT_RUBRIC;
  const tourSteps = useMemo(() => buildTour(view, {
    toAnalysis: () => setView("analysis"),
    toAssessment: () => { setView("analysis"); if (assessment) setTab("assessment"); },
    hasAssessment: !!assessment,
  }), [view, assessment]);

  // primeira visita: abre o tour sozinho, depois que a tela carregou
  useEffect(() => {
    if (config && tickets.length && !tourDone()) {
      const t = window.setTimeout(() => setTourOpen(true), 600);
      return () => window.clearTimeout(t);
    }
  }, [config, tickets.length]);

  return (
    <div className="grid h-full grid-rows-[auto_auto_1fr_auto]">
      <header className="flex flex-wrap items-center gap-x-8 gap-y-3 border-b border-line bg-sheet px-6 py-3">
        <div className="flex items-center gap-3">
          <img src={itauLogo} alt="Itaú" width={36} height={36} className="size-9 shrink-0 rounded-[9px]" />
          <span className="h-7 w-px bg-line" aria-hidden />
          <h1 className="largo text-[22px] font-extrabold tracking-tight text-blueprint">Atest.AI</h1>
          <span className="hidden text-sm text-muted xl:inline">Pré-análise de chamados SETA e SISR</span>
        </div>
        <nav data-tour="nav" className="flex gap-1 text-[15px]" aria-label="Seções">
          {(["analysis", "validation", "metrics"] as const).map((v) => (
            <Tooltip key={v} side="bottom" content={SECTION_HINT[v]}>
              <button onClick={() => setView(v)} aria-current={view === v ? "page" : undefined}
                className={`rounded-md px-3 py-1 transition-colors ${view === v ? "bg-blueprint-soft font-semibold text-blueprint" : "text-muted hover:bg-paper hover:text-ink"}`}>
                {v === "analysis" ? "Análise" : v === "validation" ? "Validação" : "Operação"}
              </button>
            </Tooltip>
          ))}
        </nav>
        <HelpMenu open={helpOpen} setOpen={setHelpOpen}
          tour={() => { setHelpOpen(false); setTourOpen(true); }}
          glossary={() => { setHelpOpen(false); setGlossaryOpen(true); }}
          reset={() => { setHelpOpen(false); resetInfoBoxes(); }} />
        {view !== "validation" && <div className="ml-auto flex flex-wrap items-center gap-4 text-sm">
          <fieldset data-tour="mode" className="flex items-center gap-2">
            <legend className="sr-only">Modo</legend>
            <span className="flex items-center gap-1 text-muted">Modo <InfoTip term="mode" /></span>
            <div className="flex rounded-lg bg-paper p-0.5">
              <SegmentButton active={mode === "simulated"} onClick={() => setMode("simulated")}>Simulado</SegmentButton>
              <SegmentButton active={mode === "api"} onClick={() => setMode("api")} disabled={!config?.api_available}
                hint={config?.api_available ? `Chama a API: ${config.main_model}` : `Defina a chave de: ${config?.missing_keys.join(", ")} (config/.secrets.toml ou variável de ambiente)`}>
                API{config ? ` ${config.providers.map((p) => p[0].toUpperCase() + p.slice(1)).join("/")}` : ""}</SegmentButton>
            </div>
          </fieldset>
          <fieldset data-tour="phase" className="flex items-center gap-2">
            <legend className="sr-only">Fase da régua</legend>
            <span className="flex items-center gap-1 text-muted">Régua <InfoTip term="phase" /></span>
            <div className="flex rounded-lg bg-paper p-0.5">
              <SegmentButton active={phase === 1} onClick={() => setPhase(1)} hint="MVP: sem antes, ilegibilidade e reaproveitamento">Fase 1</SegmentButton>
              <SegmentButton active={phase === 2} onClick={() => setPhase(2)} hint="Inclui as checagens da Fase 2">Fase 2</SegmentButton>
            </div>
          </fieldset>
          {mode === "api" && (
            <div className="flex rounded-lg bg-paper p-0.5">
              <SegmentButton active={batchMode === "sync"} onClick={() => setBatchMode("sync")} hint="Uma requisição por vez: resultado em segundos">Síncrono</SegmentButton>
              <SegmentButton active={batchMode === "batch"} onClick={() => setBatchMode("batch")} hint="Message Batches API: assíncrono, metade do custo">Batch −50%</SegmentButton>
            </div>
          )}
          {mode === "api" && (
            <div className="flex items-center gap-2">
              <Tooltip content="Modelo principal: lê o escopo, confere o orçamento e escreve o parecer">
                <input aria-label="Modelo principal" value={mainModel} onChange={(e) => setMainModel(e.target.value)}
                  className="w-40 rounded-md border border-line px-2 py-1" />
              </Tooltip>
              <Tooltip content="Modelo rápido: identifica os anexos e analisa as fotos">
                <input aria-label="Modelo rápido" value={fastModel} onChange={(e) => setFastModel(e.target.value)}
                  className="w-36 rounded-md border border-line px-2 py-1" />
              </Tooltip>
            </div>
          )}
          <Tooltip content="Envie um chamado real ou de teste: dados, planilha de orçamento e fotos">
            <button onClick={() => setShowNewTicket(true)} disabled={!config}
              className="flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 font-medium hover:bg-paper">
              <Plus size={16} /> Novo chamado
            </button>
          </Tooltip>
          <Tooltip content={!selected.size ? "Marque ao menos um chamado na lista à esquerda" : running ? "Aguarde a execução atual terminar" : `Roda o pipeline completo nos ${selected.size} chamado(s) marcados`}>
            <button data-tour="run" onClick={run} disabled={!selected.size || running}
              className="flex items-center gap-2 rounded-lg bg-blueprint px-4 py-2 font-semibold text-white shadow-sm transition-colors hover:bg-[#1d44a0] disabled:pointer-events-none disabled:opacity-50">
              {running ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
              {running ? "Analisando…" : `Analisar ${selected.size} chamado${selected.size === 1 ? "" : "s"}`}
            </button>
          </Tooltip>
        </div>}
      </header>

      {view === "validation" && config ? (
        <main className="grade row-span-2 min-h-0 overflow-y-auto">
          <ValidationView config={config} openCase={(ex, ch) => openRun(ex, ch)} />
        </main>
      ) : <>
      <div data-tour="status" className="border-b border-line bg-sheet/70 px-6 py-2 text-sm" aria-live="polite">
        {error ? (
          <span className="flex items-center gap-2 text-bad">
            <X size={15} className="shrink-0" /> <span className="flex-1">{error}</span>
            <button onClick={() => setError(null)} className="rounded-md px-2 py-0.5 text-[13px] font-medium hover:bg-[#f8e4e2]">Dispensar</button>
          </span>
        ) : execution ? (
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
            <span className="text-muted">
              Execução {execution.id} em modo {execution.mode === "api" ? `API (${execution.models.main}${execution.batch_mode === "batch" ? ", Message Batches" : ""})` : "simulado"}, régua fase {execution.phase}
            </span>
            <span className="tabular-nums">{summary.done} de {summary.total} concluídos</span>
            {Object.entries(summary.byRec).map(([r, n]) => (
              <span key={r} className="flex items-center gap-1.5"><i className="size-2.5 rounded-full" style={{ background: REC[r as Recommendation].color }} />{REC[r as Recommendation].short} {n}</span>
            ))}
            {execution.evaluation && (
              <span className="flex items-center gap-1 font-medium">Concordância com o gabarito: {execution.evaluation.exact_recommendation} de {execution.evaluation.n} <InfoTip term="ground_truth" /></span>
            )}
            {execution.mode === "api" && execution.status === "completed" && (
              <span className="tabular-nums">Custo {brl4(execution.cost_brl)} <span className="text-muted">({execution.input_tokens.toLocaleString("pt-BR")} tokens de entrada, {execution.output_tokens.toLocaleString("pt-BR")} de saída)</span></span>
            )}
            {execution.output_folder && <span className="text-muted">Saídas em {execution.output_folder}</span>}
          </div>
        ) : (
          <span className="text-muted">
            <b className="font-medium text-ink">Como começar:</b> marque os chamados na lista à esquerda e clique em <b className="font-medium text-ink">Analisar</b>. O modo simulado demonstra o fluxo sem chamar a API.
            {" "}<button onClick={() => setTourOpen(true)} className="font-medium text-blueprint hover:underline">Fazer o tour guiado</button>
          </span>
        )}
      </div>

      <div className={`grid min-h-0 grid-cols-1 transition-[grid-template-columns] duration-200 ${listCollapsed ? "grid-rows-[auto_1fr] md:grid-rows-1 md:grid-cols-[60px_1fr]" : "md:grid-cols-[380px_1fr]"}`}>
        <TicketList collapsed={listCollapsed} setCollapsed={setListCollapsed} tickets={tickets} selected={selected} focus={focus} focusTicket={setFocus} execution={execution}
          streamFilter={streamFilter} setStreamFilter={setStreamFilter} datasets={datasets} dataset={dataset} setDataset={setDataset}
          toggle={(id) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; })}
          setAll={(ids, mark) => setSelected((s) => { const n = new Set(s); ids.forEach((i) => (mark ? n.add(i) : n.delete(i))); return n; })} />

        <main className="grade min-h-0 overflow-y-auto">
          {view === "metrics" ? (
            <OperationsView openRun={openRun} />
          ) : detail_level ? (
            <div className="mx-auto max-w-[1180px] px-6 py-6">
              <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
                <div>
                  <div className="text-sm text-muted">{detail_level.workstream} · {detail_level.branch} · {detail_level.supplier}</div>
                  <h2 className="largo flex items-center gap-3 text-[28px] font-bold leading-tight">
                    Chamado {detail_level.ticket_id}
                    {detail_level.origin === "upload" && (
                      <Tooltip content="Apagar chamado enviado pelo painel (os pareceres continuam no banco)">
                        <button onClick={() => remove(detail_level.ticket_id)} aria-label="Apagar chamado" className="rounded-md p-1 text-muted hover:bg-[#f8e4e2] hover:text-bad">
                          <Trash2 size={18} />
                        </button>
                      </Tooltip>
                    )}
                  </h2>
                  <div className="text-[15px]">{detail_level.category_label}, {detail_level.symptom_label.toLowerCase()}</div>
                </div>
                {focusState && focusState.status !== "done" && focusState.status !== "error" && <StageProgress state={focusState} />}
                {!focusState && savedAssessment && (
                  <span className="text-sm text-muted">Último parecer salvo, de {new Date(savedAssessment.generated_at).toLocaleString("pt-BR")}</span>
                )}
                {focusState?.status === "error" && <span className="text-sm text-bad">{focusState.error}</span>}
              </div>

              {!assessment && !focusState && (
                <InfoBox tone="tip" className="mb-4" title="Este chamado ainda não foi analisado">
                  Marque-o na lista à esquerda e clique em <b>Analisar</b>. Enquanto isso, a aba Entrada do chamado mostra o que chegou: escopo, orçamento e fotos.
                </InfoBox>
              )}

              <nav data-tour="tabs" className="mb-5 flex gap-1 overflow-x-auto border-b border-line" role="tablist">
                {TABS.map((a) => {
                  const off = a.needsAssessment && !assessment;
                  const Icon = a.icon;
                  return (
                    <Tooltip key={a.id} side="bottom" content={off ? "Disponível depois de analisar o chamado" : a.hint}>
                      <button role="tab" aria-selected={tab === a.id} disabled={off} onClick={() => setTab(a.id)}
                        className={`-mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-[15px] transition-colors ${tab === a.id ? "border-blueprint font-semibold text-blueprint" : "border-transparent text-muted hover:text-ink"} disabled:pointer-events-none disabled:opacity-40`}>
                        <Icon size={16} aria-hidden />
                        {a.label}
                        {a.id === "assessment" && assessment && assessment.findings.length > 0 && <span className="rounded-full bg-bad px-1.5 text-[11px] text-white" aria-label={`${assessment.findings.length} apontamentos`}>{assessment.findings.length}</span>}
                      </button>
                    </Tooltip>
                  );
                })}
                {assessment && (
                  <Tooltip className="ml-auto inline-flex" content="Baixa o parecer completo em JSON (para auditoria ou integração)">
                    <button onClick={downloadJson} className="flex items-center gap-1.5 whitespace-nowrap px-3 py-2 text-sm text-muted hover:text-ink">
                      <Download size={15} /> Parecer em JSON
                    </button>
                  </Tooltip>
                )}
              </nav>

              {tab === "input" && <TicketInputTab ch={detail_level} openPhoto={openPhoto} />}
              {/* fica montado (só escondido) para não perder a revisão em andamento ao consultar outras abas */}
              {assessment && (
                <div hidden={tab !== "assessment"}>
                  <AssessmentTab key={`${assessment.ticket_id}-${assessment.record_id ?? assessment.generated_at}`} p={assessment} comparison={focusState?.comparison ?? null} rubric={rubric}
                    ticket={detail_level} openPhoto={openPhoto} goTo={goTo} />
                </div>
              )}
              {assessment && tab === "quote" && <QuoteTab p={assessment} highlight={highlight.items} />}
              {assessment && tab === "photos" && <PhotosTab p={assessment} base={`/api/tickets/${assessment.ticket_id}/attachments`} openPhoto={openPhoto} highlight={highlight.files} />}
              {assessment && tab === "calls" && <LlmCallsTab p={assessment} />}
            </div>
          ) : (
            <div className="flex h-full items-center justify-center text-muted"><Loader2 className="animate-spin" /></div>
          )}
        </main>
      </div>
      </>}

      <footer className="col-span-full flex flex-wrap items-center justify-center gap-x-2 gap-y-0.5 border-t border-line bg-sheet px-6 py-1.5 text-center text-[12px] text-muted">
        <span>Feito por <b className="font-semibold text-ink/80">DataCraft</b></span>
        <span aria-hidden>-</span>
        <span>Gerência de Ciência de Dados</span>
        <span aria-hidden>-</span>
        <span>Comunidade Infra de Canais Físicos</span>
      </footer>

      {showNewTicket && config && (
        <NewTicket config={config} close={() => setShowNewTicket(false)} created={async (c) => {
          setShowNewTicket(false);
          await reloadTickets();
          setSelected(new Set([c.ticket_id]));
          setFocus(c.ticket_id);
          setTab("input");
          setView("analysis");
          if (config.api_available) setMode("api");
        }} />
      )}

      {photos && <Lightbox items={photos.items} start={photos.index} onClose={() => setPhotos(null)} />}
      {glossaryOpen && <GlossaryDialog onClose={() => setGlossaryOpen(false)} />}
      <Tour steps={tourSteps} open={tourOpen} onClose={() => setTourOpen(false)} />
    </div>
  );
}

function SegmentButton(p: { active: boolean; onClick: () => void; children: React.ReactNode; disabled?: boolean; hint?: string }) {
  return (
    <Tooltip content={p.hint} side="bottom">
      <button type="button" disabled={p.disabled} onClick={p.onClick} aria-pressed={p.active}
        className={`rounded-md px-3 py-1 transition-colors ${p.active ? "bg-sheet font-semibold text-ink shadow-sm" : "text-muted hover:text-ink"} disabled:pointer-events-none disabled:opacity-40`}>
        {p.children}
      </button>
    </Tooltip>
  );
}

const SECTION_HINT = {
  analysis: "Analise chamados um a um e leia o parecer",
  validation: "Rode um conjunto inteiro contra o gabarito e meça a qualidade",
  metrics: "Volume, custo, latência e decisões das pessoas analistas",
} as const;

/** Menu de ajuda: tour guiado da tela atual, glossário e reexibir as dicas fechadas. */
function HelpMenu({ open, setOpen, tour, glossary, reset }: { open: boolean; setOpen: (v: boolean) => void; tour: () => void; glossary: () => void; reset: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const out = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", out);
    window.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", out); window.removeEventListener("keydown", esc); };
  }, [open, setOpen]);
  const item = "flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-left hover:bg-paper";
  return (
    <div ref={ref} className="relative text-sm" data-tour="help">
      <button onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="menu"
        className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 font-medium transition-colors ${open ? "border-blueprint bg-blueprint-soft text-blueprint" : "border-line text-muted hover:bg-paper hover:text-ink"}`}>
        <HelpCircle size={16} /> Ajuda
      </button>
      {open && (
        <div role="menu" className="surgir absolute left-0 z-40 mt-2 w-64 rounded-xl border border-line bg-sheet p-1.5 shadow-xl">
          <button role="menuitem" onClick={tour} className={item}><Compass size={16} className="shrink-0 text-blueprint" /><span><b className="block font-medium">Tour guiado</b><span className="text-[12px] text-muted">Passo a passo desta tela</span></span></button>
          <button role="menuitem" onClick={glossary} className={item}><BookOpen size={16} className="shrink-0 text-blueprint" /><span><b className="block font-medium">Glossário</b><span className="text-[12px] text-muted">Score, peso, kappa, F1…</span></span></button>
          <button role="menuitem" onClick={reset} className={item}><RotateCcw size={16} className="shrink-0 text-blueprint" /><span><b className="block font-medium">Reexibir dicas</b><span className="text-[12px] text-muted">Mostra de novo as caixas fechadas</span></span></button>
        </div>
      )}
    </div>
  );
}

/** Passos do tour de cada seção. Passos cujo alvo não está na tela são pulados. */
function buildTour(view: "analysis" | "metrics" | "validation", a: { toAnalysis: () => void; toAssessment: () => void; hasAssessment: boolean }): TourStep[] {
  const help: TourStep = { target: "help", title: "Ajuda sempre à mão", body: <p>Refaça o tour, abra o glossário ou reexiba as dicas pelo menu <b>Ajuda</b>. Os ícones <b>(i)</b> explicam cada termo.</p> };
  if (view === "validation") {
    return [
      { title: "Validação em lote", body: <p>Aqui você mede o Atest.AI como um modelo: roda um conjunto de chamados com gabarito e compara as respostas.</p> },
      { target: "val-config", title: "Configure a rodada", body: <p>Escolha o conjunto, o tamanho da amostra e o modo. No simulado, o <b>erro simulado</b> imita um modelo que às vezes erra.</p> },
      { target: "val-run", title: "Rode", body: <p>A barra mostra o progresso. Ao terminar, o relatório aparece logo abaixo.</p> },
      { target: "val-gate", title: "Portão de qualidade", body: <p>Resumo de aprovado ou reprovado: cada métrica tem um limite para a configuração ir para produção.</p> },
      { target: "val-kpis", title: "Métricas principais", body: <p>Passe o mouse no <b>(i)</b> de cada número para ver o que ele significa e como ler.</p> },
      { target: "val-matrix", title: "Onde o modelo erra", body: <p>A matriz de confusão cruza gabarito e Atest.AI. Fora da diagonal estão os erros.</p> },
      { target: "val-mismatches", title: "Casos divergentes", body: <p>Clique num caso para abrir o parecer na Análise e entender o erro.</p> },
      help,
    ];
  }
  if (view === "metrics") {
    return [
      { target: "ops-kpis", title: "Operação", body: <p>Tudo o que já passou pelo Atest.AI neste ambiente: volume, custo e valor em questão.</p> },
      { target: "ops-feedback", title: "Decisões das pessoas analistas", body: <p>Apontamentos marcados como improcedentes são os primeiros candidatos a ajuste na régua ou nos prompts.</p> },
      { target: "ops-tasks", title: "Custo por tarefa", body: <p>Latência, tokens e custo de cada tipo de chamada à IA.</p> },
      { target: "ops-runs", title: "Execuções recentes", body: <p>Clique numa execução para reabrir os pareceres dela na Análise.</p> },
      help,
    ];
  }
  return [
    { before: a.toAnalysis, title: "Bem-vindo ao Atest.AI", body: <>
      <p>O Atest.AI faz a pré-análise de chamados de manutenção: confere checklist, escopo, orçamento e fotos e sugere uma decisão.</p>
      <p>A IA <b>aponta divergências</b>, uma régua fixa converte os apontamentos em <b>score</b> e <b>você decide</b>. Leva 1 minuto.</p>
    </> },
    { target: "nav", title: "Três seções", body: <p><b>Análise</b> para trabalhar chamado a chamado, <b>Validação</b> para medir a qualidade contra o gabarito e <b>Operação</b> para custo e uso.</p> },
    { target: "ticket-list", title: "Lista de chamados", body: <p>Clique num chamado para abri-lo. Marque a caixa de seleção para incluí-lo na próxima análise. Filtre por conjunto e esteira no topo. O botão no canto (ou a tecla <b>[</b>) recolhe a lista para ganhar espaço.</p> },
    { target: "mode", title: "Modo de execução", body: <p><b>Simulado</b> demonstra o fluxo sem custo. <b>API</b> chama o modelo de verdade.</p> },
    { target: "phase", title: "Fase da régua", body: <p>A Fase 2 inclui checagens extras: foto do antes, ilegibilidade e foto reaproveitada.</p> },
    { target: "run", title: "Analisar", body: <p>Roda o pipeline nos chamados marcados: checklist → escopo → orçamento → fotos → score → parecer.</p> },
    { target: "status", title: "Andamento", body: <p>Progresso da execução, recomendações por tipo e, quando há gabarito, quantas bateram.</p> },
    { target: "tabs", title: "Abas do chamado", body: <p>A <b>Entrada</b> está sempre disponível. As demais abrem depois da análise. Passe o mouse em cada aba para ver o que ela mostra.</p> },
    ...(a.hasAssessment ? [
      { target: "checklist", before: a.toAssessment, title: "1. Checklist mínimo", body: <p>Primeira coisa conferida. Se faltar documento obrigatório, o chamado volta sem score.</p> },
      { target: "verdict", title: "2. Parecer", body: <p>O carimbo mostra o score (0 a 100) e a recomendação, com o motivo e um resumo.</p> },
      { target: "score-breakdown", title: "3. Como o score foi calculado", body: <p>Cada validação começa com 100 e perde pontos por apontamento. O score é a média ponderada: Escopo 20%, Orçamento 40%, Fotos 40%.</p> },
      { target: "findings", title: "4. Apontamentos", body: <p>Cada apontamento mostra quantos pontos tirou do score. Ex.: <b>−35 na nota de Orçamento</b> vira <b>−14 no score</b>, porque Orçamento vale 40%.</p> },
      { target: "decision", title: "5. A sua decisão, por último", body: <p>Depois de ler tudo, aceite, ajuste ou discorde. A sua decisão é a final e calibra a régua e os prompts.</p> },
    ] : []),
    help,
  ];
}

function count(ex: Run | null) {
  const byRec: Partial<Record<Recommendation, number>> = {};
  let done = 0;
  if (!ex) return { byRec, done, total: 0 };
  for (const st of Object.values(ex.tickets)) {
    if (st.assessment) {
      done++;
      byRec[st.assessment.recommendation] = (byRec[st.assessment.recommendation] ?? 0) + 1;
    } else if (st.status === "error") done++;
  }
  return { byRec, done, total: Object.keys(ex.tickets).length };
}
