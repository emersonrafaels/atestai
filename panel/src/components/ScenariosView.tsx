import { Check, CheckSquare, ExternalLink, Link2, ListOrdered, Search, Sparkles, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, type Dataset, type DemoGuide, type GuideCase, type Recommendation, type ScenarioTag, type TicketSummary } from "../api";
import { findingLabel, REC } from "../format";
import { InfoBox } from "./ui/InfoBox";
import { Card } from "./ui/Panel";
import { Tooltip } from "./ui/Tooltip";

interface Props {
  tickets: TicketSummary[];
  tags: ScenarioTag[];
  datasets: Dataset[];
  /** abre o chamado na Análise */
  openTicket: (id: string) => void;
  /** marca os chamados na lista da Análise (para analisar de uma vez) e vai para lá */
  selectTickets: (ids: string[]) => void;
}

const DATASET_SHORT: Record<string, string> = { validation: "Validação", casos: "Salesforce", itau: "Itaú", scenarios: "Cenários", uploaded: "Enviado" };
/** ordem dos botões do filtro: os conjuntos de demonstração primeiro */
const DATASET_ORDER = ["scenarios", "casos", "itau", "validation", "uploaded"];
/** conjuntos sem gabarito: não entram nos cartões "por tipo de problema" */
const NO_GROUND_TRUTH = new Set(["casos", "uploaded"]);
const FILTER_KEY = "atest.scenarios.dataset";
const CHIPS_SHOWN = 14;

const readFilter = () => {
  try { return localStorage.getItem(FILTER_KEY) || "all"; } catch { return "all"; }
};

/**
 * Cenários de teste: filtro por conjunto de dados, o que esperar de cada conjunto (data/demo_guide.toml), o roteiro
 * dos Casos Itaú - Salesforce (sem gabarito: o que foi plantado e o que mostrar), o catálogo com um chamado por tipo de
 * problema e, para cada tipo de cenário, os chamados que o trazem pelo gabarito.
 */
