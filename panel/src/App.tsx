import { BarChart3, BookOpen, ClipboardCheck, Compass, FileSearch, Cpu, Download, FlaskConical, HelpCircle, Images, Inbox, ListChecks, Loader2, Play, Plus, Receipt, RotateCcw, ScanSearch, Settings, Trash2, Wifi, WifiOff, X, type LucideIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type TicketDetail, type TicketSummary, type AppSettings, type Dataset, type Run, type Assessment, type Recommendation, type ScenarioTag } from "./api";
import { serverOutdated } from "./api";
import { LlmCallsTab } from "./components/LlmCallsTab";
import { ScopeTab } from "./components/ScopeTab";
import { StageTimeline } from "./components/StageTimeline";
import { TicketInputTab } from "./components/TicketInputTab";
import { PhotosTab } from "./components/PhotosTab";
import { QuoteTab } from "./components/QuoteTab";
import { AssessmentTab } from "./components/AssessmentTab";
import { StageProgress } from "./components/StageProgress";
import { TicketList } from "./components/TicketList";
import { OperationsView } from "./components/OperationsView";
import { NewTicket } from "./components/NewTicket";
import { RerunDialog } from "./components/RerunDialog";
import { ValidationView } from "./components/ValidationView";
import { ScenariosView } from "./components/ScenariosView";
import { brl4, REC, DEFAULT_RUBRIC, ENV_NAME, MAINTENANCE_LABEL } from "./format";
import { Tour, tourDone, type TourStep } from "./components/ui/Tour";
import { Tooltip, InfoTip } from "./components/ui/Tooltip";
import { InfoBox, resetInfoBoxes } from "./components/ui/InfoBox";
import { Lightbox, type LightboxItem } from "./components/ui/Lightbox";
import { GlossaryDialog } from "./components/ui/GlossaryDialog";
import itauLogo from "./assets/itau.png";
import { AdminView } from "./components/admin/AdminView";
import { ModelCombobox } from "./components/ui/ModelCombobox";
import { ProviderPicker, findChoice, initialProvider, providerChoices, withProvider } from "./components/ui/ProviderPicker";

type Tab = "assessment" | "scope" | "quote" | "photos" | "calls" | "input";
const TABS: { id: Tab; label: string; needsAssessment: boolean; icon: LucideIcon; hint: string }[] = [
  { id: "assessment", label: "Parecer", needsAssessment: true, icon: ClipboardCheck, hint: "Checklist, recomendação, conta do score, apontamentos e a sua decisão" },
  { id: "scope", label: "Escopo", needsAssessment: true, icon: FileSearch, hint: "O texto do escopo, o que a IA extraiu dele e as verificações de clareza e coerência" },
  { id: "quote", label: "Orçamento × escopo", needsAssessment: true, icon: Receipt, hint: "Cada item do orçamento classificado contra o escopo e a tabela de referência" },
  { id: "photos", label: "Fotos", needsAssessment: true, icon: Images, hint: "O que cada foto mostra, se corresponde ao escopo e sinais de reaproveitamento" },
  { id: "calls", label: "Chamadas ao modelo", needsAssessment: true, icon: Cpu, hint: "Cada chamada à IA: tarefa, modelo, tempo, tokens, custo e o JSON devolvido" },
  { id: "input", label: "Entrada do chamado", needsAssessment: false, icon: Inbox, hint: "O que chegou do Salesforce: escopo, orçamento e anexos" },
];

type View = "analysis" | "scenarios" | "metrics" | "validation" | "admin";

