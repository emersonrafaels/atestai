import { AlertTriangle, BookMarked, ClipboardList, Eraser, History, Home, KeyRound, ListChecks, Loader2, Lock, LogOut, RotateCcw, Save, Search, SlidersHorizontal, Tags, Undo2, UserPlus, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ADMIN_LOGOUT_EVENT, adminApi, adminSession, type AdminHistoryItem, type AdminOverview, type AdminUser, type ChecklistsConfig, type DeleteAssessmentsResult, type RubricConfig } from "../../api";
import { brl, ENV_NAME, MAINTENANCE_LABEL, STAGE_LABEL } from "../../format";
import { AnalysesCleanup } from "./AnalysesCleanup";
import { ChecklistEditor } from "./ChecklistEditor";
import { FindingRulesEditor, ScoreRubricEditor } from "./RulesEditor";
import { InfoBox } from "../ui/InfoBox";
import { PasswordInput } from "../ui/PasswordInput";
import { Tooltip } from "../ui/Tooltip";

type Tab = "home" | "checklists" | "findings" | "score" | "catalog" | "lpu" | "history" | "analyses" | "users";
const TABS: { id: Tab; label: string; icon: typeof Home; group: string }[] = [
  { id: "home", label: "Visão geral", icon: Home, group: "" },
  { id: "checklists", label: "Checklist mínimo", icon: ListChecks, group: "Regras" },
  { id: "findings", label: "Regras de apontamento", icon: ClipboardList, group: "Regras" },
  { id: "score", label: "Régua do score", icon: SlidersHorizontal, group: "Regras" },
  { id: "catalog", label: "Categorias e sintomas", icon: Tags, group: "Cadastros" },
  { id: "lpu", label: "Tabela de preços (LPU)", icon: BookMarked, group: "Cadastros" },
  { id: "history", label: "Histórico de alterações", icon: History, group: "Administração" },
  { id: "analyses", label: "Limpar análises", icon: Eraser, group: "Administração" },
  { id: "users", label: "Usuários e senha", icon: Users, group: "Administração" },
];

/** Portal de configuração: só com login. Rascunhos ficam aqui até "Salvar"; cada gravação pede um motivo e vira versão no histórico. */
export function AdminView({ goToValidation, outdated = false, onAnalysesCleared }: {
  goToValidation: () => void; outdated?: boolean; onAnalysesCleared?: (r: DeleteAssessmentsResult) => void;
}) {
  const [user, setUser] = useState<string | null>(null);
  const [checking, setChecking] = useState(!!adminSession.get());

  useEffect(() => {
    if (!adminSession.get()) return;
    adminApi.me().then((m) => setUser(m.username)).catch(() => setUser(null)).finally(() => setChecking(false));
  }, []);
  useEffect(() => {
    const out = () => setUser(null);
    window.addEventListener(ADMIN_LOGOUT_EVENT, out);
    return () => window.removeEventListener(ADMIN_LOGOUT_EVENT, out);
  }, []);

  if (checking) return <div className="flex h-full items-center justify-center text-muted"><Loader2 className="animate-spin" /></div>;
  if (!user) return <Login onLogin={setUser} outdated={outdated} />;
  return <Portal user={user} onLogout={() => { adminApi.logout().catch(() => undefined); adminSession.clear(); setUser(null); }} goToValidation={goToValidation} onAnalysesCleared={onAnalysesCleared} />;
}

