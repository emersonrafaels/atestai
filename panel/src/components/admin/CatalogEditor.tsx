import { Plus, RotateCcw, Search, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { CatalogConfig, CatalogKind, CatalogUsage, ChecklistsConfig, Option } from "../../api";
import { InfoBox } from "../ui/InfoBox";
import { Switch } from "../ui/Switch";
import { Tooltip } from "../ui/Tooltip";

type Entry = Required<Option>;
interface Props {
  data: CatalogConfig;
  base: CatalogConfig;
  onChange: (next: CatalogConfig) => void;
  /** onde cada código aparece nos chamados e gabaritos (do servidor) */
  usage: Record<CatalogKind, Record<string, CatalogUsage>>;
  /** checklist em edição: conta as regras que usam cada categoria */
  checklists: ChecklistsConfig;
}

const KINDS: { id: CatalogKind; label: string; one: string; hint: string }[] = [
  { id: "categories", label: "Categorias", one: "categoria", hint: "Especialidade do chamado. Define o checklist e em qual esteira (SETA ou SISR) ela aparece." },
  { id: "symptoms", label: "Sintomas", one: "sintoma", hint: "A queixa em uma expressão. Ligue cada sintoma às categorias em que ele faz sentido." },
  { id: "locations", label: "Locais", one: "local", hint: "Onde fica o serviço na agência (backoffice, tesouraria, fachada…)." },
];
const WS_OPTIONS: [string, string][] = [["", "SETA e SISR"], ["SETA", "SETA"], ["SISR", "SISR"]];

const slug = (s: string) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40);
const sameEntry = (a?: Entry, b?: Entry) => !!a && !!b && JSON.stringify(a) === JSON.stringify(b);

