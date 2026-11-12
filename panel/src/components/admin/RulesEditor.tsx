import { ChevronDown, Lock, RotateCcw, ShieldAlert } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { FindingTypeConfig, RubricConfig } from "../../api";
import { pts, REC, SEVERITY, VALIDATIONS, VALIDATION_LABEL, VALIDATION_SHORT } from "../../format";
import { BandScale } from "../ScoreBreakdown";
import { InfoBox } from "../ui/InfoBox";
import { Switch } from "../ui/Switch";
import { InfoTip } from "../ui/Tooltip";

interface Props {
  data: RubricConfig;
  base: RubricConfig;
  onChange: (next: RubricConfig) => void;
}

const AMOUNT: Record<string, string> = { item: "Linha inteira", excess: "Só o excedente", none: "—" };
const SEVERITIES = ["critical", "high", "medium", "low"] as const;
type WsView = "all" | "SETA" | "SISR";
type Override = NonNullable<FindingTypeConfig["by_workstream"]>["SETA"];

/** O tipo como vale na esteira: o padrão com o ajuste da esteira por cima. */
const effectiveFor = (f: FindingTypeConfig, ws: WsView): FindingTypeConfig => {
  if (ws === "all") return f;
  const o = f.by_workstream?.[ws];
  return { ...f, enabled: o?.enabled ?? f.enabled, severity: o?.severity ?? f.severity };
};
const overrideText = (f: FindingTypeConfig) =>
  (["SETA", "SISR"] as const).flatMap((w) => {
    const o = f.by_workstream?.[w];
    if (!o || (o.enabled == null && o.severity == null)) return [];
    const parts = [o.enabled === false ? "desativada" : o.enabled === true ? "ativa" : "", o.severity ? SEVERITY[o.severity].label.toLowerCase() : ""].filter(Boolean);
    return [`${w}: ${parts.join(", ")}`];
  });