// ============================================================================ login
function Login({ onLogin, outdated }: { onLogin: (u: string) => void; outdated: boolean }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await adminApi.login(username, password);
      adminSession.set(r.token);
      onLogin(r.username);
    } catch (er) {
      const m = (er as Error).message;
      if (/^40[45]\b|not allowed|not found/i.test(m)) setError("OUTDATED");
      else { setError(m); setPassword(""); }
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <form onSubmit={submit} className="surgir w-full max-w-sm rounded-2xl border border-line bg-sheet p-7 shadow-xl">
        <div className="mb-5 flex items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-xl bg-blueprint-soft text-blueprint"><Lock size={20} /></span>
          <div>
            <h2 className="largo text-xl font-bold">Configuração</h2>
            <p className="text-[13px] text-muted">Acesso restrito a quem mantém as regras.</p>
          </div>
        </div>
        <label className="mb-3 block text-sm">
          <span className="mb-1 block font-medium">Usuário</span>
          <input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required
            className="w-full rounded-lg border border-line px-3 py-2 outline-none focus:border-blueprint focus:ring-2 focus:ring-blueprint/15" />
        </label>
        <label className="mb-4 block text-sm">
          <span className="mb-1 block font-medium">Senha</span>
          <PasswordInput autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required
            className="w-full rounded-lg border border-line px-3 py-2 outline-none focus:border-blueprint focus:ring-2 focus:ring-blueprint/15" />
        </label>
        {(outdated || error === "OUTDATED") && (
          <div role="alert" className="mb-3 rounded-md border border-warn/40 bg-[#fdf6e4] px-3 py-2 text-sm">
            <b className="block text-warn">O servidor do painel está desatualizado</b>
            Ele foi iniciado antes desta versão e ainda não tem o login da Configuração. Reinicie o painel: pare o processo (Ctrl+C) e rode <code className="rounded bg-sheet px-1">python main.py</code> de novo.
          </div>
        )}
        {error && error !== "OUTDATED" && <p role="alert" className="mb-3 rounded-md bg-[#fbefed] px-3 py-2 text-sm text-bad">{error}</p>}
        <button type="submit" disabled={busy || !username || !password}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-blueprint py-2 font-semibold text-white hover:bg-[#1d44a0] disabled:opacity-50">
          {busy && <Loader2 size={16} className="animate-spin" />} Entrar
        </button>
        <p className="mt-4 text-center text-[12px] text-muted">A sessão vale por algumas horas e termina ao fechar esta aba.</p>
      </form>
    </div>
  );
}