export function ScenariosView({ tickets, tags, datasets, openTicket, selectTickets }: Props) {
  const [filter, setFilterState] = useState(readFilter);
  const [query, setQuery] = useState("");
  const [guide, setGuide] = useState<DemoGuide | null>(null);
  useEffect(() => { api.guide().then(setGuide).catch(() => setGuide(null)); }, []);

  const options = useMemo(
    () => datasets.filter((d) => d.name !== "all" && d.n > 0)
      .sort((a, b) => (DATASET_ORDER.indexOf(a.name) + 1 || 99) - (DATASET_ORDER.indexOf(b.name) + 1 || 99)),
    [datasets],
  );
  // o conjunto lembrado pode ter sumido (ex.: apagou os enviados): volta para Todos
  const dataset = filter === "all" || options.some((d) => d.name === filter) || !datasets.length ? filter : "all";
  const setFilter = (d: string) => {
    setFilterState(d);
    try { localStorage.setItem(FILTER_KEY, d); } catch { /* armazenamento indisponível */ }
  };

  const byId = useMemo(() => new Map(tickets.map((t) => [t.ticket_id, t])), [tickets]);
  const catalog = tickets.filter((t) => t.scenario);
  const pool = tickets.filter((t) => dataset === "all" || t.dataset === dataset);
  const q = query.trim().toLowerCase();
  const visibleTags = tags.filter((t) => !q || `${t.label} ${t.description} ${t.group_label}`.toLowerCase().includes(q));
  const groups = useMemo(() => {
    const out: { id: string; label: string; tags: ScenarioTag[] }[] = [];
    for (const t of visibleTags) {
      const g = out.find((x) => x.id === t.group) ?? (out.push({ id: t.group, label: t.group_label, tags: [] }), out[out.length - 1]);
      g.tags.push(t);
    }
    return out;
  }, [visibleTags]);
  const info = dataset === "all" ? null : guide?.datasets[dataset];
  const total = datasets.find((d) => d.name === "all")?.n ?? tickets.length;

  return (
    <div className="mx-auto max-w-[1180px] space-y-5 px-4 py-6 sm:px-6">
      <div>
        <h2 className="largo text-2xl font-bold text-blueprint">Cenários de teste</h2>
        <p className="text-sm text-muted">Escolha o conjunto de dados, veja o que esperar e abra ou analise os chamados com um clique. O catálogo também está em <code>docs/cenarios.md</code>; o roteiro, em <code>data/demo_guide.toml</code>.</p>
      </div>

      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filtrar por conjunto de dados">
        <span className="mr-1 text-sm text-muted">Conjunto de dados</span>
        <FilterButton active={dataset === "all"} onClick={() => setFilter("all")} label="Todos" n={total} />
        {options.map((d) => (
          <FilterButton key={d.name} active={dataset === d.name} onClick={() => setFilter(d.name)}
            label={guide?.datasets[d.name]?.label ?? d.label.split(" (")[0]} n={d.n} noTruth={NO_GROUND_TRUTH.has(d.name)} />
        ))}
      </div>

      {dataset === "all" ? (
        <DatasetOverview options={options} guide={guide} pick={setFilter} />
      ) : info ? (
        <section className="rounded-xl border border-blueprint/25 bg-blueprint-soft/50 p-5" aria-label="O que esperar deste conjunto">
          <h3 className="flex items-center gap-2 font-semibold"><Sparkles size={16} className="text-blueprint" aria-hidden /> O que esperar: {info.label}</h3>
          <p className="mt-1.5 text-sm">{info.what}</p>
          <p className="mt-1.5 text-sm"><b className="font-semibold">Resultado:</b> {info.expect}</p>
          {info.tips.length > 0 && (
            <ul className="mt-2 list-disc space-y-0.5 pl-5 text-[13px] text-muted">{info.tips.map((t) => <li key={t}>{t}</li>)}</ul>
          )}
        </section>
      ) : null}

      {dataset === "casos" && guide && (
        <CasosGuide guide={guide} tickets={pool} byId={byId} openTicket={openTicket} selectTickets={selectTickets} />
      )}

      {dataset === "uploaded" && (
        <Card title="Chamados enviados" sub={`${pool.length} chamados enviados pelo painel`} aside={<SelectButton ids={pool.map((t) => t.ticket_id)} onSelect={selectTickets} />}>
          <div className="flex flex-wrap gap-1.5">{pool.map((t) => <TicketChip key={t.ticket_id} t={t} onOpen={openTicket} />)}</div>
        </Card>
      )}

      {catalog.length > 0 && (dataset === "all" || dataset === "scenarios") && (
        <>
          <InfoBox id="scenarios-intro" title="Como usar">
            O <b>catálogo</b> tem um chamado para cada cenário, com os defeitos fixos. Abaixo, <b>por tipo de problema</b>, aparecem os
            chamados dos conjuntos com gabarito que trazem aquele problema. Clique num chamado para abrir na Análise, ou em
            <b> Selecionar</b> para marcar todos e analisar de uma vez.
          </InfoBox>
          <Card title="Catálogo: um chamado por cenário" sub={`${catalog.length} chamados do conjunto Cenários, com o resultado que o Atest.AI deveria dar`}
            aside={<SelectButton ids={catalog.map((t) => t.ticket_id)} onSelect={selectTickets} />}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="text-left text-[12px] text-muted">
                  <tr><th className="py-2 pr-3 font-medium">Chamado</th><th className="py-2 pr-3 font-medium">Cenário</th><th className="py-2 pr-3 font-medium">Esperado</th><th className="py-2 font-medium">Apontamentos esperados</th></tr>
                </thead>
                <tbody>
                  {catalog.map((t) => (
                    <tr key={t.ticket_id} className="border-t border-line/70 align-top">
                      <td className="py-2 pr-3">
                        <button onClick={() => openTicket(t.ticket_id)} className="flex items-center gap-1 font-mono font-semibold text-blueprint hover:underline">
                          {t.ticket_id}<ExternalLink size={12} aria-hidden />
                        </button>
                        <span className="text-[12px] text-muted">{t.category_label}</span>
                      </td>
                      <td className="py-2 pr-3"><div className="font-medium">{t.scenario!.title}</div><div className="text-[13px] text-muted">{t.scenario!.description}</div></td>
                      <td className="py-2 pr-3">{t.expected && <RecBadge rec={t.expected.recommendation as Recommendation} score={t.expected.score} />}</td>
                      <td className="py-2 text-[13px] text-muted">{t.expected?.findings.length ? t.expected.findings.map((f) => findingLabel(f)).join(" · ") : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}

      {!NO_GROUND_TRUTH.has(dataset) && (
        <>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <h3 className="mr-auto text-lg font-semibold">Por tipo de problema{dataset !== "all" && <span className="font-normal text-muted"> · {DATASET_SHORT[dataset] ?? dataset}</span>}</h3>
            <label className="flex items-center gap-2 rounded-lg border border-line bg-sheet px-2.5 py-1.5">
              <Search size={14} className="text-muted" aria-hidden />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar cenário (ex.: escopo, preço)" aria-label="Buscar cenário" className="w-56 bg-transparent outline-none" />
            </label>
          </div>

          {groups.map((g) => (
            <section key={g.id}>
              <h4 className="mb-2 text-[13px] font-semibold uppercase tracking-wide text-muted">{g.label}</h4>
              <div className="grid gap-3 md:grid-cols-2">
                {g.tags.map((tag) => {
                  const found = pool.filter((t) => t.tags?.includes(tag.id));
                  return (
                    <div key={tag.id} className={`rounded-xl border border-line bg-sheet p-4 ${found.length ? "" : "opacity-60"}`}>
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="font-semibold">{tag.label} <span className="ml-1 rounded-full bg-paper px-2 py-0.5 text-[12px] font-medium tabular-nums text-muted">{found.length}</span></div>
                          <p className="text-[13px] text-muted">{tag.description}</p>
                        </div>
                        {found.length > 0 && <SelectButton ids={found.map((t) => t.ticket_id)} onSelect={selectTickets} />}
                      </div>
                      {found.length > 0 ? (
                        <div className="mt-3 flex flex-wrap gap-1.5">
                          {found.slice(0, CHIPS_SHOWN).map((t) => <TicketChip key={t.ticket_id} t={t} onOpen={openTicket} />)}
                          {found.length > CHIPS_SHOWN && <span className="self-center text-[12px] text-muted">+{found.length - CHIPS_SHOWN} (use Selecionar)</span>}
                        </div>
                      ) : <p className="mt-3 text-[13px] text-muted">Nenhum chamado neste conjunto.</p>}
                    </div>
                  );
                })}
              </div>
            </section>
          ))}
          {groups.length === 0 && <p className="text-muted">Nenhum cenário com "{query}".</p>}
        </>
      )}
    </div>
  );
}

function FilterButton({ active, onClick, label, n, noTruth }: { active: boolean; onClick: () => void; label: string; n: number; noTruth?: boolean }) {
  const btn = (
    <button onClick={onClick} aria-pressed={active}
      className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-medium transition-colors ${active ? "border-blueprint bg-blueprint text-white" : "border-line bg-sheet hover:border-blueprint hover:text-blueprint"}`}>
      {label}<span className={`rounded-full px-1.5 text-[11px] tabular-nums ${active ? "bg-white/20" : "bg-paper text-muted"}`}>{n}</span>
    </button>
  );
  return noTruth ? <Tooltip content="Sem gabarito: analise no modo API">{btn}</Tooltip> : btn;
}

/** "Todos": um resumo de cada conjunto, com atalho para filtrar. */
function DatasetOverview({ options, guide, pick }: { options: Dataset[]; guide: DemoGuide | null; pick: (d: string) => void }) {
  if (!guide) return null;
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {/* o Salesforce (com roteiro) primeiro, na largura toda; os demais em pares */}
      {[...options].sort((a, b) => Number(b.name === "casos") - Number(a.name === "casos")).map((d) => {
        const g = guide.datasets[d.name];
        if (!g) return null;
        return (
          <button key={d.name} onClick={() => pick(d.name)}
            className={`rounded-xl border bg-sheet p-4 text-left hover:border-blueprint ${d.name === "casos" ? "border-blueprint/40 md:col-span-2" : "border-line"}`}>
            <div className="flex items-center gap-2 font-semibold">
              {g.label}<span className="rounded-full bg-paper px-2 py-0.5 text-[12px] font-medium tabular-nums text-muted">{d.n}</span>
              {NO_GROUND_TRUTH.has(d.name) && <span className="rounded bg-[#fdf1dc] px-1.5 text-[11px] font-semibold text-warn">sem gabarito</span>}
            </div>
            <p className="mt-1 text-[13px]">{g.what}</p>
            <p className="mt-1 text-[13px] text-muted">{g.expect}</p>
            <span className="mt-2 inline-block text-[13px] font-medium text-blueprint">{d.name === "casos" ? "Ver o roteiro de cada chamado →" : "Ver só este conjunto →"}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Roteiro dos Casos Itaú - Salesforce: o que foi plantado em cada chamado e o que mostrar na tela. */
function CasosGuide({ guide, tickets, byId, openTicket, selectTickets }: {
  guide: DemoGuide; tickets: TicketSummary[]; byId: Map<string, TicketSummary>; openTicket: (id: string) => void; selectTickets: (ids: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const titles = new Map(guide.cases.map((c) => [c.id, c.title]));
  const match = (c: GuideCase) => {
    if (!q) return true;
    const t = byId.get(c.id);
    return [c.id, c.title, c.note, ...c.show, ...c.findings.map(findingLabel), ...c.expect.map((r) => REC[r]?.label ?? r), t?.branch ?? "", t?.category_label ?? ""]
      .join(" ").toLowerCase().includes(q);
  };
  const known = new Set(guide.cases.map((c) => c.id));
  const without = tickets.filter((t) => !known.has(t.ticket_id));
  const sections = guide.groups
    .map((g) => ({ ...g, cases: guide.cases.filter((c) => c.group === g.id && match(c)) }))
    .filter((g) => g.cases.length);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <h3 className="mr-auto flex items-center gap-2 text-lg font-semibold"><ListOrdered size={18} className="text-blueprint" aria-hidden /> Roteiro: o que mostrar em cada chamado</h3>
        <label className="flex items-center gap-2 rounded-lg border border-line bg-sheet px-2.5 py-1.5">
          <Search size={14} className="text-muted" aria-hidden />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar (ex.: duplicado, foto, 1520)" aria-label="Buscar no roteiro" className="w-56 bg-transparent outline-none" />
        </label>
        <SelectButton ids={guide.cases.map((c) => c.id).filter((id) => byId.has(id))} onSelect={selectTickets} />
      </div>

      {sections.map((g) => (
        <section key={g.id}>
          <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
            <div>
              <h4 className="text-[13px] font-semibold uppercase tracking-wide text-muted">{g.label} <span className="font-normal normal-case tracking-normal">· {g.cases.length}</span></h4>
              {g.description && <p className="text-[13px] text-muted">{g.description}</p>}
            </div>
            <SelectButton ids={g.cases.map((c) => c.id).filter((id) => byId.has(id))} onSelect={selectTickets} />
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {g.cases.map((c) => <GuideCard key={c.id} c={c} t={byId.get(c.id)} titles={titles} byId={byId} openTicket={openTicket} />)}
          </div>
        </section>
      ))}
      {sections.length === 0 && <p className="text-muted">Nenhum chamado do roteiro com "{query}".</p>}

      {without.length > 0 && !q && (
        <Card title="Sem roteiro" sub="Chamados deste conjunto que ainda não estão em data/demo_guide.toml">
          <div className="flex flex-wrap gap-1.5">{without.map((t) => <TicketChip key={t.ticket_id} t={t} onOpen={openTicket} />)}</div>
        </Card>
      )}
    </div>
  );
}

function GuideCard({ c, t, titles, byId, openTicket }: {
  c: GuideCase; t?: TicketSummary; titles: Map<string, string>; byId: Map<string, TicketSummary>; openTicket: (id: string) => void;
}) {
  const last = t?.last;
  const lastMatches = last ? c.expect.includes(last.recommendation) : false;
  return (
    <article className="flex flex-col rounded-xl border border-line bg-sheet p-4" aria-label={`Roteiro do chamado ${c.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <button onClick={() => openTicket(c.id)} disabled={!t}
              className="flex items-center gap-1 font-mono font-semibold text-blueprint hover:underline disabled:text-muted disabled:no-underline">
              {c.id}{t && <ExternalLink size={12} aria-hidden />}
            </button>
            <span className="font-semibold">{c.title}</span>
          </div>
          {t ? (
            <p className="text-[12px] text-muted">{t.branch} · {t.category_label} · {t.moment === "execution" ? "atestação do serviço" : "aprovação do orçamento"}</p>
          ) : <p className="text-[12px] text-bad">Pasta do chamado não encontrada em data/tickets.</p>}
        </div>
        <div className="flex flex-wrap items-center gap-1 text-[12px]">
          <span className="text-muted">Esperado</span>
          {c.expect.map((r, i) => <span key={r} className="flex items-center gap-1">{i > 0 && <span className="text-muted">ou</span>}<RecBadge rec={r} score={null} /></span>)}
        </div>
      </div>

      {c.findings.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1">
          {c.findings.map((f) => (
            <span key={f} className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${f === "possible_duplicate_ticket" || f === "reused_photo" ? "bg-[#fbefed] text-bad" : "bg-paper text-ink"}`}>{findingLabel(f)}</span>
          ))}
        </div>
      )}

      <ol className="mt-3 list-decimal space-y-1 pl-5 text-[13px] marker:font-semibold marker:text-blueprint">
        {c.show.map((s) => <li key={s}>{s}</li>)}
      </ol>
      {c.note && <p className="mt-2 text-[12px] text-muted">{c.note}</p>}

      <div className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-2 pt-3 text-[12px]">
        {c.linked.length > 0 && (
          <div className="flex flex-wrap items-center gap-1">
            <Link2 size={13} className="text-muted" aria-hidden /><span className="text-muted">Ligado a</span>
            {c.linked.map((id) => (
              <Tooltip key={id} content={titles.get(id) ?? byId.get(id)?.scope ?? id}>
                <button onClick={() => openTicket(id)} disabled={!byId.has(id)}
                  className="rounded border border-line bg-paper/60 px-1.5 py-0.5 font-mono font-semibold hover:border-blueprint hover:text-blueprint disabled:opacity-60">{id}</button>
              </Tooltip>
            ))}
          </div>
        )}
        <div className="ml-auto flex items-center gap-1">
          {last ? (
            <Tooltip content={`Último parecer (${last.mode === "api" ? "modo API" : "simulado"}), em ${new Date(last.generated_at).toLocaleString("pt-BR")}`}>
              <span className="flex items-center gap-1">
                <span className="text-muted">Último parecer</span><RecBadge rec={last.recommendation} score={last.score} />
                {lastMatches
                  ? <Check size={14} className="text-ok" aria-label="bate com o esperado" />
                  : <TriangleAlert size={13} className="text-warn" aria-label="difere do esperado" />}
              </span>
            </Tooltip>
          ) : <span className="text-muted">Ainda não analisado</span>}
        </div>
      </div>
    </article>
  );
}

function TicketChip({ t, onOpen }: { t: TicketSummary; onOpen: (id: string) => void }) {
  const rec = t.expected?.recommendation as Recommendation | undefined;
  return (
    <Tooltip content={<><b>{t.scenario?.title ?? t.category_label}</b><br />{t.scope}<br />Esperado: {rec ? REC[rec].label : "—"}</>}>
      <button onClick={() => onOpen(t.ticket_id)} className="flex items-center gap-1.5 rounded-md border border-line bg-paper/60 px-2 py-1 text-[12px] hover:border-blueprint hover:text-blueprint">
        {rec && <i className="size-2 rounded-full" style={{ background: REC[rec].color }} aria-hidden />}
        <span className="font-mono font-semibold">{t.ticket_id}</span>
        <span className="text-muted">{DATASET_SHORT[t.dataset] ?? t.dataset}</span>
      </button>
    </Tooltip>
  );
}

function RecBadge({ rec, score }: { rec: Recommendation; score: number | null }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-paper px-2 py-0.5 text-[12px] font-medium">
      <i className="size-2 rounded-full" style={{ background: REC[rec].color }} aria-hidden />{REC[rec].short}{score !== null && <span className="tabular-nums text-muted">· {score}</span>}
    </span>
  );
}

function SelectButton({ ids, onSelect }: { ids: string[]; onSelect: (ids: string[]) => void }) {
  return (
    <Tooltip content="Marca estes chamados na lista da Análise para analisar de uma vez">
      <button onClick={() => onSelect(ids)} className="flex shrink-0 items-center gap-1.5 rounded-lg border border-line px-2.5 py-1 text-[13px] font-medium text-blueprint hover:bg-paper">
        <CheckSquare size={14} aria-hidden /> Selecionar {ids.length}
      </button>
    </Tooltip>
  );
}
