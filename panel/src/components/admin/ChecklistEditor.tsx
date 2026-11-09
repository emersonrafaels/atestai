import { ChevronDown, Copy, Plus, Search, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { ChecklistRequirementConfig, ChecklistRuleConfig, ChecklistsConfig } from "../../api";
import { MAINTENANCE_LABEL, STAGE_LABEL } from "../../format";
import { InfoBox } from "../ui/InfoBox";
import { Switch } from "../ui/Switch";
import { Tooltip } from "../ui/Tooltip";

interface Props {
  data: ChecklistsConfig;
  base: ChecklistsConfig;
  onChange: (next: ChecklistsConfig) => void;
  categories: { value: string; label: string }[];
}

const ANY = "*";
const key = (r: { category: string; maintenance: string; moment: string }) => `${r.category}/${r.maintenance}/${r.moment}`;

/** Mesma regra do backend (config.Checklists.rule_for): a regra ativa mais específica; em empate, a última. */
export function ruleFor(rules: ChecklistRuleConfig[], category: string, maintenance: string, moment: string): number | null {
  let best: [number, number] | null = null;
  rules.forEach((r, i) => {
    if (!r.enabled) return;
    let points = 0;
    for (const [rv, v] of [[r.category, category], [r.maintenance, maintenance], [r.moment, moment]]) {
      if (rv === ANY) continue;
      if (rv !== v) return;
      points++;
    }
    if (!best || points > best[0] || (points === best[0] && i > best[1])) best = [points, i];
  });
  return best ? (best as [number, number])[1] : null;
}

const slug = (s: string) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40);