// ============================================================================ portal
function Portal({ user, onLogout, goToValidation, onAnalysesCleared }: {
  user: string; onLogout: () => void; goToValidation: () => void; onAnalysesCleared?: (r: DeleteAssessmentsResult) => void;
}) {
  const [tab, setTab] = useState<Tab>("home");
  const [ov, setOv] = useState<AdminOverview | null>(null);
  const [rubric, setRubric] = useState<RubricConfig | null>(null);
  const [checklists, setChecklists] = useState<ChecklistsConfig | null>(null);
  const [comment, setComment] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const adopt = useCallback((o: AdminOverview) => {
    setOv(o);
    setRubric(structuredClone(o.sections.rubric.data));
    setChecklists(structuredClone(o.sections.checklists.data));
  }, []);
  useEffect(() => { adminApi.overview().then(adopt).catch((e) => setError((e as Error).message)); }, [adopt]);

  const dirtyRubric = !!ov && !!rubric && JSON.stringify(rubric) !== JSON.stringify(ov.sections.rubric.data);
  const dirtyChecklists = !!ov && !!checklists && JSON.stringify(checklists) !== JSON.stringify(ov.sections.checklists.data);
  const dirty = dirtyRubric || dirtyChecklists;

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      let o = ov!;
      if (dirtyRubric) o = await adminApi.save("rubric", rubric, comment);
      if (dirtyChecklists) o = await adminApi.save("checklists", checklists, comment);
      adopt(o);
      setComment("");
      setSaved(`Alterações salvas. Novas análises já usam a configuração ${o.system.signature}.`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const discard = () => { if (ov) { setRubric(structuredClone(ov.sections.rubric.data)); setChecklists(structuredClone(ov.sections.checklists.data)); setError(null); } };

  if (!ov || !rubric || !checklists) {
    return <div className="flex h-full items-center justify-center gap-2 text-muted">{error ? <span className="text-bad">{error}</span> : <Loader2 className="animate-spin" />}</div>;
  }
  const badge = (t: Tab) => (t === "checklists" && dirtyChecklists) || ((t === "findings" || t === "score") && dirtyRubric);

  return (
    <div className="mx-auto grid max-w-[1320px] gap-6 px-6 py-6 lg:grid-cols-[230px_1fr]">
      {/* menu do portal */}
      <aside className="lg:sticky lg:top-6 lg:h-fit">
        <div className="mb-4 flex items-center justify-between gap-2 rounded-xl border border-line bg-sheet px-3 py-2.5 text-sm">
          <span className="flex min-w-0 items-center gap-2"><span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-blueprint text-[12px] font-bold uppercase text-white">{user[0]}</span><span className="truncate font-medium">{user}</span></span>
          <Tooltip content="Sair do portal"><button onClick={() => { if (!dirty || window.confirm("Há alterações não salvas. Sair mesmo assim?")) onLogout(); }} aria-label="Sair" className="rounded-md p-1 text-muted hover:bg-paper hover:text-ink"><LogOut size={16} /></button></Tooltip>
        </div>
        <nav aria-label="Seções da configuração" className="flex gap-1 overflow-x-auto lg:flex-col">
          {TABS.map((t, i) => (
            <div key={t.id} className="contents">
              {t.group && t.group !== TABS[i - 1]?.group && <span className="mt-3 hidden px-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted lg:block">{t.group}</span>}
              <button onClick={() => setTab(t.id)} aria-current={tab === t.id ? "page" : undefined}
                className={`flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors ${tab === t.id ? "bg-sheet font-semibold text-blueprint shadow-sm ring-1 ring-line" : "text-muted hover:bg-sheet/60 hover:text-ink"}`}>
                <t.icon size={16} className="shrink-0" /><span className="flex-1">{t.label}</span>
                {badge(t.id) && <span className="size-2 rounded-full bg-warn" aria-label="alterações não salvas" />}
              </button>
            </div>
          ))}
        </nav>
      </aside>

      <main className="min-w-0 space-y-5 pb-28">
        <PageTitle tab={tab} ov={ov} />
        {saved && !dirty && (
          <InfoBox tone="tip" title="Configuração atualizada">
            {saved} <button onClick={goToValidation} className="font-medium text-blueprint hover:underline">Rodar a Validação para medir o impacto</button>
          </InfoBox>
        )}
        {tab === "home" && <HomeTab ov={ov} rubric={rubric} checklists={checklists} go={setTab} />}
        {tab === "checklists" && <>
          <SectionStatus ov={ov} section="checklists" onReset={async (c) => adopt(await adminApi.reset("checklists", c))} />
          <ChecklistEditor data={checklists} base={ov.sections.checklists.base} onChange={setChecklists} categories={ov.catalog.categories} />
        </>}
        {tab === "findings" && <>
          <SectionStatus ov={ov} section="rubric" onReset={async (c) => adopt(await adminApi.reset("rubric", c))} />
          <FindingRulesEditor data={rubric} base={ov.sections.rubric.base} onChange={setRubric} />
        </>}
        {tab === "score" && <>
          <SectionStatus ov={ov} section="rubric" onReset={async (c) => adopt(await adminApi.reset("rubric", c))} />
          <ScoreRubricEditor data={rubric} base={ov.sections.rubric.base} onChange={setRubric} />
        </>}
        {tab === "catalog" && <CatalogTab ov={ov} checklists={checklists} />}
        {tab === "lpu" && <LpuTab ov={ov} />}
        {tab === "history" && <HistoryTab onRestored={adopt} dirty={dirty} />}
        {tab === "analyses" && <AnalysesCleanup onCleared={onAnalysesCleared} />}
        {tab === "users" && <UsersTab me={user} />}
      </main>

      {/* barra de salvar: aparece quando há rascunho */}
      {dirty && (
        <div className="surgir fixed inset-x-0 bottom-9 z-30 flex justify-center px-4">
          <div className="flex w-full max-w-4xl flex-wrap items-center gap-3 rounded-2xl border border-line bg-sheet p-3 shadow-2xl">
            <span className="flex items-center gap-2 text-sm font-semibold"><span className="size-2 rounded-full bg-warn pulso" />Alterações não salvas
              <span className="font-normal text-muted">({[dirtyChecklists && "checklist", dirtyRubric && "régua e regras"].filter(Boolean).join(" e ")})</span></span>
            <input value={comment} onChange={(e) => setComment(e.target.value)} maxLength={500} placeholder="Motivo da alteração (obrigatório, vai para o histórico)"
              className="min-w-56 flex-1 rounded-lg border border-line px-3 py-1.5 text-sm outline-none focus:border-blueprint" />
            <button onClick={discard} disabled={saving} className="flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-paper"><Undo2 size={15} /> Descartar</button>
            <Tooltip content={!comment.trim() ? "Descreva o motivo para salvar" : "Novas análises passam a usar esta configuração"}>
              <button onClick={save} disabled={saving || !comment.trim()} className="flex items-center gap-1.5 rounded-lg bg-blueprint px-4 py-1.5 text-sm font-semibold text-white hover:bg-[#1d44a0] disabled:pointer-events-none disabled:opacity-50">
                {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />} Salvar
              </button>
            </Tooltip>
            {error && <p role="alert" className="w-full rounded-md bg-[#fbefed] px-3 py-1.5 text-sm text-bad">{error}</p>}
          </div>
        </div>
      )}
    </div>
  );
}

function PageTitle({ tab, ov }: { tab: Tab; ov: AdminOverview }) {
  const t = TABS.find((x) => x.id === tab)!;
  const sub: Record<Tab, string> = {
    home: "Resumo da configuração em uso e dos cadastros.",
    checklists: "Documentos obrigatórios por categoria, tipo de manutenção e etapa da esteira.",
    findings: "Verificações que geram apontamentos: ativar, desativar e ajustar a severidade.",
    score: "Como os apontamentos viram score e recomendação.",
    catalog: "Categorias e sintomas reconhecidos pelo Atest.AI e onde cada um é usado.",
    lpu: "Preços de referência usados na conferência do orçamento.",
    history: "Todas as gravações feitas pelo portal, com autor e motivo. Dá para voltar a qualquer versão.",
    analyses: "Apague pareceres já emitidos: todos de uma vez ou só os escolhidos.",
    users: "Quem pode entrar no portal.",
  };
  return (
    <div className="flex flex-wrap items-end justify-between gap-2">
      <div>
        <h2 className="largo flex items-center gap-2 text-[26px] font-bold"><t.icon size={24} className="text-blueprint" />{t.label}</h2>
        <p className="text-sm text-muted">{sub[tab]}</p>
      </div>
      <Tooltip content={`Régua ${ov.system.rubric_version} · prompts ${ov.system.prompts_version}`}>
        <span className="cursor-help rounded-full bg-paper px-2.5 py-1 font-mono text-[12px] text-muted ring-1 ring-line">config {ov.system.signature}</span>
      </Tooltip>
    </div>
  );
}

function SectionStatus({ ov, section, onReset }: { ov: AdminOverview; section: "rubric" | "checklists"; onReset: (comment: string) => Promise<void> }) {
  const s = ov.sections[section];
  if (!s.overridden) return <p className="text-[13px] text-muted">Usando o padrão dos arquivos de configuração (config/{section === "rubric" ? "rubric.toml" : "checklists.toml"}).</p>;
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-blueprint/20 bg-blueprint-soft/50 px-3 py-2 text-[13px]">
      <span>Personalizado pelo portal (versão #{s.version_id}). O arquivo config/{section === "rubric" ? "rubric.toml" : "checklists.toml"} continua como padrão.</span>
      <button onClick={async () => { const c = window.prompt("Motivo para voltar ao padrão dos arquivos:"); if (c?.trim()) await onReset(c); }}
        className="flex items-center gap-1 font-medium text-blueprint hover:underline"><RotateCcw size={13} /> Restaurar padrão</button>
    </div>
  );
}

// ---------------------------------------------------------------------------- visão geral
function HomeTab({ ov, rubric, checklists, go }: { ov: AdminOverview; rubric: RubricConfig; checklists: ChecklistsConfig; go: (t: Tab) => void }) {
  const types = Object.values(rubric.finding_types);
  const offTypes = Object.entries(rubric.finding_types).filter(([, f]) => !f.enabled);
  const offRules = checklists.rules.filter((r) => !r.enabled);
  const offReqs = checklists.rules.flatMap((r) => r.requirements.filter((q) => !q.enabled).map((q) => ({ r, q })));
  const covered = new Set(checklists.rules.filter((r) => r.enabled).map((r) => r.category));
  const noSpecific = ov.catalog.categories.filter((c) => !covered.has(c.value));
  const custom = ov.system.signature !== ov.system.base_signature;
  const cards = [
    { t: "checklists" as Tab, label: "Regras de checklist", value: `${checklists.rules.length - offRules.length}/${checklists.rules.length}`, sub: "ativas" },
    { t: "findings" as Tab, label: "Regras de apontamento", value: `${types.length - offTypes.length}/${types.length}`, sub: "ativas" },
    { t: "catalog" as Tab, label: "Categorias", value: String(ov.catalog.categories.length), sub: `${ov.catalog.symptoms.length} sintomas` },
    { t: "lpu" as Tab, label: "Itens na LPU", value: String(Object.values(ov.lpu).reduce((s, l) => s + l.length, 0)), sub: Object.keys(ov.lpu).join(" · ") },
  ];
  return (
    <div className="space-y-5">
      <section className={`rounded-xl border-2 p-5 ${custom ? "border-blueprint/30 bg-blueprint-soft/40" : "border-line bg-sheet"}`}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold">{custom ? "Configuração personalizada pelo portal" : "Configuração padrão dos arquivos"}</h3>
            <p className="text-sm text-muted">
              Régua <b className="text-ink">{ov.system.rubric_version}</b> · prompts {ov.system.prompts_version} · fase padrão {ov.system.phase} · ambiente {ENV_NAME[ov.system.environment] ?? ov.system.environment}
            </p>
            <p className="mt-1 text-[13px] text-muted">A assinatura <span className="font-mono">{ov.system.signature}</span> fica gravada em cada parecer: dá para saber com quais regras ele saiu.</p>
          </div>
          <div className="text-right text-[13px] text-muted">Modelos: {ov.system.main_model} · {ov.system.fast_model}</div>
        </div>
      </section>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((c) => (
          <button key={c.label} onClick={() => go(c.t)} className="rounded-xl border border-line bg-sheet p-4 text-left transition-colors hover:border-blueprint/40">
            <div className="text-[13px] text-muted">{c.label}</div>
            <div className="largo text-[26px] font-bold tabular-nums">{c.value}</div>
            <div className="text-[12px] text-muted">{c.sub}</div>
          </button>
        ))}
      </div>

      <section className="rounded-xl border border-line bg-sheet p-5">
        <h3 className="mb-2 font-semibold">Pontos de atenção</h3>
        <ul className="space-y-1.5 text-sm">
          {offTypes.map(([k, f]) => <Attention key={k} onClick={() => go("findings")}>Regra de apontamento desativada: <b>{f.description}</b></Attention>)}
          {offRules.map((r) => <Attention key={`${r.category}${r.maintenance}${r.moment}`} onClick={() => go("checklists")}>Regra de checklist desativada: <b>{catName(ov, r.category)}</b> · {r.maintenance === "*" ? "qualquer tipo" : MAINTENANCE_LABEL[r.maintenance]} · {r.moment === "*" ? "qualquer etapa" : STAGE_LABEL[r.moment]}</Attention>)}
          {offReqs.map(({ r, q }) => <Attention key={`${r.category}${r.moment}${q.id}`} onClick={() => go("checklists")}>Exigência desativada em {catName(ov, r.category)}: <b>{q.description}</b></Attention>)}
          {noSpecific.length > 0 && <Attention onClick={() => go("checklists")} tone="info">Sem regra específica (usam a regra geral): {noSpecific.map((c) => c.label).join(", ")}</Attention>}
          {!offTypes.length && !offRules.length && !offReqs.length && <li className="text-muted">Todas as regras e exigências estão ativas.</li>}
        </ul>
      </section>

      <InfoBox title="Como as alterações funcionam">
        Os ajustes valem para <b>novas análises</b> assim que você salva; pareceres já emitidos não mudam. Cada gravação pede um motivo e vira uma versão no histórico,
        com opção de voltar. Os arquivos em <span className="font-mono">config/</span> continuam sendo o padrão de fábrica.
      </InfoBox>
    </div>
  );
}

