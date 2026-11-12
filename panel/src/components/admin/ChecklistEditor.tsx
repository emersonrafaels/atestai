import { ArrowRight, ChevronDown, Copy, FileCheck2, Plus, RotateCcw, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { ChecklistRequirementConfig, ChecklistRuleConfig, ChecklistsConfig } from "../../api";
import { MAINTENANCE_LABEL, STAGE_LABEL, STAGE_SHORT } from "../../format";
import { InfoBox } from "../ui/InfoBox";
import { Switch } from "../ui/Switch";
import { Tooltip } from "../ui/Tooltip";

interface Props {
  data: ChecklistsConfig;
  base: ChecklistsConfig;
  onChange: (next: ChecklistsConfig) => void;
  /** cadastro de categorias (com as esteiras em que cada uma vale) */
  categories: { value: string; label: string; enabled?: boolean; workstreams?: string[] }[];
}

const ANY = "*";
const NO_CATEGORY = "__nenhuma__"; // só casa com regras de "qualquer categoria" (o checklist geral)
const MAINTENANCES = ["corrective", "preventive"] as const;
const WORKSTREAMS = ["SETA", "SISR"] as const;
type Ws = (typeof WORKSTREAMS)[number];
const MOMENTS = ["quote", "execution"] as const;
type Maintenance = (typeof MAINTENANCES)[number];
type Moment = (typeof MOMENTS)[number];
type Cell = { category: string; moment: Moment };

const wsOf = (r: { workstream?: string }) => r.workstream ?? ANY;
const key = (r: { category: string; maintenance: string; moment: string; workstream?: string }) => `${wsOf(r)}/${r.category}/${r.maintenance}/${r.moment}`;

/** Mesma regra do backend (config.Checklists.rule_for): a regra ativa mais específica; em empate, a última. */
export function ruleFor(rules: ChecklistRuleConfig[], category: string, maintenance: string, moment: string, workstream: string = ANY): number | null {
  let best: [number, number] | null = null;
  rules.forEach((r, i) => {
    if (!r.enabled) return;
    let points = 0;
    for (const [rv, v] of [[r.category, category], [r.maintenance, maintenance], [r.moment, moment], [wsOf(r), workstream]]) {
      if (rv === ANY) continue;
      if (rv !== v) return;
      points++;
    }
    if (!best || points > best[0] || (points === best[0] && i > best[1])) best = [points, i];
  });
  return best ? (best as [number, number])[1] : null;
}

const slug = (s: string) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40);
const uniqueId = (desc: string, taken: string[]) => {
  const root = slug(desc) || "documento";
  let id = root;
  for (let n = 2; taken.includes(id); n++) id = `${root}_${n}`;
  return id;
};
const DEFAULT_REQUIREMENT: ChecklistRequirementConfig = { id: "quote", description: "Orçamento na planilha Excel padrão", accepted: ["quote_doc"], enabled: true };

function problemsOf(q: ChecklistRequirementConfig, others: string[]): string[] {
  return [!q.description.trim() && "descreva o documento", !q.accepted.length && "aceite ao menos um tipo de anexo", !!q.id && others.includes(q.id) && "identificador repetido"]
    .filter(Boolean) as string[];
}
const ruleHasProblems = (r: ChecklistRuleConfig) =>
  (r.enabled && !r.requirements.length) || r.requirements.some((q, k) => problemsOf(q, r.requirements.filter((_, j) => j !== k).map((x) => x.id)).length > 0);

