import { ArrowRight, BadgeDollarSign, Camera, CircleAlert, CircleCheck, CircleX, HardHat, ListChecks, Ruler } from "lucide-react";
import type { Assessment, EvaluatedItem, ServiceCoverage } from "../api";
import { brl, num } from "../format";
import type { GoTo } from "./FindingEvidence";
import type { LightboxItem } from "./ui/Lightbox";
import { StepTitle } from "./ui/StepTitle";
import { highlight, SentenceList } from "./ui/RichText";

type Tone = "ok" | "warn" | "bad" | "neutral";
const TONE: Record<Tone, { chip: string; text: string; bar: string }> = {
  ok: { chip: "bg-[#e3f2ea] text-ok", text: "text-ok", bar: "bg-ok" },
  warn: { chip: "bg-[#f8eedb] text-warn", text: "text-warn", bar: "bg-warn" },
  bad: { chip: "bg-[#f8e4e2] text-bad", text: "text-bad", bar: "bg-bad" },
  neutral: { chip: "bg-paper text-muted", text: "text-muted", bar: "bg-muted" },
};

interface QuantityCheck { item: number; what_was_counted: string; per_photo: string; count_seen: number; estimated_quantity: number; reasoning: string }
interface PhotoSummary { problem_assessment?: string; quantity_checks?: QuantityCheck[] }

/** Há algo para mostrar? (cobertura, orçamento lido ou fotos analisadas) */
export const hasInsights = (p: Assessment) =>
  (p.service_coverage?.length ?? 0) > 0 || p.items.length > 0 || p.photos.length > 0 || !!(p.photo_summary as PhotoSummary | null)?.problem_assessment;

const pct = (a: number, b: number) => `${a >= b ? "+" : ""}${Math.round(100 * (a / b - 1))}%`;
const itemRef = (n: number) => (f: { reference: string }) => f.reference === `item ${n}` || f.reference.startsWith(`item ${n}:`);

/**
 * O racional do engenheiro que aprova o orçamento, em quatro conferências: o orçamento cobre o pedido, a quantidade
 * bate com as fotos, o preço bate com a referência e o que as fotos mostram do problema. Cada cartão leva ao detalhe.
 */
export function EngineerInsights({ p, n, goTo, openPhoto }: { p: Assessment; n: number; goTo: GoTo; openPhoto: (items: LightboxItem[], index: number) => void }) {
  const coverage = p.service_coverage ?? [];
  const summary = (p.photo_summary ?? {}) as PhotoSummary;
  const byN = new Map(p.items.map((i) => [i.n, i]));
  const checks = (summary.quantity_checks ?? []).filter((c) => byN.has(c.item));
  const hasPrice = p.items.length > 0;
  const problem = summary.problem_assessment?.trim() ?? "";

  return (
    <section data-tour="insights" className="rounded-xl border border-line bg-sheet p-5">
      <StepTitle n={n} sub="As conferências que um engenheiro faz para aprovar o orçamento. Clique em cada cartão para ver o detalhe.">
        <span className="inline-flex items-center gap-2"><HardHat size={18} className="text-blueprint" aria-hidden /> O que o engenheiro conferiu</span>
      </StepTitle>
      {/* esquerda: o orçamento (cobre o pedido? preço?); direita: as fotos (quantidade, leitura do problema) */}
      <div className="mt-4 grid items-start gap-4 lg:grid-cols-2">
        <div className="min-w-0 space-y-4">
          {coverage.length > 0 && <CoverageCard rows={coverage} goTo={goTo} />}
          {hasPrice && <PriceCard p={p} goTo={goTo} />}
        </div>
        <div className="min-w-0 space-y-4">
          {checks.length > 0 && <QuantityCard checks={checks} byN={byN} p={p} goTo={goTo} />}
          {(problem || p.photos.length > 0) && <ProblemCard p={p} problem={problem} goTo={goTo} openPhoto={openPhoto} />}
        </div>
      </div>
    </section>
  );
}

function Card({ icon: Icon, title, headline, tone, children, link, onLink }: {
  icon: typeof HardHat; title: string; headline: string; tone: Tone; children: React.ReactNode; link: string; onLink: () => void;
}) {
  return (
    <article className="flex min-w-0 flex-col rounded-xl border border-line bg-sheet">
      <header className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5 border-b border-line/70 px-4 py-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold"><Icon size={16} className="text-muted" aria-hidden />{title}</h3>
        <span className={`whitespace-nowrap rounded-full px-2.5 py-0.5 text-[12px] font-semibold ${TONE[tone].chip}`}>{headline}</span>
      </header>
      <div className="flex-1 px-4 py-3 text-sm">{children}</div>
      <button onClick={onLink} className="flex items-center justify-end gap-1 border-t border-line/70 px-4 py-2 text-[13px] font-medium text-blueprint hover:bg-paper/60">
        {link} <ArrowRight size={14} />
      </button>
    </article>
  );
}