const catName = (ov: AdminOverview, v: string) => (v === "*" ? "Qualquer categoria" : ov.catalog.categories.find((c) => c.value === v)?.label ?? v);

function Attention({ children, onClick, tone = "warn" }: { children: React.ReactNode; onClick: () => void; tone?: "warn" | "info" }) {
  return (
    <li>
      <button onClick={onClick} className={`flex w-full items-start gap-2 rounded-md px-2 py-1 text-left hover:bg-paper ${tone === "warn" ? "" : "text-muted"}`}>
        <AlertTriangle size={14} className={`mt-0.5 shrink-0 ${tone === "warn" ? "text-warn" : "text-muted"}`} /><span>{children}</span>
      </button>
    </li>
  );
}

// ---------------------------------------------------------------------------- categorias e sintomas
function CatalogTab({ ov, checklists }: { ov: AdminOverview; checklists: ChecklistsConfig }) {
  const symLabel = (v: string) => ov.catalog.symptoms.find((s) => s.value === v)?.label ?? v;
  return (
    <div className="space-y-5">
      <InfoBox id="admin-catalog">
        Categorias e sintomas vêm do cadastro do chamado (Salesforce) e estão fixados no código do Atest.AI. Para incluir um novo, peça ao time DataCraft;
        depois de incluído, ele aparece aqui e pode ganhar regras de checklist próprias.
      </InfoBox>
      <section className="overflow-hidden rounded-xl border border-line bg-sheet">
        <h3 className="border-b border-line px-5 py-3 font-semibold">Categorias ({ov.catalog.categories.length})</h3>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="bg-paper/60 text-left text-[12px] text-muted">
              <tr><th className="px-5 py-2 font-medium">Categoria</th><th className="px-3 py-2 text-right font-medium">Chamados</th><th className="px-3 py-2 font-medium">Regras de checklist</th><th className="px-5 py-2 font-medium">Sintomas usados</th></tr>
            </thead>
            <tbody>
              {ov.catalog.categories.map((c) => {
                const rules = checklists.rules.filter((r) => r.category === c.value);
                return (
                  <tr key={c.value} className="border-t border-line/70 align-top">
                    <td className="px-5 py-2.5"><div className="font-medium">{c.label}</div><div className="font-mono text-[11px] text-muted">{c.value}</div></td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{c.tickets}</td>
                    <td className="px-3 py-2.5">
                      <div className="flex flex-wrap gap-1">
                        {rules.length ? rules.map((r) => (
                          <span key={`${r.maintenance}${r.moment}`} className={`rounded px-1.5 text-[12px] ${r.enabled ? "bg-blueprint-soft text-blueprint" : "bg-paper text-muted line-through"}`}>
                            {r.maintenance === "*" ? "" : `${MAINTENANCE_LABEL[r.maintenance]} · `}{r.moment === "*" ? "qualquer etapa" : STAGE_LABEL[r.moment]} ({r.requirements.filter((q) => q.enabled).length})
                          </span>
                        )) : <span className="text-[12px] text-muted">usa a regra geral</span>}
                      </div>
                    </td>
                    <td className="px-5 py-2.5 text-[13px] text-muted">{c.symptoms_seen.length ? c.symptoms_seen.map(symLabel).join(", ") : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
      <section className="overflow-hidden rounded-xl border border-line bg-sheet">
        <h3 className="border-b border-line px-5 py-3 font-semibold">Sintomas ({ov.catalog.symptoms.length})</h3>
        <table className="w-full text-sm">
          <thead className="bg-paper/60 text-left text-[12px] text-muted"><tr><th className="px-5 py-2 font-medium">Sintoma</th><th className="px-3 py-2 font-medium">Código</th><th className="px-5 py-2 text-right font-medium">Chamados</th></tr></thead>
          <tbody>
            {ov.catalog.symptoms.map((s) => (
              <tr key={s.value} className="border-t border-line/70"><td className="px-5 py-2 font-medium">{s.label}</td><td className="px-3 py-2 font-mono text-[12px] text-muted">{s.value}</td><td className="px-5 py-2 text-right tabular-nums">{s.tickets}</td></tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------- LPU
function LpuTab({ ov }: { ov: AdminOverview }) {
  const streams = Object.keys(ov.lpu);
  const [ws, setWs] = useState(streams[0]);
  const [q, setQ] = useState("");
  const rows = (ov.lpu[ws] ?? []).filter((r) => !q || `${r.code} ${r.description}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="space-y-4">
      <InfoBox id="admin-lpu">Tabela de referência usada para apontar <b>preço acima da referência</b>. Ela vem dos arquivos <span className="font-mono">data/references/lpu_*.csv</span>; a tolerância fica em Régua do score.</InfoBox>
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex rounded-lg bg-paper p-0.5 text-sm">
          {streams.map((s) => <button key={s} onClick={() => setWs(s)} className={`rounded-md px-3 py-1 ${ws === s ? "bg-sheet font-semibold shadow-sm" : "text-muted"}`}>{s} ({ov.lpu[s].length})</button>)}
        </div>
        <label className="flex items-center gap-1.5 rounded-md border border-line bg-sheet px-2 py-1.5 text-sm"><Search size={14} className="text-muted" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Código ou descrição" className="w-56 bg-transparent outline-none" /></label>
      </div>
      <div className="overflow-x-auto rounded-xl border border-line bg-sheet">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="bg-paper/60 text-left text-[12px] text-muted"><tr><th className="px-5 py-2 font-medium">Código</th><th className="px-3 py-2 font-medium">Descrição</th><th className="px-3 py-2 font-medium">Unidade</th><th className="px-5 py-2 text-right font-medium">Preço de referência</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.code} className="border-t border-line/70"><td className="px-5 py-2 font-mono text-[12px]">{r.code}</td><td className="px-3 py-2">{r.description}</td><td className="px-3 py-2">{r.unit}</td><td className="px-5 py-2 text-right tabular-nums">{brl(r.reference_price)}</td></tr>)}</tbody>
        </table>
        {!rows.length && <p className="p-6 text-center text-sm text-muted">Nada encontrado.</p>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------- histórico
function HistoryTab({ onRestored, dirty }: { onRestored: (o: AdminOverview) => void; dirty: boolean }) {
  const [items, setItems] = useState<AdminHistoryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => adminApi.history().then(setItems).catch((e) => setError((e as Error).message)), []);
  useEffect(() => { load(); }, [load]);
  const latest = useMemo(() => {
    const m: Record<string, number> = {};
    (items ?? []).forEach((h) => { if (!(h.section in m)) m[h.section] = h.id; });
    return m;
  }, [items]);
  const restore = async (h: AdminHistoryItem) => {
    if (dirty && !window.confirm("Há alterações não salvas que serão descartadas. Continuar?")) return;
    const c = window.prompt(`Motivo para restaurar a versão #${h.id}:`, `Restaurou a versão #${h.id}`);
    if (!c?.trim()) return;
    try { onRestored(await adminApi.restore(h.id, c)); load(); } catch (e) { setError((e as Error).message); }
  };
  if (error) return <p className="text-bad">{error}</p>;
  if (!items) return <Loader2 className="animate-spin text-muted" />;
  if (!items.length) return <p className="rounded-xl border border-dashed border-line bg-sheet p-8 text-center text-muted">Nenhuma alteração feita pelo portal ainda: a configuração em uso é a dos arquivos.</p>;
  return (
    <ol className="relative space-y-3 border-l-2 border-line pl-5">
      {items.map((h) => (
        <li key={h.id} className="relative rounded-xl border border-line bg-sheet p-4">
          <span className={`absolute -left-[27px] top-5 size-3 rounded-full ring-4 ring-paper ${latest[h.section] === h.id ? "bg-blueprint" : "bg-line"}`} />
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <b>#{h.id}</b>
                <span className="rounded bg-paper px-1.5 text-[12px] font-medium">{h.section === "rubric" ? "Régua e regras" : "Checklist"}</span>
                {latest[h.section] === h.id && <span className="rounded bg-blueprint px-1.5 text-[11px] font-semibold uppercase text-white">em uso</span>}
                {h.is_default && <span className="rounded bg-paper px-1.5 text-[11px] font-semibold uppercase text-muted">padrão dos arquivos</span>}
              </div>
              <div className="text-[13px] text-muted">{h.author} · {new Date(h.created_at).toLocaleString("pt-BR")}</div>
            </div>
            {latest[h.section] !== h.id && !h.is_default && (
              <button onClick={() => restore(h)} className="flex items-center gap-1 rounded-lg border border-line px-2.5 py-1 text-[13px] font-medium hover:bg-paper"><RotateCcw size={13} /> Restaurar esta versão</button>
            )}
          </div>
          <p className="mt-2 text-sm italic">“{h.comment}”</p>
          <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-[13px] text-ink/80">{h.summary.map((s, k) => <li key={k}>{s}</li>)}</ul>
        </li>
      ))}
    </ol>
  );
}

// ---------------------------------------------------------------------------- usuários
function UsersTab({ me }: { me: string }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [nu, setNu] = useState({ username: "", password: "" });
  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { adminApi.users().then(setUsers).catch(() => setUsers([])); }, []);
  const addUser = async (e: React.FormEvent) => {
    e.preventDefault();
    try { setUsers(await adminApi.addUser(nu.username, nu.password)); setMsg({ ok: true, text: `Usuário ${nu.username} criado. Passe a senha por um canal seguro.` }); setNu({ username: "", password: "" }); }
    catch (er) { setMsg({ ok: false, text: (er as Error).message }); }
  };
  const changePw = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pw.next !== pw.confirm) return setMsg({ ok: false, text: "A confirmação não confere com a nova senha." });
    try { await adminApi.changePassword(pw.current, pw.next); setMsg({ ok: true, text: "Senha alterada. Entre de novo com a nova senha." }); setPw({ current: "", next: "", confirm: "" }); adminSession.clear(); setTimeout(() => window.dispatchEvent(new Event(ADMIN_LOGOUT_EVENT)), 1500); }
    catch (er) { setMsg({ ok: false, text: (er as Error).message }); }
  };
  const input = "w-full rounded-lg border border-line px-3 py-1.5 text-sm outline-none focus:border-blueprint";
  return (
    <div className="space-y-5">
      {msg && <p role="status" className={`rounded-lg px-3 py-2 text-sm ${msg.ok ? "bg-[#e3f2ea] text-ok" : "bg-[#fbefed] text-bad"}`}>{msg.text}</p>}
      <section className="overflow-hidden rounded-xl border border-line bg-sheet">
        <h3 className="border-b border-line px-5 py-3 font-semibold">Usuários com acesso ({users?.length ?? "…"})</h3>
        <table className="w-full text-sm">
          <thead className="bg-paper/60 text-left text-[12px] text-muted"><tr><th className="px-5 py-2 font-medium">Usuário</th><th className="px-3 py-2 font-medium">Criado</th><th className="px-5 py-2 font-medium">Último acesso</th></tr></thead>
          <tbody>
            {(users ?? []).map((u) => (
              <tr key={u.username} className="border-t border-line/70">
                <td className="px-5 py-2 font-medium">{u.username}{u.username === me && <span className="ml-2 rounded bg-blueprint-soft px-1.5 text-[11px] text-blueprint">você</span>}</td>
                <td className="px-3 py-2 text-muted">{new Date(u.created_at).toLocaleDateString("pt-BR")}{u.created_by ? ` por ${u.created_by === "config" ? "configuração inicial" : u.created_by}` : ""}</td>
                <td className="px-5 py-2 text-muted">{u.last_login ? new Date(u.last_login).toLocaleString("pt-BR") : "nunca"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <div className="grid gap-5 md:grid-cols-2">
        <form onSubmit={addUser} className="space-y-3 rounded-xl border border-line bg-sheet p-5">
          <h3 className="flex items-center gap-2 font-semibold"><UserPlus size={17} className="text-blueprint" /> Novo usuário</h3>
          <input value={nu.username} onChange={(e) => setNu({ ...nu, username: e.target.value.toLowerCase() })} placeholder="usuário (minúsculas)" autoComplete="off" className={input} />
          <PasswordInput value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} placeholder="senha inicial (8+ caracteres, letras e números)" autoComplete="new-password" className={input} />
          <button disabled={!nu.username || !nu.password} className="rounded-lg bg-blueprint px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-50">Criar usuário</button>
        </form>
        <form onSubmit={changePw} className="space-y-3 rounded-xl border border-line bg-sheet p-5">
          <h3 className="flex items-center gap-2 font-semibold"><KeyRound size={17} className="text-blueprint" /> Trocar minha senha</h3>
          <PasswordInput value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} placeholder="senha atual" autoComplete="current-password" className={input} />
          <PasswordInput value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} placeholder="nova senha" autoComplete="new-password" className={input} />
          <PasswordInput value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} placeholder="repita a nova senha" autoComplete="new-password" className={input} />
          {pw.confirm && pw.next !== pw.confirm && <p className="text-[12px] text-bad">A confirmação não confere com a nova senha.</p>}
          <button disabled={!pw.current || !pw.next || !pw.confirm} className="rounded-lg bg-blueprint px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-50">Trocar senha</button>
          <p className="text-[12px] text-muted">Ao trocar, as outras sessões abertas com o seu usuário são encerradas.</p>
        </form>
      </div>
    </div>
  );
}
