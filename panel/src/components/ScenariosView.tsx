import { CheckSquare, ExternalLink, Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { Dataset, Recommendation, ScenarioTag, TicketSummary } from "../api";
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
const CHIPS_SHOWN = 14;

/**
 * Cenários de teste: um catálogo com um chamado por tipo de problema (conjunto "scenarios") e, para cada tipo de
 * cenário, os chamados de todos os conjuntos que o trazem, pelo gabarito. Serve para achar rápido um caso de
 * "escopo mal preenchido", "orçamento com vários erros" etc. e abri-lo ou analisá-lo.
 */
export function ScenariosView({ tickets, tags, datasets, openTicket, selectTickets }: Props) {
  const [dataset, setDataset] = useState("all");
  const [query, setQuery] = useState("");
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

  return (
    <div className="mx-auto max-w-[1180px] space-y-5 px-4 py-6 sm:px-6">
      <div>
        <h2 className="largo text-2xl font-bold text-blueprint">Cenários de teste</h2>
        <p className="text-sm text-muted">Ache um chamado por tipo de problema e abra ou analise com um clique. A mesma lista está em <code>docs/cenarios.md</code>.</p>
      </div>
      <InfoBox id="scenarios-intro" title="Como usar">
        O <b>catálogo</b> tem um chamado para cada cenário, com os defeitos fixos. Abaixo, <b>por tipo de problema</b>, aparecem os
        chamados de todos os conjuntos que trazem aquele problema no gabarito. Clique num chamado para abrir na Análise, ou em
        <b> Selecionar</b> para marcar todos e analisar de uma vez.
      </InfoBox>

      {catalog.length > 0 && (
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
      )}

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <h3 className="mr-auto text-lg font-semibold">Por tipo de problema</h3>
        <label className="flex items-center gap-2 rounded-lg border border-line bg-sheet px-2.5 py-1.5">
          <Search size={14} className="text-muted" aria-hidden />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar cenário (ex.: escopo, preço)" aria-label="Buscar cenário" className="w-56 bg-transparent outline-none" />
        </label>
        <label htmlFor="sc-dataset" className="text-muted">Conjunto</label>
        <select id="sc-dataset" value={dataset} onChange={(e) => setDataset(e.target.value)} className="rounded-lg border border-line bg-sheet px-2 py-1.5">
          <option value="all">Todos</option>
          {datasets.filter((d) => d.name !== "all").map((d) => <option key={d.name} value={d.name}>{d.label.split(" (")[0]}</option>)}
        </select>
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
    </div>
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