/** Cadastro de categorias, sintomas e locais: incluir, renomear, ligar (esteira / categorias), desativar e apagar o que não tem uso. */
export function CatalogEditor({ data, base, onChange, usage, checklists }: Props) {
  const [kind, setKind] = useState<CatalogKind>("categories");
  const [q, setQ] = useState("");
  const [showOff, setShowOff] = useState(true);
  const meta = KINDS.find((k) => k.id === kind)!;
  const list = data[kind];
  const baseBy = useMemo(() => new Map(base[kind].map((e) => [e.value, e])), [base, kind]);
  const catLabel = (v: string) => data.categories.find((c) => c.value === v)?.label ?? v;

  const rulesUsing = (code: string) => checklists.rules.filter((r) => r.category === code).length;
  const usageOf = (code: string): CatalogUsage => {
    const u = usage[kind]?.[code] ?? { tickets: 0, ground_truth: 0, rules: 0 };
    return { ...u, rules: kind === "categories" ? rulesUsing(code) : 0 };
  };

  const setList = (k: CatalogKind, next: Entry[]) => onChange({ ...data, [k]: next });
  const update = (i: number, patch: Partial<Entry>) => setList(kind, list.map((e, j) => (j === i ? { ...e, ...patch } : e)));
  const remove = (i: number) => {
    const code = list[i].value;
    const next = { ...data, [kind]: list.filter((_, j) => j !== i) };
    if (kind === "categories") next.symptoms = data.symptoms.map((s) => ({ ...s, categories: s.categories.filter((c) => c !== code) }));
    onChange(next);
  };

  const visible = list
    .map((e, i) => ({ e, i }))
    .filter(({ e }) => (showOff || e.enabled) && (!q || `${e.label} ${e.value}`.toLowerCase().includes(q.toLowerCase())));
  const offCount = list.filter((e) => !e.enabled).length;

  return (
    <div className="space-y-5">
      <InfoBox id="admin-catalog-edit" title="Como o cadastro funciona">
        O <b>nome</b> aparece no painel e no resumo enviado ao modelo; o <b>código</b> é o que fica gravado no chamado e não muda depois de criado.
        Item <b>desativado</b> some das listas de escolha (novo chamado, checklist), mas chamados antigos continuam mostrando o nome.
        Só dá para <b>apagar</b> o que nenhum chamado, gabarito ou regra de checklist usa.
      </InfoBox>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex rounded-lg bg-paper p-0.5 text-sm" role="tablist" aria-label="Cadastro">
          {KINDS.map((k) => (
            <button key={k.id} role="tab" aria-selected={kind === k.id} onClick={() => { setKind(k.id); setQ(""); }}
              className={`rounded-md px-3 py-1 ${kind === k.id ? "bg-sheet font-semibold shadow-sm" : "text-muted hover:text-ink"}`}>
              {k.label} <span className="tabular-nums text-muted">({data[k.id].filter((e) => e.enabled).length})</span>
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1.5 rounded-md border border-line bg-sheet px-2 py-1.5 text-sm focus-within:border-blueprint">
          <Search size={14} className="text-muted" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Buscar ${meta.one}`} className="w-44 bg-transparent outline-none" />
        </label>
        {offCount > 0 && <label className="flex items-center gap-2 text-sm text-muted"><Switch size="sm" on={showOff} onChange={setShowOff} label="Mostrar desativados" /> Mostrar desativados ({offCount})</label>}
      </div>
      <p className="-mt-2 text-[13px] text-muted">{meta.hint}</p>

      <NewEntry key={kind} kind={kind} one={meta.one} data={data} onAdd={(e) => setList(kind, [...list, e])} />

      <section className="overflow-x-auto rounded-xl border border-line bg-sheet">
        <table className="w-full min-w-[680px] text-sm">
          <thead className="bg-paper/60 text-left text-[12px] text-muted">
            <tr>
              <th className="w-14 px-4 py-2 font-medium">Ativo</th>
              <th className="px-2 py-2 font-medium">Nome</th>
              {kind === "categories" && <th className="px-2 py-2 font-medium">Esteira</th>}
              {kind === "symptoms" && <th className="px-2 py-2 font-medium">Vale para as categorias</th>}
              <th className="px-2 py-2 font-medium">Uso</th>
              <th className="w-10 px-4 py-2" />
            </tr>
          </thead>
          <tbody>
            {visible.map(({ e, i }) => {
              const b = baseBy.get(e.value);
              const status = !b ? "novo" : sameEntry(b, e) ? null : "alterado";
              const u = usageOf(e.value);
              const used = u.tickets + u.ground_truth + u.rules > 0;
              const dupLabel = e.enabled && list.some((x, j) => j !== i && x.enabled && x.label.trim().toLowerCase() === e.label.trim().toLowerCase());
              return (
                <tr key={e.value} className={`border-t border-line/70 align-top ${!e.enabled ? "bg-paper/50 text-muted" : status ? "bg-[#fffaf0]" : ""}`}>
                  <td className="px-4 py-2.5"><Switch on={e.enabled} onChange={(on) => update(i, { enabled: on })} label={`${e.label}: ${e.enabled ? "ativo" : "desativado"}`} /></td>
                  <td className="px-2 py-2">
                    <input value={e.label} onChange={(ev) => update(i, { label: ev.target.value })} aria-label={`Nome de ${e.value}`} title={`Código gravado no chamado: ${e.value}`}
                      className={`w-full min-w-40 rounded-md border px-2 py-1 ${!e.label.trim() || dupLabel ? "border-bad/60" : "border-transparent hover:border-line focus:border-blueprint"} ${e.enabled ? "" : "line-through"} bg-transparent outline-none`} />
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 px-2 text-[11px]">
                      {status && <span className={`rounded px-1.5 font-semibold uppercase ${status === "novo" ? "bg-blueprint-soft text-blueprint" : "bg-[#fdf1dc] text-warn"}`}>{status}</span>}
                      {status === "alterado" && b && <button onClick={() => update(i, b)} className="flex items-center gap-0.5 text-warn hover:underline"><RotateCcw size={11} /> desfazer</button>}
                      {!e.label.trim() && <span className="text-bad">dê um nome</span>}
                      {dupLabel && <span className="text-bad">nome repetido</span>}
                    </div>
                  </td>
                  {kind === "categories" && (
                    <td className="px-2 py-2">
                      <select value={e.workstreams.length === 1 ? e.workstreams[0] : ""} onChange={(ev) => update(i, { workstreams: ev.target.value ? [ev.target.value] : [] })}
                        aria-label={`Esteira de ${e.label}`} className="rounded-md border border-line bg-sheet px-1.5 py-1">
                        {WS_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                      </select>
                    </td>
                  )}
                  {kind === "symptoms" && (
                    <td className="px-2 py-2">
                      <CategoryLinks value={e.categories} options={data.categories} catLabel={catLabel} onChange={(categories) => update(i, { categories })} />
                    </td>
                  )}
                  <td className="px-2 py-2.5 text-[12px] text-muted">
                    {used ? [u.tickets && `${u.tickets} chamado(s)`, u.ground_truth && `${u.ground_truth} gabarito(s)`, u.rules && `${u.rules} regra(s) de checklist`].filter(Boolean).join(" · ") : "sem uso"}
                  </td>
                  <td className="px-4 py-2">
                    <Tooltip content={used ? "Em uso: desative em vez de apagar" : `Apagar ${meta.one}`}>
                      <button disabled={used} aria-label={`Apagar ${e.label}`}
                        onClick={() => { if (window.confirm(`Apagar ${meta.one} “${e.label}”?${kind === "categories" ? " Ela também sai dos sintomas ligados." : ""}`)) remove(i); }}
                        className="rounded-md p-1 text-muted hover:bg-[#fbefed] hover:text-bad disabled:pointer-events-none disabled:opacity-30"><Trash2 size={15} /></button>
                    </Tooltip>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!visible.length && <p className="p-6 text-center text-sm text-muted">Nada encontrado.</p>}
      </section>

      {/* removidos ainda não salvos: dá para trazer de volta */}
      {base[kind].some((b) => !list.some((e) => e.value === b.value)) && (
        <p className="text-[13px] text-muted">
          Apagados (ainda não salvos):{" "}
          {base[kind].filter((b) => !list.some((e) => e.value === b.value)).map((b) => (
            <button key={b.value} onClick={() => setList(kind, [...list, b])} className="mr-2 inline-flex items-center gap-1 text-blueprint hover:underline"><RotateCcw size={12} /> {b.label}</button>
          ))}
        </p>
      )}
    </div>
  );
}

function NewEntry({ kind, one, data, onAdd }: { kind: CatalogKind; one: string; data: CatalogConfig; onAdd: (e: Entry) => void }) {
  const [label, setLabel] = useState("");
  const [code, setCode] = useState("");
  const [codeTouched, setCodeTouched] = useState(false);
  const [ws, setWs] = useState("");
  const [cats, setCats] = useState<string[]>([]);
  const value = codeTouched ? code : slug(label);
  const list = data[kind];
  const problem = !label.trim() ? null
    : value.length < 2 ? "o código precisa de 2 a 40 letras minúsculas, números ou _"
    : list.some((e) => e.value === value) ? `já existe ${one} com o código “${value}”`
    : list.some((e) => e.enabled && e.label.trim().toLowerCase() === label.trim().toLowerCase()) ? `já existe ${one} com esse nome`
    : null;
  const add = (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!label.trim() || problem) return;
    onAdd({ value, label: label.trim(), enabled: true, workstreams: kind === "categories" && ws ? [ws] : [], categories: kind === "symptoms" ? cats : [] });
    setLabel(""); setCode(""); setCodeTouched(false); setCats([]);
  };
  const catLabel = (v: string) => data.categories.find((c) => c.value === v)?.label ?? v;
  return (
    <form onSubmit={add} className="rounded-xl border border-line bg-sheet p-4">
      <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold"><Plus size={15} className="text-blueprint" /> Incluir {one}</h3>
      <div className="flex flex-wrap items-end gap-3 text-sm">
        <label className="min-w-52 flex-1">
          <span className="mb-1 block text-[12px] font-medium text-muted">Nome</span>
          <input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={80} placeholder={kind === "categories" ? "Ex.: Vidraçaria" : kind === "symptoms" ? "Ex.: Vidro trincado" : "Ex.: Sala de reunião"}
            className="w-full rounded-md border border-line px-2 py-1.5 outline-none focus:border-blueprint" />
        </label>
        <label className="w-48">
          <span className="mb-1 block text-[12px] font-medium text-muted">Código (gravado no chamado)</span>
          <input value={value} onChange={(e) => { setCodeTouched(true); setCode(slug(e.target.value)); }} placeholder="gerado pelo nome"
            className="w-full rounded-md border border-line px-2 py-1.5 font-mono text-[13px] outline-none focus:border-blueprint" />
        </label>
        {kind === "categories" && (
          <label>
            <span className="mb-1 block text-[12px] font-medium text-muted">Esteira</span>
            <select value={ws} onChange={(e) => setWs(e.target.value)} className="rounded-md border border-line bg-sheet px-2 py-1.5">
              {WS_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
        )}
        <button type="submit" disabled={!label.trim() || !!problem}
          className="flex items-center gap-1.5 rounded-lg bg-blueprint px-3 py-1.5 font-semibold text-white hover:bg-[#1d44a0] disabled:opacity-50"><Plus size={14} /> Incluir</button>
      </div>
      {kind === "symptoms" && (
        <div className="mt-3 text-sm">
          <span className="mb-1 block text-[12px] font-medium text-muted">Vale para as categorias</span>
          <CategoryLinks value={cats} options={data.categories} catLabel={catLabel} onChange={setCats} />
        </div>
      )}
      {problem && <p className="mt-2 text-[12px] text-bad">Não dá para incluir: {problem}.</p>}
      <p className="mt-2 text-[12px] text-muted">O item entra na lista abaixo como rascunho; ele passa a valer quando você salvar.</p>
    </form>
  );
}

function CategoryLinks({ value, options, catLabel, onChange }: { value: string[]; options: Entry[]; catLabel: (v: string) => string; onChange: (v: string[]) => void }) {
  const remaining = options.filter((c) => c.enabled && !value.includes(c.value));
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
      {!value.length && <span className="rounded-full bg-paper px-2 py-0.5 text-muted ring-1 ring-line">todas as categorias</span>}
      {value.map((c) => (
        <span key={c} className="flex items-center gap-1 rounded-full bg-blueprint-soft py-0.5 pl-2 pr-1 text-blueprint">
          {catLabel(c)}
          <button type="button" onClick={() => onChange(value.filter((x) => x !== c))} aria-label={`Tirar ${catLabel(c)}`} className="rounded-full p-0.5 hover:bg-blueprint/10"><X size={11} /></button>
        </span>
      ))}
      {remaining.length > 0 && (
        <select value="" onChange={(e) => e.target.value && onChange([...value, e.target.value])} aria-label="Ligar a uma categoria"
          className="rounded-full border border-dashed border-line bg-sheet px-2 py-0.5 text-[12px] text-muted hover:border-blueprint">
          <option value="">+ categoria</option>
          {remaining.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
      )}
    </div>
  );
}
