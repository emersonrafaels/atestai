import { ChevronDown, Search, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import type { TicketSummary } from "../api";
import { REC, STAGE_LABEL, envLabel } from "../format";
import { activeChips, advancedCount, EMPTY_FILTERS, VERDICT_LABEL, type ListFilters } from "../ticketFilters";
import { InfoTip, Tooltip } from "./ui/Tooltip";

interface Props {
  filters: ListFilters;
  setFilters: (f: ListFilters) => void;
  /** chamados no escopo (conjunto + esteira), para as opções e contagens */
  scope: TicketSummary[];
  open: boolean;
  setOpen: (v: boolean) => void;
  /** bar = busca e botão Filtros (fixos no topo); panel = painel aberto e selos (rolam junto com a lista) */
  part: "bar" | "panel";
}

/** Valores distintos de um campo, com quantos chamados têm cada um, em ordem alfabética do rótulo. */
function options(scope: TicketSummary[], value: (c: TicketSummary) => string, label: (c: TicketSummary) => string) {
  const m = new Map<string, { label: string; n: number }>();
  for (const c of scope) {
    const v = value(c);
    if (!v) continue;
    const e = m.get(v);
    if (e) e.n++;
    else m.set(v, { label: label(c), n: 1 });
  }
  return [...m.entries()].map(([value, e]) => ({ value, ...e })).sort((a, b) => a.label.localeCompare(b.label, "pt-BR"));
}

const field = "w-full min-w-0 rounded-md border bg-sheet px-1.5 py-1";
const on = (active: boolean) => (active ? "border-blueprint text-blueprint" : "border-line");

function Label({ children, tip, term }: { children: React.ReactNode; tip?: string; term?: string }) {
  return (
    <span className="mb-0.5 flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted">
      {children}
      {tip && <InfoTip text={tip} size={11} />}
      {term && <InfoTip term={term} size={11} />}
    </span>
  );
}

/** Busca livre (sempre à vista), botão "Filtros" com o painel dos demais campos e os selos dos filtros ativos. */
export function TicketFilters({ filters: f, setFilters, scope, open, setOpen, part }: Props) {
  const set = <K extends keyof ListFilters>(k: K, v: ListFilters[K]) => setFilters({ ...f, [k]: v });
  const search = useRef<HTMLInputElement>(null);

  // "/" leva à busca (fora de campos de texto), como em outros sistemas
  useEffect(() => {
    if (part !== "bar") return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      if (t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName))) return;
      e.preventDefault();
      search.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [part]);

  const branches = useMemo(() => options(scope, (c) => c.branch, (c) => c.branch), [scope]);
  const categories = useMemo(() => options(scope, (c) => c.category, (c) => c.category_label), [scope]);
  const suppliers = useMemo(() => options(scope, (c) => c.supplier, (c) => c.supplier), [scope]);
  const places = useMemo(() => options(scope, (c) => c.environment, (c) => envLabel(c.environment)), [scope]);
  const count = (p: (c: TicketSummary) => boolean) => scope.filter(p).length;
  const catName = (v: string) => categories.find((o) => o.value === v)?.label ?? scope.find((c) => c.category === v)?.category_label ?? v;
  const chips = activeChips(f, { category: catName });
  const nAdvanced = advancedCount(f);
  const dates = scope.map((c) => c.opened_at).filter(Boolean).sort() as string[];

  if (part === "bar") return (
      <div className="flex shrink-0 items-center gap-2 border-b border-line px-4 py-2">
        <div className="relative min-w-0 flex-1">
          <Search size={14} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted" />
          <input ref={search} type="search" value={f.q} onChange={(e) => set("q", e.target.value)}
            aria-label="Buscar chamados" placeholder="Buscar nº, agência, texto…"
            onKeyDown={(e) => { if (e.key === "Escape") { set("q", ""); e.currentTarget.blur(); } }}
            className={`w-full rounded-md border bg-sheet py-1 pl-7 pr-7 text-sm [&::-webkit-search-cancel-button]:hidden ${on(!!f.q.trim())}`} />
          {f.q && (
            <button onClick={() => set("q", "")} aria-label="Limpar a busca" className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted hover:text-ink">
              <X size={14} />
            </button>
          )}
        </div>
        <InfoTip text="Busca em nº do chamado, agência (nome ou núm. do ponto), fornecedor, categoria, sintoma, escopo e solução, sem diferenciar acento. Vários nºs de chamado separados por espaço ou vírgula trazem todos eles; as outras palavras precisam aparecer todas. Atalho: / ." />
        <Tooltip content={open ? "Esconder os filtros" : "Mais filtros: agência, categoria, fornecedor, parecer, valor, data…"}>
          <button onClick={() => setOpen(!open)} aria-expanded={open} aria-controls="ticket-filters"
            className={`flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-sm ${nAdvanced ? "border-blueprint bg-blueprint-soft text-blueprint" : "border-line text-muted hover:text-ink"}`}>
            <SlidersHorizontal size={14} /> Filtros
            {nAdvanced > 0 && <span className="rounded-full bg-blueprint px-1.5 text-[11px] font-semibold tabular-nums leading-4 text-white">{nAdvanced}</span>}
            <ChevronDown size={13} className={`transition-transform ${open ? "rotate-180" : ""}`} />
          </button>
        </Tooltip>
      </div>
  );

  return (
    <>
      {open && (
        <div id="ticket-filters" className="grid grid-cols-2 gap-x-2 gap-y-1.5 border-b border-line bg-paper/40 px-4 py-2 text-[13px]">
          <label className="col-span-2 min-w-0">
            <Label tip="Nome (ou um trecho, sem acento) ou número do ponto, de 0 a 9999 — 418 encontra o 0418. Escolha na lista ou digite.">Agência</Label>
            <div className="relative">
              <input list="branch-options" value={f.branch} onChange={(e) => set("branch", e.target.value)} placeholder="Nome ou núm. do ponto"
                className={`${field} pr-6 ${on(!!f.branch.trim())}`} />
              {f.branch && (
                <button onClick={() => set("branch", "")} aria-label="Limpar a agência" className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted hover:text-ink">
                  <X size={13} />
                </button>
              )}
            </div>
            <datalist id="branch-options">
              {branches.map((o) => <option key={o.value} value={o.value}>{o.n} chamado{o.n === 1 ? "" : "s"}</option>)}
            </datalist>
          </label>

          <label className="min-w-0">
            <Label term="stage">Etapa</Label>
            <select value={f.stage} onChange={(e) => set("stage", e.target.value as ListFilters["stage"])} className={`${field} ${on(!!f.stage)}`}>
              <option value="">Todas ({scope.length})</option>
              <option value="quote">{STAGE_LABEL.quote} ({count((c) => c.moment === "quote")})</option>
              <option value="execution">{STAGE_LABEL.execution} ({count((c) => c.moment === "execution")})</option>
            </select>
          </label>
          <label className="min-w-0">
            <Label term="maintenance">Tipo</Label>
            <select value={f.kind} onChange={(e) => set("kind", e.target.value as ListFilters["kind"])} className={`${field} ${on(!!f.kind)}`}>
              <option value="">Todos ({scope.length})</option>
              <option value="corrective">Corretiva ({count((c) => c.maintenance_type === "corrective")})</option>
              <option value="preventive">Preventiva ({count((c) => c.maintenance_type === "preventive")})</option>
            </select>
          </label>

          <label className="min-w-0">
            <Label>Categoria</Label>
            <select value={f.category} onChange={(e) => set("category", e.target.value)} className={`${field} ${on(!!f.category)}`}>
              <option value="">Todas</option>
              {categories.map((o) => <option key={o.value} value={o.value}>{o.label} ({o.n})</option>)}
            </select>
          </label>
          <label className="min-w-0">
            <Label>Local</Label>
            <select value={f.environment} onChange={(e) => set("environment", e.target.value)} className={`${field} ${on(!!f.environment)}`}>
              <option value="">Todos</option>
              {places.map((o) => <option key={o.value} value={o.value}>{o.label} ({o.n})</option>)}
            </select>
          </label>

          <label className="col-span-2 min-w-0">
            <Label>Fornecedor</Label>
            <select value={f.supplier} onChange={(e) => set("supplier", e.target.value)} className={`${field} ${on(!!f.supplier)}`}>
              <option value="">Todos</option>
              {suppliers.map((o) => <option key={o.value} value={o.value}>{o.label} ({o.n})</option>)}
            </select>
          </label>

          <label className="min-w-0">
            <Label tip="O parecer desta execução; sem ele, o último gravado no banco. “Diferente do gabarito” só vale para conjuntos com gabarito.">Parecer</Label>
            <select value={f.verdict} onChange={(e) => set("verdict", e.target.value as ListFilters["verdict"])} className={`${field} ${on(!!f.verdict)}`}>
              <option value="">Todos</option>
              {(["none", "any", "dup", "diverged"] as const).map((k) => <option key={k} value={k}>{VERDICT_LABEL[k]}</option>)}
              <optgroup label="Recomendação">
                {(Object.keys(REC) as (keyof typeof REC)[]).map((r) => <option key={r} value={r}>{REC[r].label}</option>)}
              </optgroup>
            </select>
          </label>
          <label className="min-w-0">
            <Label>Impede abertura</Label>
            <select value={f.blocks} onChange={(e) => set("blocks", e.target.value as ListFilters["blocks"])} className={`${field} ${on(!!f.blocks)}`}>
              <option value="">Todos</option>
              <option value="yes">Sim ({count((c) => c.blocks_opening === true)})</option>
              <option value="no">Não ({count((c) => c.blocks_opening === false)})</option>
              <option value="unknown">Não informado ({count((c) => c.blocks_opening === null || c.blocks_opening === undefined)})</option>
            </select>
          </label>

          <div className="col-span-2 min-w-0">
            <Label tip="Valor orçado do chamado. Aceita 1500, 1.500,50 ou 1500.5. Chamados sem valor saem quando há limite.">Valor orçado (R$)</Label>
            <div className="flex items-center gap-1.5">
              <input inputMode="decimal" value={f.minValue} onChange={(e) => set("minValue", e.target.value)} placeholder="de" aria-label="Valor mínimo" className={`${field} ${on(!!f.minValue.trim())}`} />
              <span className="text-muted">a</span>
              <input inputMode="decimal" value={f.maxValue} onChange={(e) => set("maxValue", e.target.value)} placeholder="até" aria-label="Valor máximo" className={`${field} ${on(!!f.maxValue.trim())}`} />
            </div>
          </div>

          <div className="col-span-2 min-w-0">
            <Label tip={dates.length ? `Data de abertura. Neste escopo, de ${dates[0].split("-").reverse().join("/")} a ${dates[dates.length - 1].split("-").reverse().join("/")}.` : "Data de abertura."}>Aberto entre</Label>
            <div className="flex items-center gap-1.5">
              <input type="date" value={f.from} max={f.to || undefined} onChange={(e) => set("from", e.target.value)} aria-label="Aberto a partir de" className={`${field} ${on(!!f.from)}`} />
              <span className="text-muted">e</span>
              <input type="date" value={f.to} min={f.from || undefined} onChange={(e) => set("to", e.target.value)} aria-label="Aberto até" className={`${field} ${on(!!f.to)}`} />
            </div>
          </div>

          <label className="min-w-0">
            <Label>Fotos</Label>
            <select value={f.photos} onChange={(e) => set("photos", e.target.value as ListFilters["photos"])} className={`${field} ${on(!!f.photos)}`}>
              <option value="">Todos</option>
              <option value="with">Com fotos ({count((c) => c.n_photos > 0)})</option>
              <option value="without">Sem fotos ({count((c) => c.n_photos === 0)})</option>
            </select>
          </label>
          <div className="flex items-end justify-end">
            <button onClick={() => setFilters({ ...EMPTY_FILTERS, q: f.q })} disabled={!nAdvanced}
              className="rounded-md px-2 py-1 text-[12px] font-medium text-blueprint hover:bg-sheet disabled:text-muted disabled:opacity-60">
              Limpar estes filtros
            </button>
          </div>
        </div>
      )}

      {chips.length > 0 && (
        <ul aria-label="Filtros ativos" className="flex flex-wrap items-center gap-1.5 border-b border-line px-4 py-2">
          {chips.map((c) => (
            <li key={c.key.join()} className="flex max-w-full items-center rounded-full bg-blueprint-soft text-[12px] font-medium text-blueprint">
              <span className="truncate py-0.5 pl-2">{c.label}</span>
              <button onClick={() => setFilters({ ...f, ...Object.fromEntries(c.key.map((k) => [k, ""])) })} aria-label={`Tirar o filtro ${c.label}`}
                className="mx-0.5 rounded-full p-0.5 hover:bg-sheet"><X size={12} strokeWidth={2.5} /></button>
            </li>
          ))}
          {chips.length > 1 && (
            <li><button onClick={() => setFilters(EMPTY_FILTERS)} className="px-1 text-[12px] font-medium text-muted hover:text-bad">limpar tudo</button></li>
          )}
        </ul>
      )}
    </>
  );
}