export default function App() {
  const [config, setConfig] = useState<AppSettings | null>(null);
  const [tickets, setTickets] = useState<TicketSummary[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [streamFilter, setStreamFilter] = useState<"all" | "SETA" | "SISR">("all");
  const [focus, setFocus] = useState<string | null>(null);
  const [detail_level, setDetail] = useState<TicketDetail | null>(null);
  const [mode, setMode] = useState<"simulated" | "api">("simulated");
  const [batchMode, setBatchMode] = useState<"sync" | "batch">("sync");
  const [view, setView] = useState<View>("analysis");
  const [adminVisited, setAdminVisited] = useState(false);
  useEffect(() => { if (view === "admin") setAdminVisited(true); }, [view]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [scenarioTags, setScenarioTags] = useState<ScenarioTag[]>([]);
  const [dataset, setDataset] = useState("demo");
  const [showNewTicket, setShowNewTicket] = useState(false);
  const [savedAssessment, setSavedAssessment] = useState<Assessment | null>(null);
  const [phase, setPhase] = useState(2);
  const [mainModel, setMainModel] = useState("");
  const [fastModel, setFastModel] = useState("");
  const [provider, setProvider] = useState("");
  const [execution, setRun] = useState<Run | null>(null);
  const [tab, setTabRaw] = useState<Tab>("input");
  const [highlight, setHighlight] = useState<{ items?: number[]; files?: string[] }>({});
  // troca de aba pelo usuário limpa o destaque; goTo (clique num apontamento) troca e destaca
  const setTab = useCallback((t: Tab | ((a: Tab) => Tab)) => { setHighlight({}); setTabRaw(t); }, []);
  const goTo = useCallback((t: Tab, h: { items?: number[]; files?: string[] } = {}) => { setTabRaw(t); setHighlight(h); }, []);
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
      const p = initialProvider(c);
      const choice = findChoice(c, p);
      setProvider(p);
      setMainModel(choice?.main ?? c.main_model);
      setFastModel(choice?.fast ?? c.fast_model);
    }).catch((e) => setError(String(e.message ?? e)));
    api.datasets().then(setDatasets).catch(() => undefined);
    api.scenarios().then(setScenarioTags).catch(() => undefined);
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

  // aba Cenários: abre um chamado ou marca vários na lista da Análise, ajustando o filtro de conjunto para mostrá-los
  const showInList = (ids: string[]) => {
    const sets = new Set(ids.map((id) => tickets.find((c) => c.ticket_id === id)?.dataset));
    const only = sets.size === 1 ? [...sets][0] : undefined;
    if (dataset !== "all" && (!only || only !== dataset)) setDataset(only ?? "all");
  };
  const openFromScenarios = (id: string) => {
    showInList([id]);
    setFocus(id);
    setView("analysis");
  };
  const selectFromScenarios = (ids: string[]) => {
    showInList(ids);
    setSelected(new Set(ids));
    if (ids.length) setFocus(ids[0]);
    setView("analysis");
  };

  const remove = async (id: string) => {
    if (!window.confirm(`Apagar o chamado ${id}, enviado pelo painel? Os pareceres já gravados continuam no banco.`)) return;
    await api.deleteTicket(id);
    setSelected((s) => { const n = new Set(s); n.delete(id); return n; });
    const cs = await api.tickets();
    setTickets(cs);
    setFocus(cs[0]?.ticket_id ?? null);
  };

  // trocar de provedor preenche os modelos que ele traz na configuração ([panel.providers])
  const chooseProvider = (id: string) => {
    const choice = findChoice(config, id);
    setProvider(id);
    if (choice) { setMainModel(choice.main); setFastModel(choice.fast); }
  };
  const providerModels = (config?.models ?? []).filter((m) => m.provider === provider);
  const currentChoice = findChoice(config, provider);

  const start = async (ids: string[], o: { refresh?: boolean; keepFocus?: boolean } = {}) => {
    setError(null);
    try {
      const ex = await api.run({ tickets: ids, mode, batch_mode: batchMode, phase, provider: provider || undefined,
        main_model: withProvider(mainModel, provider), fast_model: withProvider(fastModel, provider), refresh: o.refresh });
      setRun(ex);
      if (!o.keepFocus && (!focus || !ids.includes(focus))) setFocus(ids[0]);
      track(ex.id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  // no modo API, chamado com parecer salvo de uma execução real: pergunta antes de chamar a API de novo
  const [rerunAsk, setRerunAsk] = useState<TicketSummary[] | null>(null);
  const [openSaved, setOpenSaved] = useState<string | null>(null);
  const marked = tickets.filter((c) => selected.has(c.ticket_id));
  const run = () => {
    const saved = mode === "api" ? marked.filter((c) => c.last?.mode === "api") : [];
    if (saved.length) setRerunAsk(saved);
    else start(marked.map((c) => c.ticket_id));
  };
  const reuseSaved = (saved: TicketSummary[]) => {
    setRerunAsk(null);
    const savedIds = new Set(saved.map((c) => c.ticket_id));
    const rest = marked.map((c) => c.ticket_id).filter((id) => !savedIds.has(id));
    const target = focus && savedIds.has(focus) ? focus : saved[0].ticket_id;
    // sem execução na tela, o painel mostra o último parecer salvo de cada chamado
    if (rest.length) start(rest, { keepFocus: true }); else setRun(null);
    setFocus(target);
    setOpenSaved(target);
  };
  const rerun = () => {
    setRerunAsk(null);
    start(marked.map((c) => c.ticket_id), { refresh: true });
  };
  // abre o parecer salvo assim que ele carregar
  useEffect(() => {
    if (openSaved && savedAssessment?.ticket_id === openSaved && !focusState) { setTab("assessment"); setOpenSaved(null); }
  }, [openSaved, savedAssessment, focusState, setTab]);

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
      <header className="border-b border-line bg-sheet">
        {/* linha 1: marca, navegação e ajuda */}
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-6 py-2.5">
          <div className="flex items-center gap-3">
            <img src={itauLogo} alt="Itaú" width={36} height={36} className="size-9 shrink-0 rounded-[9px] shadow-sm" />
            <span className="h-8 w-px bg-line" aria-hidden />
            <div className="leading-tight">
              <h1 className="largo text-[20px] font-extrabold tracking-tight text-blueprint">Atest.AI</h1>
              <span className="hidden text-[12px] text-muted sm:block">Pré-análise de chamados SETA e SISR</span>
            </div>
          </div>

          <nav data-tour="nav" aria-label="Seções" className="order-3 flex w-full rounded-xl bg-paper p-1 text-[14px] sm:order-none sm:w-auto">
            {([["analysis", "Análise", ScanSearch], ["scenarios", "Cenários", ListChecks], ["validation", "Validação", FlaskConical], ["metrics", "Operação", BarChart3], ["admin", "Configuração", Settings]] as const).map(([v, label, Icon]) => (
              <Tooltip key={v} side="bottom" className="flex flex-1 sm:flex-none" content={SECTION_HINT[v]}>
                <button onClick={() => setView(v)} aria-current={view === v ? "page" : undefined}
                  className={`relative flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 transition-colors sm:flex-none ${view === v ? "bg-sheet font-semibold text-blueprint shadow-sm" : "text-muted hover:text-ink"}`}>
                  <Icon size={16} aria-hidden />{label}
                  {v === "analysis" && running && <span className="absolute right-1 top-1 size-2 rounded-full bg-blueprint pulso" aria-label="análise em andamento" />}
                </button>
              </Tooltip>
            ))}
          </nav>

          <div className="order-2 ml-auto flex items-center gap-2 text-sm sm:order-none">
            {config && (
              <Tooltip side="bottom" content={<>Ambiente de <b>{ENV_NAME[config.environment] ?? config.environment}</b> · versão {config.version}<br />Régua {config.rubric_version} · prompts {config.prompts_version}<br />Configuração {config.signature}</>}>
                <span className={`hidden cursor-help items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-semibold md:flex ${ENV_BADGE[config.environment]?.cls ?? "bg-paper text-muted"}`}>
                  <span className="size-1.5 rounded-full bg-current" />{ENV_BADGE[config.environment]?.label ?? config.environment}
                </span>
              </Tooltip>
            )}
            {config && (
              <Tooltip side="bottom" content={config.api_available ? `Provedores com credencial: ${providerChoices(config).filter((p) => p.available).map((p) => p.label).join(", ")}` : `Nenhum provedor com credencial (${providerChoices(config).map((p) => p.label).join(", ")}): só o modo simulado está disponível`}>
                <span className={`hidden cursor-help items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-semibold lg:flex ${config.api_available ? "bg-[#e3f2ea] text-ok" : "bg-paper text-muted"}`}>
                  {config.api_available ? <Wifi size={13} /> : <WifiOff size={13} />}{config.api_available ? "API conectada" : "Só simulado"}
                </span>
              </Tooltip>
            )}
            <HelpMenu open={helpOpen} setOpen={setHelpOpen}
              tour={() => { setHelpOpen(false); setTourOpen(true); }}
              glossary={() => { setHelpOpen(false); setGlossaryOpen(true); }}
              reset={() => { setHelpOpen(false); resetInfoBoxes(); }} />
          </div>
        </div>

        {/* linha 2: barra de execução (só onde se analisa chamados) */}
        {(view === "analysis" || view === "metrics") && (
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-line/70 bg-paper/50 px-6 py-2 text-sm">
            <fieldset data-tour="mode" className="flex items-center gap-2">
              <legend className="sr-only">Modo</legend>
              <span className="flex items-center gap-1 text-[13px] text-muted">Modo <InfoTip term="mode" /></span>
              <div className="flex rounded-lg border border-line bg-sheet p-0.5">
                <SegmentButton active={mode === "simulated"} onClick={() => setMode("simulated")} hint="Sem custo: respostas simuladas, sem chamar o modelo">Simulado</SegmentButton>
                <SegmentButton active={mode === "api"} onClick={() => setMode("api")} disabled={!config?.api_available}
                  hint={config?.api_available ? `Chama o modelo de verdade${currentChoice ? ` (${currentChoice.label})` : ""}: mede a qualidade real e gera custo` : "Nenhum provedor com credencial: defina em config/.secrets.toml ou no ambiente"}>
                  API</SegmentButton>
              </div>
            </fieldset>
            {mode === "api" && config && (
              <fieldset data-tour="provider" className="flex items-center gap-2">
                <legend className="sr-only">Provedor</legend>
                <span className="flex items-center gap-1 text-[13px] text-muted">Provedor
                  <InfoTip text={<>Quem responde às chamadas de LLM nesta execução. A lista e os modelos de cada provedor ficam em <code>config/settings.toml</code>, seção <code>[panel.providers]</code>.</>} />
                </span>
                <ProviderPicker config={config} value={provider} onChange={chooseProvider} disabled={running} />
              </fieldset>
            )}
            <fieldset data-tour="phase" className="flex items-center gap-2">
              <legend className="sr-only">Fase da régua</legend>
              <span className="flex items-center gap-1 text-[13px] text-muted">Régua <InfoTip term="phase" /></span>
              <div className="flex rounded-lg border border-line bg-sheet p-0.5">
                <SegmentButton active={phase === 1} onClick={() => setPhase(1)} hint="MVP: sem antes, ilegibilidade e reaproveitamento">Fase 1</SegmentButton>
                <SegmentButton active={phase === 2} onClick={() => setPhase(2)} hint="Inclui as checagens da Fase 2">Fase 2</SegmentButton>
              </div>
            </fieldset>
            {mode === "api" && (
              <fieldset className="flex items-center gap-2">
                <legend className="sr-only">Envio</legend>
                <span className="flex items-center gap-1 text-[13px] text-muted">Envio <InfoTip term="batch" /></span>
                <div className="flex rounded-lg border border-line bg-sheet p-0.5">
                  <SegmentButton active={batchMode === "sync"} onClick={() => setBatchMode("sync")} hint="Uma requisição por vez: resultado em segundos">Síncrono</SegmentButton>
                  <SegmentButton active={batchMode === "batch"} onClick={() => setBatchMode("batch")} hint={provider === "anthropic" ? "Envio em lote (Message Batches): assíncrono, metade do custo" : `${currentChoice?.label ?? provider} não tem lote integrado: as chamadas saem síncronas, sem desconto`}>Lote −50%</SegmentButton>
                </div>
              </fieldset>
            )}
            {mode === "api" && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="flex items-center gap-1 text-[13px] text-muted">Modelos
                  <InfoTip text={<><b>Principal</b>: lê o escopo, confere o orçamento e escreve o parecer.<br /><b>Rápido</b>: identifica os anexos e analisa as fotos.<br />Escolha na lista ou digite outro id no formato provedor:modelo.</>} />
                </span>
                <ModelCombobox label="Principal" value={mainModel} onChange={setMainModel} options={providerModels}
                  defaultId={currentChoice?.main ?? config?.main_model} defaultProvider={provider || undefined} availableProviders={config?.keyed_providers}
                  hint="Escopo, orçamento × escopo e parecer: prefira o modelo mais capaz." />
                <ModelCombobox label="Rápido" value={fastModel} onChange={setFastModel} options={providerModels}
                  defaultId={currentChoice?.fast ?? config?.fast_model} defaultProvider={provider || undefined} availableProviders={config?.keyed_providers}
                  hint="Identificação dos anexos e fotos: um modelo mais barato costuma bastar." />
              </div>
            )}

            <div className="ml-auto flex items-center gap-2">
              <Tooltip content="Envie um chamado real ou de teste: dados, planilha de orçamento e fotos">
                <button onClick={() => setShowNewTicket(true)} disabled={!config}
                  className="flex items-center gap-1.5 rounded-lg border border-line bg-sheet px-3 py-1.5 font-medium hover:border-ink/25">
                  <Plus size={16} /> Novo chamado
                </button>
              </Tooltip>
              <Tooltip content={!selected.size ? "Marque ao menos um chamado na lista à esquerda" : running ? "Aguarde a execução atual terminar" : `Analisa no modo ${mode === "api" ? "API" : "simulado"}: ${[...selected].slice(0, 8).join(", ")}${selected.size > 8 ? ` e mais ${selected.size - 8}` : ""}`}>
                <button data-tour="run" onClick={run} disabled={!selected.size || running}
                  className="flex items-center gap-2 rounded-lg bg-blueprint px-4 py-1.5 font-semibold text-white shadow-sm transition-colors hover:bg-[#1d44a0] disabled:pointer-events-none disabled:opacity-50">
                  {running ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
                  {running ? `Analisando ${summary.done}/${summary.total}…` : <>Analisar <span className="rounded-full bg-white/20 px-1.5 text-[12px] tabular-nums">{selected.size}</span></>}
                </button>
              </Tooltip>
            </div>
          </div>
        )}
        {/* dentro do header: a grade da página tem número fixo de linhas */}
        {serverOutdated(config) && (
          <div role="alert" className="border-t border-warn/40 bg-[#fdf6e4] px-6 py-2 text-sm">
            <b className="text-warn">O servidor do painel está desatualizado.</b> Esta tela é de uma versão mais nova do que o servidor em execução: algumas funções (como o login da Configuração) não vão responder.
            Reinicie: pare o processo (Ctrl+C) e rode <code className="rounded bg-sheet px-1">python main.py</code> de novo.
          </div>
        )}
      </header>

      {/* o portal fica montado depois da 1ª visita: rascunhos não se perdem ao consultar outras telas */}
      {adminVisited && (
        <main hidden={view !== "admin"} className="grade row-span-2 min-h-0 overflow-y-auto">
          <AdminView goToValidation={() => setView("validation")} outdated={serverOutdated(config)} />
        </main>
      )}
      {view === "admin" ? null : view === "scenarios" ? (
        <main className="grade row-span-2 min-h-0 overflow-y-auto">
          <ScenariosView tickets={tickets} tags={scenarioTags} datasets={datasets} openTicket={openFromScenarios} selectTickets={selectFromScenarios} />
        </main>
      ) : view === "validation" && config ? (
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
              Execução {execution.id} em modo {execution.mode === "api" ? `API (${execution.models.main}${execution.batch_mode === "batch" ? ", envio em lote" : ""})` : "simulado"}, régua fase {execution.phase}
            </span>
            <span className="tabular-nums">{summary.done} de {summary.total} concluídos</span>
            {Object.entries(summary.byRec).map(([r, n]) => (
              <span key={r} className="flex items-center gap-1.5"><i className="size-2.5 rounded-full" style={{ background: REC[r as Recommendation].color }} />{REC[r as Recommendation].short} {n}</span>
            ))}
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

      <div className={`grid min-h-0 grid-cols-1 transition-[grid-template-columns] duration-200 ${listCollapsed ? "grid-rows-[auto_1fr] md:grid-rows-1 md:grid-cols-[76px_1fr]" : "md:grid-cols-[380px_1fr]"}`}>
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
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                    <span className="text-[15px]">{detail_level.category_label}, {detail_level.symptom_label.toLowerCase()}</span>
                    <Tooltip content={<><b>Tipo de manutenção</b><br />{detail_level.maintenance_type === "preventive" ? "Manutenção programada, para evitar problemas." : "Conserto de um problema que apareceu."}</>}>
                      <span className={`cursor-help rounded-full px-2.5 py-0.5 text-[12px] font-semibold ${detail_level.maintenance_type === "preventive" ? "bg-[#e3f2ea] text-ok" : "bg-[#fdf1dc] text-warn"}`}>
                        {MAINTENANCE_LABEL[detail_level.maintenance_type] ?? detail_level.maintenance_type}
                      </span>
                    </Tooltip>
                  </div>
                </div>
                {focusState && focusState.status !== "done" && focusState.status !== "error" && <StageProgress state={focusState} />}
                {!focusState && savedAssessment && (
                  <span className="text-sm text-muted">Último parecer salvo, de {new Date(savedAssessment.generated_at).toLocaleString("pt-BR")}</span>
                )}
                {focusState?.status === "error" && <span className="text-sm text-bad">{focusState.error}</span>}
              </div>

              <StageTimeline ticket={detail_level} />

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
                        {a.id === "scope" && assessment && assessment.findings.some((f) => f.validation === "scope") && <span className="rounded-full bg-warn px-1.5 text-[11px] text-white" aria-label="apontamentos de escopo">{assessment.findings.filter((f) => f.validation === "scope").length}</span>}
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
                  <AssessmentTab key={`${assessment.ticket_id}-${assessment.record_id ?? assessment.generated_at}`} p={assessment} rubric={rubric}
                    ticket={detail_level} openPhoto={openPhoto} goTo={goTo} openTicket={(id) => { setView("analysis"); setFocus(id); }} />
                </div>
              )}
              {assessment && tab === "scope" && <ScopeTab p={assessment} ticket={detail_level} rubric={rubric} goTo={goTo} />}
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

      {rerunAsk && (
        <RerunDialog saved={rerunAsk} total={marked.length} onClose={() => setRerunAsk(null)}
          useSaved={() => reuseSaved(rerunAsk)} rerun={rerun} />
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

const ENV_BADGE: Record<string, { label: string; cls: string }> = {
  development: { label: "Desenvolvimento", cls: "bg-[#fdf1dc] text-warn" },
  staging: { label: "Homologação", cls: "bg-blueprint-soft text-blueprint" },
  production: { label: "Produção", cls: "bg-[#e3f2ea] text-ok" },
};

const SECTION_HINT = {
  analysis: "Analise chamados um a um e leia o parecer",
  scenarios: "Ache chamados por tipo de problema (escopo vago, orçamento com vários erros...) e analise com um clique",
  validation: "Meça a qualidade do Atest.AI em um conjunto de chamados de teste",
  metrics: "Volume, custo, latência e decisões das pessoas analistas",
  admin: "Checklists, regras e cadastros (acesso com usuário e senha)",
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
        <div role="menu" className="surgir absolute right-0 z-40 mt-2 w-64 rounded-xl border border-line bg-sheet p-1.5 shadow-xl">
          <button role="menuitem" onClick={tour} className={item}><Compass size={16} className="shrink-0 text-blueprint" /><span><b className="block font-medium">Tour guiado</b><span className="text-[12px] text-muted">Passo a passo desta tela</span></span></button>
          <button role="menuitem" onClick={glossary} className={item}><BookOpen size={16} className="shrink-0 text-blueprint" /><span><b className="block font-medium">Glossário</b><span className="text-[12px] text-muted">Score, peso, kappa, F1…</span></span></button>
          <button role="menuitem" onClick={reset} className={item}><RotateCcw size={16} className="shrink-0 text-blueprint" /><span><b className="block font-medium">Reexibir dicas</b><span className="text-[12px] text-muted">Mostra de novo as caixas fechadas</span></span></button>
        </div>
      )}
    </div>
  );
}

/** Passos do tour de cada seção. Passos cujo alvo não está na tela são pulados. */
function buildTour(view: View, a: { toAnalysis: () => void; toAssessment: () => void; hasAssessment: boolean }): TourStep[] {
  const help: TourStep = { target: "help", title: "Ajuda sempre à mão", body: <p>Refaça o tour, abra o glossário ou reexiba as dicas pelo menu <b>Ajuda</b>. Os ícones <b>(i)</b> explicam cada termo.</p> };
  if (view === "admin") {
    return [
      { title: "Configuração", body: <p>Portal para manter as regras do Atest.AI: checklist mínimo por categoria e etapa, regras de apontamento, régua do score e cadastros. O acesso pede usuário e senha.</p> },
      help,
    ];
  }
  if (view === "scenarios") {
    return [
      { title: "Cenários de teste", body: <p>Um chamado por tipo de problema, e os chamados de todos os conjuntos agrupados pelo problema que o gabarito descreve. Clique num chamado para abri-lo na Análise, ou em <b>Selecionar</b> para marcar vários e analisar de uma vez.</p> },
      help,
    ];
  }
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
      { target: "ops-kpis", title: "Operação", body: <p>Tudo o que já passou pelo Atest.AI neste ambiente: volume, custo e valor potencial divergente.</p> },
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
    { target: "nav", title: "Três seções", body: <p><b>Análise</b> para trabalhar chamado a chamado, <b>Validação</b> para medir a qualidade do Atest.AI e <b>Operação</b> para custo e uso.</p> },
    { target: "ticket-list", title: "Lista de chamados", body: <p>Clique num chamado para abri-lo. Marque a caixa de seleção para incluí-lo na próxima análise. Filtre por conjunto e esteira no topo. O botão no canto (ou a tecla <b>[</b>) recolhe a lista para ganhar espaço.</p> },
    { target: "mode", title: "Modo de execução", body: <p><b>Simulado</b> demonstra o fluxo sem custo. <b>API</b> chama o modelo de verdade.</p> },
    { target: "phase", title: "Fase da régua", body: <p>A Fase 2 inclui checagens extras: foto do antes, ilegibilidade e foto reaproveitada.</p> },
    { target: "run", title: "Analisar", body: <p>Roda o pipeline nos chamados marcados: checklist → escopo → orçamento → fotos → score → parecer.</p> },
    { target: "status", title: "Andamento", body: <p>Progresso da execução e quantas recomendações de cada tipo saíram.</p> },
    { target: "tabs", title: "Abas do chamado", body: <p>A <b>Entrada</b> está sempre disponível. As demais abrem depois da análise. Passe o mouse em cada aba para ver o que ela mostra.</p> },
    ...(a.hasAssessment ? [
      { target: "checklist", before: a.toAssessment, title: "1. Checklist mínimo", body: <p>Primeira coisa conferida. Se faltar documento obrigatório, o chamado volta sem score.</p> },
      { target: "verdict", title: "2. Parecer", body: <p>O medidor mostra o score (0 a 100) dentro das faixas da régua e a recomendação, com o motivo e um resumo.</p> },
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