/** Tipos de apontamento: ativar/desativar e ajustar severidade, fase, trava e redução de confiança. */
export function FindingRulesEditor({ data, base, onChange }: Props) {
  const total = VALIDATIONS.reduce((s, v) => s + data.weights[v], 0) || 100;
  const [ws, setWs] = useState<WsView>("all");
  const set = (kind: string, patch: Partial<FindingTypeConfig>) =>
    onChange({ ...data, finding_types: { ...data.finding_types, [kind]: { ...data.finding_types[kind], ...patch } } });
  /** Ajuste na esteira escolhida: valor igual ao padrão vira "segue o padrão" (null); sem ajuste, a esteira sai. */
  const setOverride = (kind: string, patch: Partial<NonNullable<Override>>) => {
    if (ws === "all") return;
    const f = data.finding_types[kind];
    const cur = { enabled: null, severity: null, ...(f.by_workstream?.[ws] ?? {}), ...patch } as NonNullable<Override>;
    if (cur.enabled === f.enabled) cur.enabled = null;
    if (cur.severity === f.severity) cur.severity = null;
    const by = { ...(f.by_workstream ?? {}) };
    if (cur.enabled == null && cur.severity == null) delete by[ws];
    else by[ws] = cur;
    set(kind, { by_workstream: by });
  };
  const clearOverride = (kind: string) => {
    if (ws === "all") return;
    const by = { ...(data.finding_types[kind].by_workstream ?? {}) };
    delete by[ws];
    set(kind, { by_workstream: by });
  };
  const entries = Object.entries(data.finding_types).map(([k, f]) => [k, effectiveFor(f, ws)] as [string, FindingTypeConfig]);
  const off = entries.filter(([, f]) => !f.enabled).length;
  const wsOnly = ws === "all" ? "" : "Este ajuste vale para todas as esteiras: troque para “Padrão” para mudar";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex rounded-lg bg-paper p-0.5 text-sm" role="radiogroup" aria-label="Esteira">
          {([["all", "Padrão (todas as esteiras)"], ["SETA", "SETA"], ["SISR", "SISR"]] as [WsView, string][]).map(([v, l]) => (
            <button key={v} role="radio" aria-checked={ws === v} onClick={() => setWs(v)}
              className={`rounded-md px-3 py-1 ${ws === v ? "bg-sheet font-semibold shadow-sm" : "text-muted hover:text-ink"}`}>{l}</button>
          ))}
        </div>
        <p className="text-sm text-muted">{ws === "all" ? "" : `Na esteira ${ws}: `}{entries.length - off} de {entries.length} regras ativas{off ? ` · ${off} desativada${off === 1 ? "" : "s"}` : ""}.</p>
      </div>
      {ws !== "all" && (
        <p className="rounded-lg border border-blueprint/20 bg-blueprint-soft/50 px-3 py-2 text-[13px]">
          Você está ajustando só a esteira <b>{ws}</b>: dá para ativar, desativar e mudar a severidade de cada regra para os chamados {ws}.
          O que não for ajustado segue o padrão. Fase, trava, confiança e absorção valem para todas as esteiras.
        </p>
      )}

      {VALIDATIONS.map((v) => (
        <section key={v} className="overflow-hidden rounded-xl border border-line bg-sheet">
          <h3 className="flex items-baseline justify-between border-b border-line px-5 py-3 font-semibold">
            {VALIDATION_LABEL[v]} <span className="text-[13px] font-normal text-muted">peso {data.weights[v]}% no score</span>
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] text-sm">
              <thead className="bg-paper/60 text-left text-[12px] text-muted">
                <tr>
                  <Th tip={COLUMN_HELP.enabled} className="w-14 px-4">Ativa</Th>
                  <Th tip={COLUMN_HELP.rule}>Regra</Th>
                  <Th tip={COLUMN_HELP.severity}>Severidade</Th>
                  <Th tip={COLUMN_HELP.effect} className="text-right" justify="justify-end">Efeito no score</Th>
                  <Th tip={COLUMN_HELP.phase}>Fase</Th>
                  <Th tip={COLUMN_HELP.lock} className="text-center" justify="justify-center">Trava</Th>
                  <Th tip={COLUMN_HELP.confidence} className="text-center" justify="justify-center">Reduz confiança</Th>
                  <Th tip={COLUMN_HELP.absorbs}>Absorve</Th>
                  <Th tip={COLUMN_HELP.amount} className="px-4">Valor divergente</Th>
                </tr>
              </thead>
              <tbody>
                {entries.filter(([, f]) => f.validation === v).map(([kind, f]) => {
                  const raw = data.finding_types[kind];
                  const b = base.finding_types[kind];
                  const changed = JSON.stringify(b) !== JSON.stringify(raw);
                  const wsAdjusted = ws !== "all" && !!raw.by_workstream?.[ws];
                  const notes = ws === "all" ? overrideText(raw) : [];
                  const effect = (data.discount_by_severity[f.severity] * data.weights[v]) / total;
                  return (
                    <tr key={kind} className={`border-t border-line/70 ${!f.enabled ? "bg-paper/50 text-muted" : changed ? "bg-[#fffaf0]" : ""}`}>
                      <td className="px-4 py-2"><Switch on={f.enabled} onChange={(on) => (ws === "all" ? set(kind, { enabled: on }) : setOverride(kind, { enabled: on }))} label={`${f.description}: ${f.enabled ? "ativa" : "desativada"}`} /></td>
                      <td className="px-2 py-2">
                        <div className={`font-medium ${f.enabled ? "" : "line-through"}`}>{f.description}</div>
                        {((changed && ws === "all") || wsAdjusted) && (
                          <div className="flex items-center gap-2 text-[11px]">
                            {changed && ws === "all" && (
                              <button onClick={() => set(kind, b)} className="flex items-center gap-0.5 text-warn hover:underline"><RotateCcw size={11} /> desfazer</button>
                            )}
                            {wsAdjusted && (
                              <button onClick={() => clearOverride(kind)} className="flex items-center gap-0.5 text-blueprint hover:underline"><RotateCcw size={11} /> usar o padrão</button>
                            )}
                          </div>
                        )}
                        {wsAdjusted && <span className="mt-0.5 inline-block rounded bg-blueprint-soft px-1.5 text-[11px] font-medium text-blueprint">ajustada para {ws}</span>}
                        {notes.map((n) => <span key={n} className="mr-1 mt-0.5 inline-block rounded bg-paper px-1.5 text-[11px] text-muted ring-1 ring-line">{n}</span>)}
                      </td>
                      <td className="px-2 py-2">
                        <select value={f.severity} disabled={!f.enabled}
                          onChange={(e) => { const sev = e.target.value as FindingTypeConfig["severity"]; if (ws === "all") set(kind, { severity: sev }); else setOverride(kind, { severity: sev }); }}
                          className="rounded-md border border-line bg-sheet px-1.5 py-1 font-medium" style={{ color: SEVERITY[f.severity].color }}>
                          {SEVERITIES.map((s) => <option key={s} value={s}>{SEVERITY[s].label} (−{data.discount_by_severity[s]})</option>)}
                        </select>
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">{f.enabled ? <span className="font-semibold text-bad">−{pts(effect)}</span> : "—"}</td>
                      <td className="px-2 py-2">
                        <select value={f.phase} disabled={!f.enabled || ws !== "all"} title={wsOnly} onChange={(e) => set(kind, { phase: Number(e.target.value) })} className="rounded-md border border-line bg-sheet px-1.5 py-1">
                          <option value={1}>Fase 1</option><option value={2}>Fase 2</option>
                        </select>
                      </td>
                      <td className="px-2 py-2 text-center"><span className="inline-flex items-center gap-1"><Switch size="sm" on={f.lock} disabled={!f.enabled || ws !== "all"} onChange={(on) => set(kind, { lock: on })} label="Trava" />{f.lock && <Lock size={12} className="text-lock" />}</span></td>
                      <td className="px-2 py-2 text-center"><span className="inline-flex items-center gap-1"><Switch size="sm" on={f.reduces_confidence} disabled={!f.enabled || ws !== "all"} onChange={(on) => set(kind, { reduces_confidence: on })} label="Reduz confiança" />{f.reduces_confidence && <ShieldAlert size={12} className="text-muted" />}</span></td>
                      <td className="px-2 py-2">
                        <Absorbs name={f.description} value={f.absorbs ?? []} disabled={!f.enabled || ws !== "all"}
                          options={entries.filter(([k, o]) => k !== kind && o.validation === v).map(([k, o]) => ({ kind: k, label: o.description }))}
                          onChange={(absorbs) => set(kind, { absorbs })} />
                      </td>
                      <td className="px-4 py-2 text-[12px] text-muted">{AMOUNT[f.amount_at_issue] ?? f.amount_at_issue}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}

/** Explicação de cada coluna da tabela de regras (ícone ao lado do nome). */
const COLUMN_HELP: Record<string, React.ReactNode> = {
  enabled: "Desligada, a verificação não é feita: não gera apontamento, não desconta e não entra no valor divergente.",
  rule: "Cada linha é uma verificação que o Atest.AI faz no chamado. Quando ela encontra um problema, gera um apontamento, que tira pontos do score.",
  severity: "Quanto o apontamento tira da nota da validação (Escopo, Orçamento ou Fotos). O número entre parênteses é o desconto.",
  effect: "Quanto sai do score final (0 a 100): o desconto da severidade multiplicado pelo peso da validação. Ex.: −35 numa validação com peso 40% tira 14 pontos.",
  phase: "Fase 1 vale desde já; Fase 2 só conta quando a análise roda na Fase 2.",
  lock: "Ligada, o apontamento devolve o chamado ao fornecedor qualquer que seja o score (ex.: foto reaproveitada de outro chamado).",
  confidence: "O apontamento indica que faltou informação para concluir. Um redutor deixa a confiança média; dois mandam o chamado para análise detalhada.",
  absorbs: <>Evita punir duas vezes o mesmo problema. Se esta regra e uma das marcadas aparecem juntas no mesmo chamado, só esta desconta; a outra continua no parecer como evidência.
    <span className="mt-1 block">Ex.: <i>Sem foto do serviço concluído</i> absorve <i>Foto não corresponde ao escopo</i>, porque a foto de outro ambiente é justamente o motivo de faltar a prova do serviço. Só dá para marcar regras da mesma validação.</span></>,
  amount: "Quanto do orçamento entra no valor potencial divergente quando o apontamento aparece: a linha inteira, só o excedente ou nada. É definido no código.",
};

/** Cabeçalho de coluna com o ícone de ajuda (ⓘ) ao lado do nome. */
function Th({ children, tip, className = "px-2", justify = "" }: { children: string; tip: React.ReactNode; className?: string; justify?: string }) {
  return (
    <th className={`py-2 font-medium ${className}`}>
      <span className={`inline-flex items-center gap-1 ${justify}`}>
        {children}
        <InfoTip size={12} label={`O que é “${children}”?`} text={<><b className="mb-0.5 block">{children}</b>{tip}</>} />
      </span>
    </th>
  );
}

/** Tipos que este absorve: botão com o resumo que abre a lista de marcação flutuando sobre a página
 * (fora da tabela, que tem rolagem horizontal e cortava a lista), sempre dentro da área visível. */
function Absorbs({ name, value, options, disabled, onChange }: { name: string; value: string[]; options: { kind: string; label: string }[]; disabled: boolean; onChange: (v: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const label = (k: string) => options.find((o) => o.kind === k)?.label ?? k;
  const summary = value.length ? value.map(label).join(", ") : "nenhuma";

  // posiciona abaixo do botão (ou acima, se não couber), alinhado para não sair da tela
  useLayoutEffect(() => {
    if (!open || !button.current || !panel.current) return;
    const b = button.current.getBoundingClientRect();
    const w = panel.current.offsetWidth;
    const h = panel.current.offsetHeight;
    const left = Math.max(8, Math.min(b.right - w, window.innerWidth - w - 8));
    const below = b.bottom + 4;
    const top = below + h > window.innerHeight - 8 && b.top - h - 4 > 8 ? b.top - h - 4 : below;
    setPos({ top, left });
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!panel.current?.contains(e.target as Node) && !button.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); button.current?.focus(); } };
    const close = () => setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [open]);

  return (
    <>
      <button ref={button} type="button" disabled={disabled} onClick={() => { setPos(null); setOpen(!open); }} aria-expanded={open}
        aria-label={`${name} absorve: ${summary}. Clique para escolher`} title={value.length ? summary : undefined}
        className="flex max-w-[180px] items-center gap-1 rounded-md border border-line bg-sheet px-1.5 py-1 text-left text-[12px] text-muted hover:text-ink disabled:opacity-60">
        <span className="truncate">{value.length ? summary : "—"}</span>
        <ChevronDown size={12} className={`shrink-0 transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div ref={panel} role="dialog" aria-label={`O que “${name}” absorve`}
          style={{ position: "fixed", top: pos?.top ?? -9999, left: pos?.left ?? -9999 }}
          className="z-50 w-80 max-w-[calc(100vw-16px)] rounded-lg border border-line bg-sheet p-3 text-[13px] shadow-xl">
          <p className="mb-2 text-[12px] text-muted">Quando <b className="text-ink">{name}</b> aparece, estas deixam de descontar (seguem como evidência):</p>
          <div className="max-h-64 space-y-1 overflow-y-auto">
            {options.map((o) => (
              <label key={o.kind} className="flex cursor-pointer items-start gap-2 rounded px-1 py-0.5 hover:bg-paper">
                <input type="checkbox" className="mt-0.5 shrink-0" checked={value.includes(o.kind)} aria-label={`${name} absorve ${o.label}`}
                  onChange={(e) => onChange(e.target.checked ? [...value, o.kind] : value.filter((x) => x !== o.kind))} />
                <span>{o.label}</span>
              </label>
            ))}
            {!options.length && <p className="text-muted">Não há outras regras nesta validação.</p>}
          </div>
          <div className="mt-2 flex justify-end">
            <button type="button" onClick={() => setOpen(false)} className="rounded-md border border-line px-2.5 py-1 text-[12px] hover:bg-paper">Fechar</button>
          </div>
        </div>
      )}
    </>
  );
}

/** Régua do score: pesos, descontos, faixas, confiança e tolerâncias. */
export function ScoreRubricEditor({ data, base, onChange }: Props) {
  const sum = VALIDATIONS.reduce((s, v) => s + (data.weights[v] || 0), 0);
  const approve = data.bands.find((b) => b.recommendation === "approve")?.score_min ?? 85;
  const caveats = data.bands.find((b) => b.recommendation === "approve_with_caveats")?.score_min ?? 70;
  const setBand = (rec: "approve" | "approve_with_caveats", v: number) =>
    onChange({ ...data, bands: data.bands.map((b) => (b.recommendation === rec ? { ...b, score_min: v } : b)) });
  const bandError = !(caveats > 0 && approve > caveats && approve <= 100);
  const num = (v: string) => (v === "" ? 0 : Number(v));
  const diff = (a: unknown, b: unknown) => JSON.stringify(a) !== JSON.stringify(b);
  const field = (changed: boolean, bad = false) => `w-20 rounded-md border px-2 py-1 text-right tabular-nums ${bad ? "border-bad bg-[#fbefed]" : changed ? "border-warn bg-[#fdf6e4]" : "border-line"}`;

  return (
    <div className="space-y-5">
      <InfoBox id="admin-score" title="Mudanças aqui afetam todos os chamados">
        A régua converte apontamentos em score e recomendação. Depois de mudar, rode a <b>Validação</b> para ver o impacto na acurácia antes de usar em produção.
      </InfoBox>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="rounded-xl border border-line bg-sheet p-5">
          <h3 className="flex items-center gap-1.5 font-semibold">Pesos das validações <InfoTip term="weight" /></h3>
          <p className="mb-3 text-[13px] text-muted">Quanto cada validação vale no score. Precisam somar 100.</p>
          <div className="space-y-2 text-sm">
            {VALIDATIONS.map((v) => (
              <label key={v} className="flex items-center justify-between gap-3">
                <span>{VALIDATION_LABEL[v]}</span>
                <span className="flex items-center gap-1"><input type="number" min={0} max={100} value={data.weights[v]} onChange={(e) => onChange({ ...data, weights: { ...data.weights, [v]: num(e.target.value) } })} className={field(data.weights[v] !== base.weights[v], sum !== 100)} />%</span>
              </label>
            ))}
            <div className={`flex justify-between border-t border-line pt-2 font-semibold ${sum === 100 ? "text-ok" : "text-bad"}`}>
              <span>Total</span><span className="tabular-nums">{sum}%{sum !== 100 && ` (faltam ${100 - sum})`}</span>
            </div>
          </div>
        </section>

        <section className="rounded-xl border border-line bg-sheet p-5">
          <h3 className="flex items-center gap-1.5 font-semibold">Desconto por severidade <InfoTip term="severity" /></h3>
          <p className="mb-3 text-[13px] text-muted">Pontos tirados da nota da validação (0–100) por apontamento. O efeito no score depende do peso.</p>
          <div className="space-y-2 text-sm">
            {SEVERITIES.map((s) => (
              <label key={s} className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-2"><i className="size-2.5 rounded-sm" style={{ background: SEVERITY[s].color }} />{SEVERITY[s].label}</span>
                <span className="flex items-center gap-3">
                  <span className="text-[12px] text-muted">{VALIDATIONS.map((v) => `${VALIDATION_SHORT[v]} −${pts((data.discount_by_severity[s] * data.weights[v]) / (sum || 100))}`).join(" · ")}</span>
                  <span className="flex items-center gap-1">−<input type="number" min={0} max={100} value={data.discount_by_severity[s]}
                    onChange={(e) => onChange({ ...data, discount_by_severity: { ...data.discount_by_severity, [s]: num(e.target.value) } })}
                    className={field(data.discount_by_severity[s] !== base.discount_by_severity[s])} /></span>
                </span>
              </label>
            ))}
          </div>
        </section>

        <section className="rounded-xl border border-line bg-sheet p-5">
          <h3 className="flex items-center gap-1.5 font-semibold">Faixas de recomendação <InfoTip term="bands" /></h3>
          <p className="mb-3 text-[13px] text-muted">Score mínimo para cada recomendação. Abaixo de “Ressalvas”, devolve ao fornecedor.</p>
          <div className="space-y-2 text-sm">
            <label className="flex items-center justify-between"><span style={{ color: REC.approve.color }} className="font-medium">Aprovar a partir de</span>
              <input type="number" min={1} max={100} value={approve} onChange={(e) => setBand("approve", num(e.target.value))} className={field(diff(data.bands, base.bands), bandError)} /></label>
            <label className="flex items-center justify-between"><span style={{ color: REC.approve_with_caveats.color }} className="font-medium">Aprovar com ressalvas a partir de</span>
              <input type="number" min={1} max={99} value={caveats} onChange={(e) => setBand("approve_with_caveats", num(e.target.value))} className={field(diff(data.bands, base.bands), bandError)} /></label>
            {bandError && <p className="text-[12px] text-bad">“Aprovar” precisa ser maior que “Ressalvas”, e ambos entre 1 e 100.</p>}
            {!bandError && <div className="pt-2"><BandScale score={approve} rubric={{ weights: data.weights, discount_by_severity: data.discount_by_severity, bands: data.bands, confidence: data.confidence }} /></div>}
          </div>
        </section>

        <section className="rounded-xl border border-line bg-sheet p-5">
          <h3 className="flex items-center gap-1.5 font-semibold">Confiança <InfoTip term="confidence" /></h3>
          <p className="mb-3 text-[13px] text-muted">Quantos redutores (escopo vago, foto ilegível…) levam a confiança média ou baixa. Confiança baixa manda para análise detalhada.</p>
          <div className="space-y-2 text-sm">
            <label className="flex items-center justify-between"><span>Confiança média com</span>
              <span className="flex items-center gap-1"><input type="number" min={1} max={5} value={data.confidence.medium_with_n_reducers} onChange={(e) => onChange({ ...data, confidence: { ...data.confidence, medium_with_n_reducers: num(e.target.value) } })} className={field(data.confidence.medium_with_n_reducers !== base.confidence.medium_with_n_reducers)} /> redutor(es)</span></label>
            <label className="flex items-center justify-between"><span>Confiança baixa com</span>
              <span className="flex items-center gap-1"><input type="number" min={1} max={5} value={data.confidence.low_with_n_reducers} onChange={(e) => onChange({ ...data, confidence: { ...data.confidence, low_with_n_reducers: num(e.target.value) } })} className={field(data.confidence.low_with_n_reducers !== base.confidence.low_with_n_reducers, data.confidence.medium_with_n_reducers > data.confidence.low_with_n_reducers)} /> redutor(es)</span></label>
          </div>
        </section>
      </div>

      <section className="rounded-xl border border-line bg-sheet p-5">
        <h3 className="font-semibold">Tolerâncias das verificações</h3>
        <p className="mb-3 text-[13px] text-muted">Limites das checagens feitas por regra (sem o modelo).</p>
        <div className="grid gap-x-8 gap-y-3 text-sm md:grid-cols-2">
          {([
            ["price_tolerance_pct", "Tolerância de preço sobre a referência (LPU)", "%", "Acima de referência + tolerância vira “Preço acima da referência”."],
            ["market_price_tolerance_pct", "Tolerância sobre o preço de mercado", "%", "Preço até N% acima de um anúncio ou cotação anexada não é apontado: cobre a margem do fornecedor sobre o varejo."],
            ["max_amount_at_issue_for_approve_pct", "Valor em questão que impede aprovar direto", "%", "Acima desta fração do orçamento em questão, uma nota que aprovaria vira “Aprovar com ressalvas” (0 desliga)."],
            ["spreadsheet_value_tolerance", "Diferença aceita entre planilha e chamado", "R$", "Diferença de valor total tolerada antes de virar “Planilha divergente”."],
            ["photo_date_tolerance_days", "Tolerância da data da foto", "dias", "Foto tirada até N dias antes da abertura não é apontada."],
            ["hash_max_distance", "Semelhança para foto reaproveitada", "dist.", "Distância máxima (0 = idêntica) para considerar a foto uma cópia. Menor = mais rigoroso para acusar."],
            ["hash_max_distance_low_detail", "Semelhança em foto escura/tremida", "dist.", "Limite mais estrito para fotos com pouco detalhe."],
            ["hash_min_detail", "Detalhe mínimo da foto", "", "Abaixo disso a foto é considerada de pouco detalhe."],
            ["photo_quantity_tolerance_pct", "Tolerância da quantidade sobre as fotos", "%", "Quantidade cobrada até N% acima do que as fotos mostram (somadas) não é apontada: cobre margem de corte e perda."],
            ["relevant_amount_at_issue_pct", "Valor divergente relevante", "%", "A partir desta fração do orçamento em questão, entra o apontamento “Valor divergente relevante” (cada tipo desconta uma vez; este pesa a materialidade)."],
          ] as const).map(([k, label, unit, help]) => (
            <label key={k} className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-1">{label} <InfoTip text={help} size={12} /></span>
              <span className="flex items-center gap-1 whitespace-nowrap">
                <input type="number" step="any" min={0} value={data[k]} onChange={(e) => onChange({ ...data, [k]: num(e.target.value) })} className={field(data[k] !== base[k])} />
                <span className="w-8 text-[12px] text-muted">{unit}</span>
              </span>
            </label>
          ))}
        </div>
      </section>
    </div>
  );
}