export function ChecklistEditor({ data, base, onChange, categories }: Props) {
  const catLabel = (v: string) => (v === ANY ? "Qualquer categoria" : categories.find((c) => c.value === v)?.label ?? v);
  const [filter, setFilter] = useState<string>("all");
  const [q, setQ] = useState("");
  const [showOff, setShowOff] = useState(true);
  const [sim, setSim] = useState({ category: categories[0]?.value ?? "", maintenance: "corrective", moment: "execution" });
  const [creating, setCreating] = useState(false);
  const baseByKey = useMemo(() => new Map(base.rules.map((r) => [key(r), r])), [base]);

  const setRule = (i: number, r: ChecklistRuleConfig) => onChange({ ...data, rules: data.rules.map((x, k) => (k === i ? r : x)) });
  const removeRule = (i: number) => onChange({ ...data, rules: data.rules.filter((_, k) => k !== i) });

  const simIdx = ruleFor(data.rules, sim.category, sim.maintenance, sim.moment);
  const simRule = simIdx !== null ? data.rules[simIdx] : null;

  const visible = data.rules
    .map((r, i) => ({ r, i }))
    .filter(({ r }) => (filter === "all" || (filter === "general" ? r.category === ANY : r.category === filter)) && (showOff || r.enabled))
    .filter(({ r }) => !q || `${catLabel(r.category)} ${r.requirements.map((x) => x.description).join(" ")}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => (a.r.category === ANY ? -1 : 0) - (b.r.category === ANY ? -1 : 0) || catLabel(a.r.category).localeCompare(catLabel(b.r.category), "pt-BR"));

  const goToRule = (i: number) => {
    setFilter("all"); setQ(""); setShowOff(true);
    requestAnimationFrame(() => {
      const el = document.getElementById(`rule-${i}`);
      el?.scrollIntoView({ behavior: "smooth", block: "start" });
      el?.classList.remove("piscar"); void el?.offsetWidth; el?.classList.add("piscar");
    });
  };

  return (
    <div className="space-y-5">
      <InfoBox id="admin-checklist" title="Como o checklist é escolhido">
        Para cada chamado vale a <b>regra ativa mais específica</b> que combina categoria × tipo de manutenção × etapa da esteira
        (“Qualquer” vale para todos). Exigência desativada não é cobrada; regra desativada é ignorada e cai para a próxima mais geral.
      </InfoBox>

      {/* simulador */}
      <section className="rounded-xl border border-line bg-sheet p-5">
        <h3 className="font-semibold">Qual checklist vale para…</h3>
        <p className="mb-3 text-[13px] text-muted">Escolha uma combinação para ver a regra aplicada, já com as suas alterações não salvas.</p>
        <div className="grid gap-3 text-sm sm:grid-cols-3">
          <Select label="Categoria" value={sim.category} onChange={(v) => setSim({ ...sim, category: v })} options={categories.map((c) => [c.value, c.label])} />
          <Select label="Tipo de manutenção" value={sim.maintenance} onChange={(v) => setSim({ ...sim, maintenance: v })} options={[["corrective", "Corretiva"], ["preventive", "Preventiva"]]} />
          <Select label="Etapa da esteira" value={sim.moment} onChange={(v) => setSim({ ...sim, moment: v })} options={[["quote", STAGE_LABEL.quote], ["execution", STAGE_LABEL.execution]]} />
        </div>
        <div className="mt-3 rounded-lg bg-paper/60 p-3 text-sm">
          {simRule ? (
            <>
              <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                <span>Vale a regra <b>{ruleTitle(simRule, catLabel)}</b>{simRule.category === ANY ? <span className="text-muted"> (regra geral: não há uma específica ativa)</span> : null}</span>
                <button onClick={() => goToRule(simIdx!)} className="text-[13px] font-medium text-blueprint hover:underline">Editar esta regra</button>
              </div>
              <ol className="list-decimal space-y-0.5 pl-5">
                {simRule.requirements.filter((r) => r.enabled).map((r) => <li key={r.id}>{r.description}</li>)}
              </ol>
              {simRule.requirements.some((r) => !r.enabled) && <p className="mt-1 text-[12px] text-muted">{simRule.requirements.filter((r) => !r.enabled).length} exigência(s) desativada(s) não entram.</p>}
            </>
          ) : <span className="text-bad">Nenhuma regra ativa se aplica: o checklist fica vazio para essa combinação.</span>}
        </div>
      </section>

      {/* barra de filtros */}
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <select value={filter} onChange={(e) => setFilter(e.target.value)} className="rounded-md border border-line bg-sheet px-2 py-1.5">
          <option value="all">Todas as regras ({data.rules.length})</option>
          <option value="general">Regras gerais</option>
          {categories.map((c) => <option key={c.value} value={c.value}>{c.label} ({data.rules.filter((r) => r.category === c.value).length})</option>)}
        </select>
        <label className="flex items-center gap-1.5 rounded-md border border-line bg-sheet px-2 py-1.5 focus-within:border-blueprint">
          <Search size={14} className="text-muted" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar exigência" className="w-44 bg-transparent outline-none" />
        </label>
        <label className="flex items-center gap-2 text-muted"><Switch size="sm" on={showOff} onChange={setShowOff} label="Mostrar regras desativadas" /> Mostrar desativadas</label>
        <button onClick={() => setCreating(true)} className="ml-auto flex items-center gap-1.5 rounded-lg bg-blueprint px-3 py-1.5 font-semibold text-white hover:bg-[#1d44a0]"><Plus size={15} /> Nova regra</button>
      </div>

      {creating && (
        <NewRule data={data} categories={categories} catLabel={catLabel} onCancel={() => setCreating(false)}
          onCreate={(r) => { onChange({ ...data, rules: [...data.rules, r] }); setCreating(false); setTimeout(() => goToRule(data.rules.length), 50); }} />
      )}

      <div className="space-y-4">
        {visible.map(({ r, i }) => {
          const b = baseByKey.get(key(r));
          const status = !b ? "nova" : JSON.stringify(b) !== JSON.stringify(r) ? "alterada" : null;
          return (
            <RuleCard key={key(r) + i} id={`rule-${i}`} rule={r} status={status} catLabel={catLabel} attachments={data.attachment_categories}
              onChange={(nr) => setRule(i, nr)} onRemove={() => { if (window.confirm(`Remover a regra ${ruleTitle(r, catLabel)}?`)) removeRule(i); }} />
          );
        })}
        {!visible.length && <p className="rounded-xl border border-dashed border-line bg-sheet p-6 text-center text-sm text-muted">Nenhuma regra com esse filtro.</p>}
      </div>

      <AttachmentTypes data={data} base={base} onChange={onChange} />
    </div>
  );
}

function ruleTitle(r: ChecklistRuleConfig, catLabel: (v: string) => string) {
  return `${catLabel(r.category)} · ${r.maintenance === ANY ? "qualquer tipo" : MAINTENANCE_LABEL[r.maintenance].toLowerCase()} · ${r.moment === ANY ? "qualquer etapa" : STAGE_LABEL[r.moment]}`;
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[12px] font-medium text-muted">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="w-full rounded-md border border-line bg-sheet px-2 py-1.5">
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

function RuleCard({ id, rule, status, catLabel, attachments, onChange, onRemove }: {
  id: string; rule: ChecklistRuleConfig; status: "nova" | "alterada" | null; catLabel: (v: string) => string;
  attachments: Record<string, string>; onChange: (r: ChecklistRuleConfig) => void; onRemove: () => void;
}) {
  const [open, setOpen] = useState(true);
  const setReq = (k: number, q: ChecklistRequirementConfig) => onChange({ ...rule, requirements: rule.requirements.map((x, j) => (j === k ? q : x)) });
  const addReq = () => onChange({ ...rule, requirements: [...rule.requirements, { id: "", description: "", accepted: [], enabled: true }] });
  const active = rule.requirements.filter((q) => q.enabled).length;
  return (
    <section id={id} className={`scroll-mt-20 rounded-xl border bg-sheet transition-opacity ${rule.enabled ? "border-line" : "border-dashed border-line opacity-70"}`}>
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-4 py-3">
        <Switch on={rule.enabled} onChange={(v) => onChange({ ...rule, enabled: v })} label={`Regra ${rule.enabled ? "ativa" : "desativada"}`} />
        <button onClick={() => setOpen(!open)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
          <ChevronDown size={16} className={`shrink-0 text-muted transition ${open ? "" : "-rotate-90"}`} />
          <span className="font-semibold">{catLabel(rule.category)}</span>
          <Chip>{rule.maintenance === ANY ? "Qualquer tipo" : MAINTENANCE_LABEL[rule.maintenance]}</Chip>
          <Chip>{rule.moment === ANY ? "Qualquer etapa" : STAGE_LABEL[rule.moment]}</Chip>
          <span className="text-[12px] text-muted">{active} de {rule.requirements.length} exigências ativas</span>
        </button>
        {status && <span className={`rounded px-1.5 text-[11px] font-semibold uppercase ${status === "nova" ? "bg-blueprint-soft text-blueprint" : "bg-[#fdf1dc] text-warn"}`}>{status}</span>}
        {!rule.enabled && <span className="rounded bg-paper px-1.5 text-[11px] font-semibold uppercase text-muted">desativada</span>}
        <Tooltip content="Remover a regra"><button onClick={onRemove} aria-label="Remover a regra" className="rounded-md p-1 text-muted hover:bg-[#fbefed] hover:text-bad"><Trash2 size={16} /></button></Tooltip>
      </header>
      {open && (
        <div className="space-y-2 p-4">
          {rule.requirements.map((q, k) => (
            <Requirement key={k} q={q} attachments={attachments} onChange={(nq) => setReq(k, nq)}
              onRemove={() => onChange({ ...rule, requirements: rule.requirements.filter((_, j) => j !== k) })}
              existingIds={rule.requirements.filter((_, j) => j !== k).map((x) => x.id)} />
          ))}
          <button onClick={addReq} className="flex items-center gap-1.5 rounded-md px-2 py-1 text-sm font-medium text-blueprint hover:bg-blueprint-soft"><Plus size={14} /> Adicionar exigência</button>
        </div>
      )}
    </section>
  );
}

function Requirement({ q, attachments, onChange, onRemove, existingIds }: {
  q: ChecklistRequirementConfig; attachments: Record<string, string>; onChange: (q: ChecklistRequirementConfig) => void; onRemove: () => void; existingIds: string[];
}) {
  const remaining = Object.keys(attachments).filter((a) => !q.accepted.includes(a));
  const dupId = !!q.id && existingIds.includes(q.id);
  const problems = [!q.description.trim() && "descreva a exigência", !q.accepted.length && "aceite ao menos um tipo de anexo", dupId && "identificador repetido"].filter(Boolean);
  return (
    <div className={`grid gap-2 rounded-lg border p-3 md:grid-cols-[auto_1fr_auto] ${q.enabled ? "border-line/80" : "border-dashed border-line bg-paper/40"} ${problems.length ? "border-bad/50" : ""}`}>
      <div className="pt-1"><Switch size="sm" on={q.enabled} onChange={(v) => onChange({ ...q, enabled: v })} label={`Exigência ${q.enabled ? "ativa" : "desativada"}`} /></div>
      <div className="min-w-0 space-y-2">
        <input value={q.description} placeholder="Ex.: Foto do ambiente depois do serviço"
          onChange={(e) => onChange({ ...q, description: e.target.value })}
          onBlur={() => { if (!q.id && q.description) onChange({ ...q, id: slug(q.description) }); }}
          className={`w-full rounded-md border px-2 py-1 text-sm ${q.enabled ? "" : "text-muted line-through"} ${!q.description.trim() ? "border-bad/60" : "border-line"}`} />
        <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
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
            <select value="" onChange={(e) => e.target.value && onChange({ ...q, accepted: [...q.accepted, e.target.value] })}
              className="rounded-full border border-dashed border-line bg-sheet px-2 py-0.5 text-[12px] text-muted hover:border-blueprint">
              <option value="">+ tipo de anexo</option>
              {remaining.map((a) => <option key={a} value={a} title={attachments[a]}>{attachmentShort(a)}</option>)}
            </select>
          )}
          <span className="ml-auto font-mono text-[11px] text-muted" title="Identificador interno da exigência">
            {q.id ? q.id : <input value={q.id} onChange={(e) => onChange({ ...q, id: slug(e.target.value) })} placeholder="identificador" className="w-28 rounded border border-line px-1" />}
          </span>
        </div>
        {problems.length > 0 && <p className="text-[12px] text-bad">Falta: {problems.join(", ")}.</p>}
      </div>
      <Tooltip content="Remover a exigência"><button onClick={onRemove} aria-label="Remover a exigência" className="h-fit rounded-md p-1 text-muted hover:bg-[#fbefed] hover:text-bad"><Trash2 size={15} /></button></Tooltip>
    </div>
  );
}

export const ATTACHMENT_SHORT: Record<string, string> = {
  quote_doc: "Orçamento (planilha)", completion_certificate_doc: "Termo de conclusão", technical_report_doc: "Relatório técnico",
  room_before_photo: "Foto do antes", room_after_photo: "Foto do depois", equipment_photo: "Foto de equipamento",
  label_photo: "Foto da etiqueta", removed_items_photo: "Foto dos itens retirados", cctv_screen_photo: "Imagem de câmera/monitor",
  alarm_panel_photo: "Foto da central de alarme", other: "Outro",
};
export const attachmentShort = (a: string) => ATTACHMENT_SHORT[a] ?? a;

function NewRule({ data, categories, catLabel, onCancel, onCreate }: {
  data: ChecklistsConfig; categories: { value: string; label: string }[]; catLabel: (v: string) => string;
  onCancel: () => void; onCreate: (r: ChecklistRuleConfig) => void;
}) {
  const [r, setR] = useState({ category: categories[0]?.value ?? ANY, maintenance: ANY, moment: "execution" });
  const [copy, setCopy] = useState(true);
  const exists = data.rules.some((x) => key(x) === key(r));
  const from = ruleFor(data.rules, r.category === ANY ? "__" : r.category, r.maintenance === ANY ? "corrective" : r.maintenance, r.moment === ANY ? "execution" : r.moment);
  const source = from !== null ? data.rules[from] : null;
  return (
    <section className="surgir rounded-xl border-2 border-blueprint/40 bg-sheet p-5">
      <div className="mb-3 flex items-center justify-between"><h3 className="font-semibold">Nova regra de checklist</h3><button onClick={onCancel} aria-label="Cancelar" className="rounded-md p-1 text-muted hover:bg-paper"><X size={16} /></button></div>
      <div className="grid gap-3 text-sm sm:grid-cols-3">
        <Select label="Categoria" value={r.category} onChange={(v) => setR({ ...r, category: v })} options={[[ANY, "Qualquer categoria"], ...categories.map((c) => [c.value, c.label] as [string, string])]} />
        <Select label="Tipo de manutenção" value={r.maintenance} onChange={(v) => setR({ ...r, maintenance: v })} options={[[ANY, "Qualquer tipo"], ["corrective", "Corretiva"], ["preventive", "Preventiva"]]} />
        <Select label="Etapa da esteira" value={r.moment} onChange={(v) => setR({ ...r, moment: v })} options={[[ANY, "Qualquer etapa"], ["quote", STAGE_LABEL.quote], ["execution", STAGE_LABEL.execution]]} />
      </div>
      {source && (
        <label className="mt-3 flex items-center gap-2 text-sm">
          <input type="checkbox" checked={copy} onChange={(e) => setCopy(e.target.checked)} className="size-4 accent-[var(--color-blueprint)]" />
          <Copy size={14} className="text-muted" /> Começar com as exigências da regra que vale hoje: <b>{ruleTitle(source, catLabel)}</b>
        </label>
      )}
      <div className="mt-4 flex items-center justify-end gap-2">
        {exists && <span className="mr-auto text-sm text-bad">Já existe uma regra para essa combinação: edite a que está na lista.</span>}
        <button onClick={onCancel} className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-paper">Cancelar</button>
        <button disabled={exists} onClick={() => onCreate({ ...r, enabled: true, requirements: copy && source ? source.requirements.map((x) => ({ ...x })) : [{ id: "quote", description: "Orçamento na planilha Excel padrão", accepted: ["quote_doc"], enabled: true }] })}
          className="rounded-lg bg-blueprint px-3 py-1.5 text-sm font-semibold text-white hover:bg-[#1d44a0] disabled:opacity-50">Criar regra</button>
      </div>
    </section>
  );
}

function AttachmentTypes({ data, base, onChange }: { data: ChecklistsConfig; base: ChecklistsConfig; onChange: (d: ChecklistsConfig) => void }) {
  return (
    <details className="group rounded-xl border border-line bg-sheet">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-5 py-3 font-semibold">
        <ChevronDown size={16} className="text-muted transition group-open:rotate-180" /> Tipos de anexo reconhecidos ({Object.keys(data.attachment_categories).length})
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

function Chip({ children }: { children: React.ReactNode }) {
  return <span className="rounded-full bg-paper px-2 py-0.5 text-[12px] font-medium text-ink/70">{children}</span>;
}