export function ChecklistEditor({ data, base, onChange, categories }: Props) {
  const catLabel = (v: string) => (v === ANY ? "Checklist geral" : categories.find((c) => c.value === v)?.label ?? v);
  const sortedCats = useMemo(() => [...categories].sort((a, b) => a.label.localeCompare(b.label, "pt-BR")), [categories]);
  const [maint, setMaint] = useState<Maintenance>("corrective");
  const [ws, setWs] = useState<Ws>("SETA");
  // linhas: checklist geral + categorias ativas da esteira (e as desativadas que ainda têm checklist próprio)
  const inWs = (c: Props["categories"][number], w: string) => !c.workstreams?.length || c.workstreams.includes(w);
  const rowsFor = (w: string) => [ANY, ...sortedCats
    .filter((c) => inWs(c, w) && (c.enabled !== false || data.rules.some((r) => r.category === c.value)))
    .map((c) => c.value)];
  const rows = rowsFor(ws);
  const baseByKey = useMemo(() => new Map(base.rules.map((r) => [key(r), r])), [base]);

  const effective = (category: string, moment: string, m: string = maint, w: string = ws) =>
    ruleFor(data.rules, category === ANY ? NO_CATEGORY : category, m, moment, w);
  /** Checklist próprio desligado da combinação (para reativar). */
  const disabledOwn = (category: string, moment: string, m: string = maint, w: string = ws) =>
    data.rules.findIndex((r) => !r.enabled && r.category === category && r.moment === moment
      && (r.maintenance === m || r.maintenance === ANY) && (wsOf(r) === w || wsOf(r) === ANY));

  const [sel, setSel] = useState<Cell>(() => {
    const own = [...categories].sort((a, b) => a.label.localeCompare(b.label, "pt-BR"))
      .find((c) => inWs(c, "SETA") && (() => { const i = ruleFor(data.rules, c.value, "corrective", "execution", "SETA"); return i !== null && data.rules[i].category === c.value; })());
    return { category: own?.value ?? ANY, moment: "execution" };
  });
  const changeWs = (w: Ws) => {
    setWs(w);
    if (!rowsFor(w).includes(sel.category)) setSel({ category: ANY, moment: sel.moment });
  };

  const setRules = (rules: ChecklistRuleConfig[]) => onChange({ ...data, rules });
  const setRule = (i: number, r: ChecklistRuleConfig) => setRules(data.rules.map((x, k) => (k === i ? r : x)));
  const statusOf = (r: ChecklistRuleConfig) => {
    const b = baseByKey.get(key(r));
    return !b ? "nova" : JSON.stringify(b) !== JSON.stringify(r) ? "alterada" : null;
  };

  // regras que nenhuma célula do mapa mostra (ex.: regra geral só de um tipo de manutenção sobreposta, desativadas sem célula)
  const reachable = new Set<number>();
  for (const w of WORKSTREAMS) for (const m of MAINTENANCES) for (const c of rowsFor(w)) for (const mo of MOMENTS) {
    const i = effective(c, mo, m, w);
    if (i !== null) reachable.add(i);
    const d = disabledOwn(c, mo, m, w);
    if (d >= 0 && (i === null || data.rules[i].category !== c)) reachable.add(d);
  }
  const others = data.rules.map((r, i) => ({ r, i })).filter(({ i }) => !reachable.has(i));

  return (
    <div className="space-y-5">
      <InfoBox id="admin-checklist-map" title="Como ler esta página">
        Cada chamado é conferido contra uma lista de <b>documentos exigidos</b>, que depende da esteira, do tipo de manutenção, da categoria e da etapa.
        Categorias sem <b>checklist próprio</b> usam o <b>checklist geral</b> da etapa. Clique numa célula do mapa para ver e editar o que vale ali.
      </InfoBox>

      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,430px)_minmax(0,1fr)]">
        {/* mapa */}
        <section className="min-w-0 rounded-xl border border-line bg-sheet">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
            <h3 className="font-semibold">Mapa do checklist</h3>
            <div className="flex flex-wrap gap-2">
              <Segmented label="Esteira" value={ws} onChange={changeWs} options={WORKSTREAMS.map((w) => [w, w])} />
              <Segmented label="Tipo de manutenção" value={maint} onChange={setMaint} options={MAINTENANCES.map((m) => [m, MAINTENANCE_LABEL[m]])} />
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[380px] text-sm">
              <thead className="text-left text-[12px] text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">Categoria</th>
                  {MOMENTS.map((mo) => <th key={mo} className="px-2 py-2 font-medium">{STAGE_SHORT[mo]}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c} className={`border-t border-line/70 ${c === ANY ? "bg-paper/40" : ""}`}>
                    <th scope="row" className="px-4 py-1.5 text-left font-medium">
                      {catLabel(c)}
                      {c === ANY && <div className="text-[11px] font-normal text-muted">para quem não tem checklist próprio</div>}
                    </th>
                    {MOMENTS.map((mo) => {
                      const i = effective(c, mo);
                      const r = i !== null ? data.rules[i] : null;
                      const own = !!r && r.category === c;
                      const n = r ? r.requirements.filter((q) => q.enabled).length : 0;
                      const st = own && r ? statusOf(r) : null;
                      const off = !own && disabledOwn(c, mo) >= 0;
                      const bad = own && r ? ruleHasProblems(r) : false;
                      const active = sel.category === c && sel.moment === mo;
                      return (
                        <td key={mo} className="px-1.5 py-1">
                          <button onClick={() => setSel({ category: c, moment: mo })} aria-pressed={active}
                            aria-label={`${catLabel(c)}, ${STAGE_LABEL[mo]}: ${!r ? "sem checklist" : own ? `checklist próprio com ${n} documentos` : `usa o checklist geral, ${n} documentos`}`}
                            className={`flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors ${active ? "bg-blueprint text-white" : own ? "bg-blueprint-soft/70 text-blueprint hover:bg-blueprint-soft" : "hover:bg-paper"}`}>
                            {!r ? <span className={active ? "" : "text-bad"}>vazio</span>
                              : own ? <><FileCheck2 size={13} className="shrink-0" /><b className="tabular-nums">{n}</b><span>{n === 1 ? "documento" : "documentos"}</span></>
                              : <span className={active ? "" : "text-muted"}>geral · {n}</span>}
                            <span className="ml-auto flex items-center gap-1">
                              {bad && <span className="size-2 rounded-full bg-bad" title="Há algo a corrigir" />}
                              {st && <span className={`size-2 rounded-full ${st === "nova" ? "bg-blueprint" : "bg-warn"} ${active ? "ring-1 ring-white" : ""}`} title={st === "nova" ? "Novo (não salvo)" : "Alterado (não salvo)"} />}
                              {off && <span className={`text-[10px] uppercase ${active ? "" : "text-muted"}`} title="Há um checklist próprio desativado">desat.</span>}
                            </span>
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="flex flex-wrap gap-x-4 gap-y-1 border-t border-line px-4 py-2.5 text-[12px] text-muted">
            <span className="flex items-center gap-1"><FileCheck2 size={12} className="text-blueprint" /> checklist próprio</span>
            <span>geral · n = usa o checklist geral</span>
            <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-warn" /> alterado, não salvo</span>
          </p>
        </section>

        {/* painel da combinação */}
        <CellPanel
          key={`${sel.category}/${sel.moment}/${maint}/${ws}`}
          cell={sel} maint={maint} ws={ws} data={data} catLabel={catLabel} rows={rows}
          catWs={sel.category === ANY ? [] : categories.find((c) => c.value === sel.category)?.workstreams ?? []}
          effective={effective} disabledOwn={disabledOwn} statusOf={statusOf}
          setRule={setRule} setRules={setRules} select={setSel}
        />
      </div>

      {others.length > 0 && (
        <details className="group rounded-xl border border-line bg-sheet">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-5 py-3 font-semibold">
            <ChevronDown size={16} className="text-muted transition group-open:rotate-180" /> Outras regras ({others.length})
            <span className="text-[13px] font-normal text-muted">não aparecem no mapa porque nenhuma combinação as usa hoje</span>
          </summary>
          <ul className="divide-y divide-line/70 border-t border-line">
            {others.map(({ r, i }) => (
              <li key={key(r) + i} className="flex flex-wrap items-center gap-3 px-5 py-2.5 text-sm">
                <Switch size="sm" on={r.enabled} onChange={(v) => setRule(i, { ...r, enabled: v })} label={`Regra ${r.enabled ? "ativa" : "desativada"}`} />
                <span className="flex-1">{ruleTitle(r, catLabel)} <span className="text-muted">· {r.requirements.length} documento(s)</span></span>
                <button onClick={() => { if (window.confirm(`Remover a regra ${ruleTitle(r, catLabel)}?`)) setRules(data.rules.filter((_, k) => k !== i)); }}
                  className="flex items-center gap-1 rounded-md px-2 py-1 text-[13px] text-muted hover:bg-[#fbefed] hover:text-bad"><Trash2 size={14} /> Remover</button>
              </li>
            ))}
          </ul>
        </details>
      )}

      <AttachmentTypes data={data} base={base} onChange={onChange} />
    </div>
  );
}

function ruleTitle(r: ChecklistRuleConfig, catLabel: (v: string) => string) {
  return `${wsOf(r) === ANY ? "" : `${wsOf(r)} · `}${catLabel(r.category)} · ${r.maintenance === ANY ? "qualquer tipo" : MAINTENANCE_LABEL[r.maintenance].toLowerCase()} · ${r.moment === ANY ? "qualquer etapa" : STAGE_LABEL[r.moment]}`;
}

function Segmented<T extends string>({ label, value, onChange, options }: { label: string; value: T; onChange: (v: T) => void; options: [T, string][] }) {
  return (
    <div className="flex rounded-lg bg-paper p-0.5 text-sm" role="radiogroup" aria-label={label}>
      {options.map(([v, l]) => (
        <button key={v} role="radio" aria-checked={value === v} onClick={() => onChange(v)}
          className={`rounded-md px-3 py-1 ${value === v ? "bg-sheet font-semibold shadow-sm" : "text-muted hover:text-ink"}`}>{l}</button>
      ))}
    </div>
  );
}

// ============================================================================ painel da combinação escolhida
function CellPanel({ cell, maint, ws, catWs, data, catLabel, rows, effective, disabledOwn, statusOf, setRule, setRules, select }: {
  cell: Cell; maint: Maintenance; ws: Ws; data: ChecklistsConfig; catLabel: (v: string) => string; rows: string[];
  /** esteiras da categoria escolhida (vazio = SETA e SISR); com uma só, não há o que escolher */
  catWs: string[];
  effective: (c: string, mo: string) => number | null; disabledOwn: (c: string, mo: string) => number;
  statusOf: (r: ChecklistRuleConfig) => "nova" | "alterada" | null;
  setRule: (i: number, r: ChecklistRuleConfig) => void; setRules: (rules: ChecklistRuleConfig[]) => void; select: (c: Cell) => void;
}) {
  const [onlyThis, setOnlyThis] = useState(false);
  const [onlyWs, setOnlyWs] = useState(false);
  const general = cell.category === ANY;
  const idx = effective(cell.category, cell.moment);
  const rule = idx !== null ? data.rules[idx] : null;
  const own = !!rule && rule.category === cell.category;
  const off = disabledOwn(cell.category, cell.moment);
  const title = `${catLabel(cell.category)} · ${ws} · ${MAINTENANCE_LABEL[maint]} · ${STAGE_LABEL[cell.moment]}`;

  const create = () => {
    const r: ChecklistRuleConfig = {
      workstream: onlyWs ? ws : ANY, category: cell.category, maintenance: onlyThis ? maint : ANY, moment: cell.moment, enabled: true,
      requirements: rule ? rule.requirements.map((x) => ({ ...x, accepted: [...x.accepted] })) : [{ ...DEFAULT_REQUIREMENT }],
    };
    const same = data.rules.findIndex((x) => key(x) === key(r));
    if (same >= 0) setRule(same, { ...data.rules[same], enabled: true });
    else setRules([...data.rules, r]);
  };

  return (
    <section className="min-w-0 rounded-xl border border-line bg-sheet lg:sticky lg:top-6">
      <header className="flex flex-wrap items-start justify-between gap-2 border-b border-line px-5 py-3">
        <div className="min-w-0">
          <h3 className="font-semibold">{title}</h3>
          <p className="text-[13px] text-muted">
            {own ? (general ? "Checklist geral desta etapa" : "Checklist próprio da categoria") : rule ? "Usa o checklist geral desta etapa" : "Nenhum checklist se aplica"}
          </p>
        </div>
        {own && rule && statusOf(rule) && (
          <span className={`rounded px-1.5 text-[11px] font-semibold uppercase ${statusOf(rule) === "nova" ? "bg-blueprint-soft text-blueprint" : "bg-[#fdf1dc] text-warn"}`}>
            {statusOf(rule) === "nova" ? "novo" : "alterado"} · não salvo
          </span>
        )}
      </header>

      {own && rule && idx !== null ? (
        <OwnRule rule={rule} general={general}
          usedBy={general ? rows.filter((c) => c !== ANY && effective(c, cell.moment) === idx).map(catLabel) : []}
          attachments={data.attachment_categories}
          onChange={(r) => setRule(idx, r)}
          onRemove={() => { if (window.confirm(`Remover o checklist próprio de ${catLabel(cell.category)}? A combinação volta a usar o checklist geral.`)) setRules(data.rules.filter((_, k) => k !== idx)); }} />
      ) : (
        <div className="space-y-4 p-5">
          {rule ? (
            <div>
              <p className="mb-2 text-sm">Esta combinação não tem checklist próprio e usa o <b>checklist geral</b>:</p>
              <ReadOnlyList rule={rule} />
            </div>
          ) : (
            <p className="rounded-lg bg-[#fbefed] px-3 py-2 text-sm text-bad">
              {general ? "Não há checklist geral ativo para esta etapa: categorias sem checklist próprio ficam sem nenhuma exigência." : "Nenhum checklist se aplica: o chamado não terá exigências de documentos."}
            </p>
          )}

          {off >= 0 ? (
            <div className="rounded-lg border border-line p-3 text-sm">
              <p className="mb-2">Há um {general ? "checklist geral" : "checklist próprio"} desativado para esta combinação ({data.rules[off].requirements.length} documento(s)).</p>
              <div className="flex flex-wrap gap-2">
                <button onClick={() => setRule(off, { ...data.rules[off], enabled: true })} className="flex items-center gap-1.5 rounded-lg bg-blueprint px-3 py-1.5 font-semibold text-white hover:bg-[#1d44a0]"><RotateCcw size={14} /> Reativar</button>
                <button onClick={() => { if (window.confirm("Apagar o checklist desativado?")) setRules(data.rules.filter((_, k) => k !== off)); }} className="flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-muted hover:bg-[#fbefed] hover:text-bad"><Trash2 size={14} /> Apagar</button>
              </div>
            </div>
          ) : (
            <div className="space-y-3 rounded-lg border border-line p-4">
              <h4 className="text-sm font-semibold">{general ? "Criar checklist geral" : `Criar checklist próprio para ${catLabel(cell.category)}`}</h4>
              <p className="text-[13px] text-muted">Na etapa <b className="text-ink">{STAGE_LABEL[cell.moment]}</b>, para quais chamados ele vale?</p>
              <div className="grid gap-2 text-sm sm:grid-cols-[130px_1fr] sm:items-center">
                <span className="text-[13px] font-medium text-muted">Tipo de manutenção</span>
                <Segmented label="Tipo de manutenção do novo checklist" value={onlyThis ? "only" : "both"} onChange={(v) => setOnlyThis(v === "only")}
                  options={[["both", "Corretiva e preventiva"], ["only", `Só ${MAINTENANCE_LABEL[maint].toLowerCase()}`]]} />
                {catWs.length !== 1 && <>
                  <span className="text-[13px] font-medium text-muted">Esteira</span>
                  <Segmented label="Esteira do novo checklist" value={onlyWs ? "only" : "both"} onChange={(v) => setOnlyWs(v === "only")}
                    options={[["both", "SETA e SISR"], ["only", `Só ${ws}`]]} />
                </>}
              </div>
              <p className="rounded-md bg-paper/70 px-3 py-2 text-[13px]">
                {general ? "Categorias sem checklist próprio" : <>Chamados de <b>{catLabel(cell.category)}</b></>}
                {" "}em {STAGE_LABEL[cell.moment].toLowerCase()}, de manutenção <b>{onlyThis ? `só ${MAINTENANCE_LABEL[maint].toLowerCase()}` : "corretiva e preventiva"}</b>
                {catWs.length === 1 ? <>, na esteira <b>{catWs[0]}</b></> : <>, {onlyWs ? <>só na esteira <b>{ws}</b></> : <>nas esteiras <b>SETA e SISR</b></>}</>},
                {" "}passam a usar este checklist.
                {(onlyThis || (onlyWs && catWs.length !== 1)) && (
                  <span className="mt-1 block text-muted">
                    {[
                      onlyThis && `os chamados de manutenção ${MAINTENANCE_LABEL[maint === "corrective" ? "preventive" : "corrective"].toLowerCase()}`,
                      onlyWs && catWs.length !== 1 && `os da esteira ${ws === "SETA" ? "SISR" : "SETA"}`,
                    ].filter(Boolean).join(" e ").replace(/^o/, "O")} continuam com o checklist que usam hoje.
                  </span>
                )}
              </p>
              <div className="flex flex-wrap items-center gap-3">
                <button onClick={create} className="flex items-center gap-1.5 rounded-lg bg-blueprint px-3 py-1.5 text-sm font-semibold text-white hover:bg-[#1d44a0]">
                  {rule ? <Copy size={14} /> : <Plus size={14} />} Criar checklist
                </button>
                {rule && <span className="text-[12px] text-muted">Ele começa com os documentos acima; depois é só ajustar.</span>}
              </div>
            </div>
          )}

          {!general && rule && (
            <button onClick={() => select({ category: ANY, moment: cell.moment })} className="flex items-center gap-1 text-[13px] font-medium text-blueprint hover:underline">
              Editar o checklist geral desta etapa <ArrowRight size={13} />
            </button>
          )}
        </div>
      )}
    </section>
  );
}

function ReadOnlyList({ rule }: { rule: ChecklistRuleConfig }) {
  const on = rule.requirements.filter((q) => q.enabled);
  return (
    <ol className="space-y-1.5 rounded-lg bg-paper/60 p-3 text-sm">
      {on.map((q, k) => (
        <li key={q.id || k} className="flex gap-2">
          <span className="w-5 shrink-0 text-right tabular-nums text-muted">{k + 1}.</span>
          <span>{q.description} <span className="text-[12px] text-muted">· aceita {q.accepted.map(attachmentShort).join(", ").toLowerCase()}</span></span>
        </li>
      ))}
      {!on.length && <li className="text-muted">Nenhum documento cobrado.</li>}
    </ol>
  );
}

function OwnRule({ rule, general, usedBy, attachments, onChange, onRemove }: {
  rule: ChecklistRuleConfig; general: boolean; usedBy: string[]; attachments: Record<string, string>;
  onChange: (r: ChecklistRuleConfig) => void; onRemove: () => void;
}) {
  const setReq = (k: number, q: ChecklistRequirementConfig) => onChange({ ...rule, requirements: rule.requirements.map((x, j) => (j === k ? q : x)) });
  const reach = `Vale para ${wsOf(rule) === ANY ? "as esteiras SETA e SISR" : `a esteira ${wsOf(rule)}`}, ${rule.maintenance === ANY ? "manutenção corretiva e preventiva" : `só manutenção ${MAINTENANCE_LABEL[rule.maintenance].toLowerCase()}`}.`;
  return (
    <div className="space-y-4 p-5">
      <div className="space-y-1 text-[13px] text-muted">
        <p>{reach}</p>
        {general && (
          <p>{usedBy.length ? <>Usado por {usedBy.length} categoria(s) sem checklist próprio: <span className="text-ink">{usedBy.join(", ")}</span>.</> : "Nenhuma categoria usa este checklist hoje: todas têm checklist próprio nesta etapa."}</p>
        )}
      </div>

      <div>
        <h4 className="mb-2 text-sm font-semibold">Documentos exigidos</h4>
        <ol className="space-y-2">
          {rule.requirements.map((q, k) => (
            <Requirement key={k} n={k + 1} q={q} attachments={attachments}
              others={rule.requirements.filter((_, j) => j !== k).map((x) => x.id)}
              onChange={(nq) => setReq(k, nq)}
              onRemove={() => onChange({ ...rule, requirements: rule.requirements.filter((_, j) => j !== k) })} />
          ))}
        </ol>
        {rule.enabled && !rule.requirements.length && (
          <p className="mt-2 rounded-md bg-[#fbefed] px-3 py-1.5 text-[13px] text-bad">Adicione um documento{general ? "" : " ou remova o checklist próprio"}: um checklist ativo precisa de pelo menos um.</p>
        )}
        <button onClick={() => onChange({ ...rule, requirements: [...rule.requirements, { id: "", description: "", accepted: [], enabled: true }] })}
          className="mt-2 flex items-center gap-1.5 rounded-md px-2 py-1 text-sm font-medium text-blueprint hover:bg-blueprint-soft"><Plus size={14} /> Adicionar documento</button>
      </div>

      <footer className="flex flex-wrap items-center gap-3 border-t border-line pt-3 text-sm">
        <label className="flex items-center gap-2">
          <Switch on={rule.enabled} onChange={(v) => onChange({ ...rule, enabled: v })} label={rule.enabled ? "Checklist ativo" : "Checklist desativado"} />
          {rule.enabled ? "Checklist ativo" : "Checklist desativado"}
        </label>
        <span className="text-[12px] text-muted">
          {general ? "Desativar deixa as categorias sem checklist próprio sem exigências." : "Desativar faz a combinação voltar a usar o checklist geral."}
        </span>
        {!general && (
          <button onClick={onRemove} className="ml-auto flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-muted hover:bg-[#fbefed] hover:text-bad">
            <Trash2 size={14} /> Remover checklist próprio
          </button>
        )}
      </footer>
    </div>
  );
}

function Requirement({ n, q, attachments, others, onChange, onRemove }: {
  n: number; q: ChecklistRequirementConfig; attachments: Record<string, string>; others: string[];
  onChange: (q: ChecklistRequirementConfig) => void; onRemove: () => void;
}) {
  const remaining = Object.keys(attachments).filter((a) => !q.accepted.includes(a));
  const problems = problemsOf(q, others);
  return (
    <li className={`rounded-lg border p-2.5 ${problems.length ? "border-bad/50" : q.enabled ? "border-line/80" : "border-dashed border-line bg-paper/40"}`}>
      <div className="flex items-start gap-2">
        <Tooltip content={q.id ? `Identificador interno: ${q.id}` : "O identificador é gerado a partir do texto"}>
          <span className="w-5 shrink-0 cursor-help pt-1.5 text-right text-sm tabular-nums text-muted">{n}.</span>
        </Tooltip>
        <input value={q.description} placeholder="Ex.: Foto do local depois do serviço" aria-label={`Documento ${n}`}
          onChange={(e) => onChange({ ...q, description: e.target.value })}
          onBlur={() => { if (!q.id && q.description.trim()) onChange({ ...q, id: uniqueId(q.description, others) }); }}
          className={`min-w-0 flex-1 rounded-md border border-transparent px-1.5 py-1 text-sm hover:border-line focus:border-blueprint focus:outline-none ${q.enabled ? "" : "text-muted line-through"} ${!q.description.trim() ? "border-bad/60" : ""}`} />
        <Tooltip content={q.enabled ? "Cobrado: desligue para deixar de exigir sem apagar" : "Não cobrado: ligue para voltar a exigir"}>
          <span className="flex items-center gap-1.5 pt-1.5 text-[12px] text-muted">
            <Switch size="sm" on={q.enabled} onChange={(v) => onChange({ ...q, enabled: v })} label={q.enabled ? "Cobrar este documento" : "Não cobrar este documento"} />
            <span className="hidden w-[62px] sm:inline">{q.enabled ? "cobrado" : "não cobrado"}</span>
          </span>
        </Tooltip>
        <Tooltip content="Remover o documento"><button onClick={onRemove} aria-label={`Remover o documento ${n}`} className="rounded-md p-1 text-muted hover:bg-[#fbefed] hover:text-bad"><Trash2 size={15} /></button></Tooltip>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5 pl-7 text-[12px]">
        <span className="text-muted">Aceita:</span>
        {q.accepted.map((a) => (
          <Tooltip key={a} content={attachments[a] ?? a}>
            <span className="flex cursor-help items-center gap-1 rounded-full bg-blueprint-soft py-0.5 pl-2 pr-1 text-blueprint">
              {attachmentShort(a)}
              <button onClick={() => onChange({ ...q, accepted: q.accepted.filter((x) => x !== a) })} aria-label={`Remover ${attachmentShort(a)}`} className="rounded-full p-0.5 hover:bg-blueprint/10"><X size={11} /></button>
            </span>
          </Tooltip>
        ))}
        {remaining.length > 0 && (
          <select value="" onChange={(e) => e.target.value && onChange({ ...q, accepted: [...q.accepted, e.target.value] })} aria-label="Adicionar tipo de anexo aceito"
            className="rounded-full border border-dashed border-line bg-sheet px-2 py-0.5 text-[12px] text-muted hover:border-blueprint">
            <option value="">+ tipo de anexo</option>
            {remaining.map((a) => <option key={a} value={a} title={attachments[a]}>{attachmentShort(a)}</option>)}
          </select>
        )}
      </div>
      {problems.length > 0 && <p className="mt-1 pl-7 text-[12px] text-bad">Falta: {problems.join(", ")}.</p>}
    </li>
  );
}

export const ATTACHMENT_SHORT: Record<string, string> = {
  quote_doc: "Orçamento (planilha)", completion_certificate_doc: "Termo de conclusão", technical_report_doc: "Relatório técnico",
  price_reference_doc: "Referência de preço",
  room_before_photo: "Foto do antes", room_after_photo: "Foto do depois", equipment_photo: "Foto de equipamento",
  label_photo: "Foto da etiqueta", removed_items_photo: "Foto dos itens retirados", cctv_screen_photo: "Imagem de câmera/monitor",
  alarm_panel_photo: "Foto da central de alarme", other: "Outro",
};
export const attachmentShort = (a: string) => ATTACHMENT_SHORT[a] ?? a;

function AttachmentTypes({ data, base, onChange }: { data: ChecklistsConfig; base: ChecklistsConfig; onChange: (d: ChecklistsConfig) => void }) {
  return (
    <details className="group rounded-xl border border-line bg-sheet">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-5 py-3 font-semibold">
        <ChevronDown size={16} className="text-muted transition group-open:rotate-180" /> Tipos de anexo reconhecidos ({Object.keys(data.attachment_categories).length})
        <span className="text-[13px] font-normal text-muted">avançado</span>
      </summary>
      <div className="space-y-3 border-t border-line px-5 py-4">
        <p className="text-[13px] text-muted">
          A identificação dos anexos usa estas descrições para classificar cada foto ou documento. Mudar o texto muda como o modelo classifica: prefira ajustes pontuais e rode a Validação depois.
          Novos tipos exigem mudança no código.
        </p>
        {Object.entries(data.attachment_categories).map(([k, v]) => (
          <label key={k} className="grid gap-1 text-sm md:grid-cols-[200px_1fr] md:items-center">
            <span className="font-medium">{attachmentShort(k)} <span className="font-mono text-[11px] text-muted">{k}</span></span>
            <input value={v} onChange={(e) => onChange({ ...data, attachment_categories: { ...data.attachment_categories, [k]: e.target.value } })}
              className={`rounded-md border px-2 py-1 ${v !== base.attachment_categories[k] ? "border-warn bg-[#fdf6e4]" : "border-line"}`} />
          </label>
        ))}
      </div>
    </details>
  );
}