const STATUS = {
  yes: { icon: CircleCheck, tone: "ok" as Tone, label: "coberto" },
  partial: { icon: CircleAlert, tone: "warn" as Tone, label: "só em parte" },
  no: { icon: CircleX, tone: "bad" as Tone, label: "sem item" },
  undetermined: { icon: CircleAlert, tone: "neutral" as Tone, label: "não conferido" },
};

/** 1. Cada serviço pedido tem item que o executa? */
function CoverageCard({ rows, goTo }: { rows: ServiceCoverage[]; goTo: GoTo }) {
  const covered = rows.filter((r) => r.covered === "yes").length;
  const tone: Tone = rows.some((r) => r.covered === "no") ? "bad" : rows.some((r) => r.covered !== "yes") ? "warn" : "ok";
  const gapItems = rows.filter((r) => r.covered === "partial").flatMap((r) => r.items);
  return (
    <Card icon={ListChecks} title="O orçamento cobre o pedido?" tone={tone} headline={`${covered} de ${rows.length} serviço${rows.length === 1 ? "" : "s"} coberto${covered === 1 ? "" : "s"}`}
      link="Ver no orçamento" onLink={() => goTo("quote", { items: gapItems })}>
      <ul className="space-y-2">
        {rows.map((r) => {
          const s = STATUS[r.covered] ?? STATUS.undetermined;
          const Icon = s.icon;
          return (
            <li key={r.n} className="flex gap-2">
              <Icon size={16} className={`mt-0.5 shrink-0 ${TONE[s.tone].text}`} aria-label={s.label} />
              <div className="min-w-0">
                <span className="font-medium">{r.service}</span>
                <span className={`ml-1.5 text-[12px] font-semibold ${TONE[s.tone].text}`}>{s.label}{r.items.length ? ` · ${r.items.length > 1 ? "itens" : "item"} ${r.items.join(", ")}` : ""}</span>
                {r.note && <p className="text-[13px] text-muted">{highlight(r.note)}</p>}
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

/** 2. Quantidade cobrada × o que as fotos mostram, em barras comparáveis. */
function QuantityCard({ checks, byN, p, goTo }: { checks: QuantityCheck[]; byN: Map<number, EvaluatedItem>; p: Assessment; goTo: GoTo }) {
  const flagged = (n: number) => p.findings.some((f) => f.kind === "quantity_above_photos" && itemRef(n)(f));
  const above = checks.filter((c) => flagged(c.item));
  const unknown = checks.filter((c) => c.estimated_quantity <= 0).length;
  const tone: Tone = above.length ? "bad" : unknown ? "neutral" : "ok";
  const headline = above.length ? `${above.length} ite${above.length === 1 ? "m" : "ns"} acima do visível` : unknown === checks.length ? "não deu para estimar" : "bate com as fotos";
  return (
    <Card icon={Ruler} title="Quantidade cobrada × fotos" tone={tone} headline={headline} link="Ver as fotos" onLink={() => goTo("photos")}>
      <ul className="space-y-3">
        {checks.map((c) => {
          const item = byN.get(c.item)!;
          const est = c.estimated_quantity;
          const max = Math.max(item.quantity, est > 0 ? est : 0) || 1;
          const bad = flagged(c.item);
          return (
            <li key={c.item}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="min-w-0 truncate font-medium" title={item.description}>{item.n}. {item.description}</span>
                {bad && est > 0 && <span className="whitespace-nowrap text-[12px] font-semibold text-bad">{pct(item.quantity, est)}</span>}
              </div>
              <Bar label="Cobrado" value={`${num(item.quantity)} ${item.unit}`} width={item.quantity / max} tone={bad ? "bad" : "neutral"} />
              <Bar label="Fotos" value={est > 0 ? `≈ ${num(est)} ${item.unit}` : "não dá para estimar"} width={est > 0 ? est / max : 0} tone="ok" />
              <details className="mt-0.5 text-[12px] text-muted">
                <summary className="cursor-pointer select-none">
                  <span className="first-letter:uppercase">{c.what_was_counted}</span>: <b className="text-ink">{num(c.count_seen)}</b> · como contou
                </summary>
                {c.reasoning && <p className="mt-1">{c.reasoning}</p>}
                {c.per_photo && <p className="mt-0.5">Por foto: {c.per_photo}</p>}
              </details>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function Bar({ label, value, width, tone }: { label: string; value: string; width: number; tone: Tone }) {
  return (
    <div className="mt-1 grid grid-cols-[52px_1fr_auto] items-center gap-2 text-[12px]">
      <span className="text-muted">{label}</span>
      <span className="h-2 rounded-full bg-paper"><span className={`block h-2 rounded-full ${TONE[tone].bar}`} style={{ width: `${Math.max(2, Math.min(100, 100 * width))}%` }} /></span>
      <span className="whitespace-nowrap tabular-nums">{value}</span>
    </div>
  );
}

/** 3. Preço × tabela de referência e × preço de mercado anexado. */
function PriceCard({ p, goTo }: { p: Assessment; goTo: GoTo }) {
  const priced = p.items.filter((i) => i.reference_price);
  const market = (p.documents ?? []).flatMap((d) => d.prices.filter((x) => x.quote_item > 0 && x.value > 0 && p.items.some((i) => i.n === x.quote_item)).map((x) => ({ ...x, file: d.file })));
  const isAbove = (i: EvaluatedItem) => i.findings.some((f) => f.kind === "price_above_reference" || f.kind === "price_above_market");
  const above = p.items.filter(isAbove);
  const compared = priced.length + market.length;
  const tone: Tone = above.length ? "bad" : compared ? "ok" : "neutral";
  const headline = above.length ? `${above.length} ite${above.length === 1 ? "m" : "ns"} acima` : compared ? "dentro da referência" : "sem referência";
  return (
    <Card icon={BadgeDollarSign} title="Preço × referência" tone={tone} headline={headline} link="Ver no orçamento" onLink={() => goTo("quote", { items: above.map((i) => i.n) })}>
      {compared === 0 && (
        <p className="text-muted">Nenhum item tem equivalente na tabela de referência e não há preço de mercado anexado: o preço não pôde ser comparado.</p>
      )}
      <ul className="space-y-1.5">
        {priced.map((i) => {
          const bad = i.findings.some((f) => f.kind === "price_above_reference");
          return (
            <li key={i.n} className="flex flex-wrap items-baseline justify-between gap-x-2">
              <span className="min-w-0 truncate" title={i.description}>{i.n}. {i.description}</span>
              <span className={`tabular-nums ${bad ? "font-semibold text-bad" : "text-muted"}`}>{brl(i.unit_value)} × tabela {brl(i.reference_price!)} ({pct(i.unit_value, i.reference_price!)})</span>
            </li>
          );
        })}
        {market.map((x, k) => {
          const item = p.items.find((i) => i.n === x.quote_item)!;
          const bad = item.findings.some((f) => f.kind === "price_above_market");
          return (
            <li key={`m${k}`}>
              <div className="flex flex-wrap items-baseline justify-between gap-x-2">
                <span className="min-w-0 truncate" title={item.description}>{item.n}. {item.description}</span>
                <span className={`tabular-nums ${bad ? "font-semibold text-bad" : "text-muted"}`}>{brl(item.unit_value)} × anúncio {brl(x.value)} ({pct(item.unit_value, x.value)})</span>
              </div>
              <p className="break-words text-[12px] text-muted">{x.description} · {x.file}{x.same_product && x.same_product !== "yes" ? " · produto não confirmado" : ""}</p>
            </li>
          );
        })}
      </ul>
      {compared > 0 && p.items.length > priced.length + new Set(market.map((m) => m.quote_item)).size && (
        <p className="mt-2 text-[12px] text-muted">{p.items.length - priced.length} ite{p.items.length - priced.length === 1 ? "m" : "ns"} sem equivalente na tabela.</p>
      )}
    </Card>
  );
}

/** 4. O que as fotos mostram do problema (gravidade, risco) e se justificam o serviço, com as fotos à mão. */
function ProblemCard({ p, problem, goTo, openPhoto }: { p: Assessment; problem: string; goTo: GoTo; openPhoto: (items: LightboxItem[], index: number) => void }) {
  const url = (file: string) => `/api/tickets/${p.ticket_id}/attachments/${encodeURIComponent(file)}`;
  const gallery = p.photos.map((ph) => ({ url: url(ph.file), caption: ph.what_it_shows }));
  const shown = p.photos.slice(0, 4);
  const mismatch = p.photos.filter((ph) => ph.readable && ph.matches_scope === "no").length;
  const tone: Tone = mismatch ? "bad" : problem ? "ok" : "neutral";
  const headline = `${p.photos.length} foto${p.photos.length === 1 ? "" : "s"}${mismatch ? ` · ${mismatch} fora do escopo` : ""}`;
  return (
    <Card icon={Camera} title="O que as fotos mostram do problema" tone={tone} headline={headline} link="Ver as fotos" onLink={() => goTo("photos")}>
      {problem ? <SentenceList text={problem} topics={false} className="text-[14px]" /> : <p className="text-muted">O modelo não registrou uma leitura do problema neste parecer.</p>}
      {shown.length > 0 && (
        <div className="mt-3 flex gap-2">
          {shown.map((ph, k) => (
            <button key={ph.file} onClick={() => openPhoto(gallery, k)} aria-label={`Ampliar: ${ph.what_it_shows}`}
              className="size-16 overflow-hidden rounded-md border border-line hover:border-blueprint">
              <img src={url(ph.file)} alt="" loading="lazy" className="size-full object-cover" />
            </button>
          ))}
          {p.photos.length > shown.length && <span className="self-center text-[12px] text-muted">+{p.photos.length - shown.length}</span>}
        </div>
      )}
    </Card>
  );
}
