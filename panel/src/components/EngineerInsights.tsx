import { ArrowRight, BadgeDollarSign, Camera, ChevronDown, CircleAlert, CircleCheck, CircleMinus, CircleX, HardHat, ListChecks, Ruler } from "lucide-react";
import { useState } from "react";
import type { Assessment, EvaluatedItem, ServiceCoverage } from "../api";
import { brl, num } from "../format";
import type { GoTo } from "./FindingEvidence";
import type { LightboxItem } from "./ui/Lightbox";
import { StepTitle } from "./ui/StepTitle";
import { highlight, LpuRef, SentenceList } from "./ui/RichText";

type Tone = "ok" | "warn" | "bad" | "neutral";
const TONE: Record<Tone, { chip: string; text: string; bar: string; edge: string; soft: string; icon: typeof CircleCheck }> = {
  ok: { chip: "bg-[#e3f2ea] text-ok", text: "text-ok", bar: "bg-ok", edge: "border-l-ok", soft: "bg-[#e3f2ea]", icon: CircleCheck },
  warn: { chip: "bg-[#f8eedb] text-warn", text: "text-warn", bar: "bg-warn", edge: "border-l-warn", soft: "bg-[#f8eedb]", icon: CircleAlert },
  bad: { chip: "bg-[#f8e4e2] text-bad", text: "text-bad", bar: "bg-bad", edge: "border-l-bad", soft: "bg-[#f8e4e2]", icon: CircleX },
  neutral: { chip: "bg-paper text-muted", text: "text-muted", bar: "bg-muted", edge: "border-l-line", soft: "bg-paper", icon: CircleMinus },
};

interface QuantityCheck { item: number; what_was_counted: string; per_photo: string; count_seen: number; estimated_quantity: number; reasoning: string }
interface PhotoSummary { problem_assessment?: string; quantity_checks?: QuantityCheck[] }
interface Status { tone: Tone; headline: string }

/** Há algo para mostrar? (cobertura, orçamento lido ou fotos analisadas) */
export const hasInsights = (p: Assessment) =>
  (p.service_coverage?.length ?? 0) > 0 || p.items.length > 0 || p.photos.length > 0 || !!(p.photo_summary as PhotoSummary | null)?.problem_assessment;

const pct = (a: number, b: number) => `${a >= b ? "+" : ""}${Math.round(100 * (a / b - 1))}%`;
const itemRef = (n: number) => (f: { reference: string }) => f.reference === `item ${n}` || f.reference.startsWith(`item ${n}:`);
const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);
const itens = (n: number) => `${n} ${plural(n, "item", "itens")}`;

// ---- resultado de cada conferência: o mesmo cálculo serve ao placar e ao cartão ----

const STATUS = {
  no: { tone: "bad" as Tone, label: "sem item", order: 0 },
  partial: { tone: "warn" as Tone, label: "só em parte", order: 1 },
  undetermined: { tone: "neutral" as Tone, label: "não conferido", order: 2 },
  yes: { tone: "ok" as Tone, label: "coberto", order: 3 },
};
const statusOf = (r: ServiceCoverage) => STATUS[r.covered] ?? STATUS.undetermined;

function coverageStatus(rows: ServiceCoverage[]): Status {
  const covered = rows.filter((r) => r.covered === "yes").length;
  const tone: Tone = rows.some((r) => r.covered === "no") ? "bad" : rows.some((r) => r.covered !== "yes") ? "warn" : "ok";
  return { tone, headline: `${covered} de ${rows.length} ${plural(rows.length, "serviço", "serviços")} ${plural(covered, "coberto", "cobertos")}` };
}

const quantityFlagged = (p: Assessment, n: number) => p.findings.some((f) => f.kind === "quantity_above_photos" && itemRef(n)(f));

function quantityStatus(checks: QuantityCheck[], p: Assessment): Status {
  const above = checks.filter((c) => quantityFlagged(p, c.item)).length;
  const unknown = checks.filter((c) => c.estimated_quantity <= 0).length;
  if (above) return { tone: "bad", headline: `${itens(above)} acima do visível` };
  if (unknown === checks.length) return { tone: "neutral", headline: "não deu para estimar" };
  return { tone: unknown ? "neutral" : "ok", headline: "bate com as fotos" };
}

/** Como o preço de cada item foi comparado: LPU, item similar da LPU, anúncio anexado ou nada. */
function priceView(p: Assessment) {
  const has = (kind: string, n: number) => p.findings.some((f) => f.kind === kind && itemRef(n)(f) && !(kind === "similar_lpu_item" && f.amount_at_issue <= 0));
  const lpu = p.items.filter((i) => i.reference_price);
  const similar = p.items.filter((i) => !i.reference_price && i.similar_lpu);
  const market = (p.documents ?? []).flatMap((d) =>
    d.prices.filter((x) => x.quote_item > 0 && x.value > 0 && p.items.some((i) => i.n === x.quote_item)).map((x) => ({ ...x, file: d.file })));
  const marketItems = new Set(market.map((m) => m.quote_item));
  const unref = p.items.filter((i) => !i.reference_price && !i.similar_lpu && !marketItems.has(i.n));
  const isAbove = (i: EvaluatedItem) => ["price_above_reference", "price_above_market", "similar_lpu_item"].some((k) => has(k, i.n));
  return { has, lpu, similar, market, unref, above: p.items.filter(isAbove) };
}

function priceStatus(v: ReturnType<typeof priceView>): Status {
  const compared = v.lpu.length + v.similar.length + v.market.length;
  if (v.above.length) return { tone: "bad", headline: `${itens(v.above.length)} acima` };
  if (compared === 0) return { tone: "neutral", headline: "sem referência" };
  const check = v.similar.length + v.unref.length;
  if (check) return { tone: "warn", headline: `${itens(check)} a conferir` };
  return { tone: "ok", headline: "dentro da referência" };
}

function photoStatus(p: Assessment, problem: string): Status {
  const mismatch = p.photos.filter((ph) => ph.readable && ph.matches_scope === "no").length;
  // apontamentos das fotos (fora a quantidade, que tem cartão próprio): a leitura não basta para dar "ok"
  const flagged = p.findings.filter((f) => f.validation === "photos" && f.kind !== "quantity_above_photos" && !f.absorbed_by).length;
  const tone: Tone = mismatch ? "bad" : flagged ? "warn" : problem ? "ok" : "neutral";
  const extra = mismatch ? ` · ${mismatch} fora do escopo` : flagged ? ` · ${flagged} ${plural(flagged, "apontamento", "apontamentos")}` : "";
  return { tone, headline: `${p.photos.length} ${plural(p.photos.length, "foto", "fotos")}${extra}` };
}

/** rola até o cartão e pisca o contorno */
function focusCard(id: string) {
  const el = document.getElementById(id);
  el?.scrollIntoView({ block: "start", behavior: "smooth" });
  el?.classList.remove("piscar");
  void el?.offsetWidth;
  el?.classList.add("piscar");
}

/**
 * O racional do engenheiro que aprova o orçamento, em quatro conferências: o orçamento cobre o pedido, a quantidade
 * bate com as fotos, o preço bate com a referência e o que as fotos mostram do problema. Um placar no topo dá o
 * resultado de cada uma de relance; cada cartão traz o detalhe e leva à aba correspondente.
 */
export function EngineerInsights({ p, n, goTo, openPhoto }: { p: Assessment; n: number; goTo: GoTo; openPhoto: (items: LightboxItem[], index: number) => void }) {
  const coverage = p.service_coverage ?? [];
  const summary = (p.photo_summary ?? {}) as PhotoSummary;
  const byN = new Map(p.items.map((i) => [i.n, i]));
  const checks = (summary.quantity_checks ?? []).filter((c) => byN.has(c.item));
  const problem = summary.problem_assessment?.trim() ?? "";
  const price = priceView(p);

  const tiles: { id: string; icon: typeof HardHat; label: string; s: Status }[] = [];
  if (coverage.length > 0) tiles.push({ id: "insight-coverage", icon: ListChecks, label: "Cobertura", s: coverageStatus(coverage) });
  if (checks.length > 0) tiles.push({ id: "insight-quantity", icon: Ruler, label: "Quantidade", s: quantityStatus(checks, p) });
  if (p.items.length > 0) tiles.push({ id: "insight-price", icon: BadgeDollarSign, label: "Preço", s: priceStatus(price) });
  if (problem || p.photos.length > 0) tiles.push({ id: "insight-photos", icon: Camera, label: "Fotos", s: photoStatus(p, problem) });
  const status = Object.fromEntries(tiles.map((t) => [t.id, t.s]));

  return (
    <section data-tour="insights" className="rounded-xl border border-line bg-sheet p-5">
      <StepTitle n={n} sub="As conferências que um engenheiro faz para aprovar o orçamento. Clique numa conferência para ir ao detalhe.">
        <span className="inline-flex items-center gap-2"><HardHat size={18} className="text-blueprint" aria-hidden /> O que o engenheiro conferiu</span>
      </StepTitle>
      {tiles.length > 1 && (
        <div className={`mt-4 grid gap-2.5 sm:grid-cols-2 ${tiles.length >= 4 ? "lg:grid-cols-4" : tiles.length === 3 ? "lg:grid-cols-3" : ""}`}>
          {tiles.map(({ id, icon: Icon, label, s }) => {
            const T = TONE[s.tone];
            const Mark = T.icon;
            return (
              <button key={id} onClick={() => focusCard(id)}
                className={`flex min-w-0 items-center gap-3 rounded-lg border border-line border-l-4 ${T.edge} bg-sheet px-3 py-2.5 text-left transition-colors hover:bg-paper/70`}>
                <span className={`flex size-9 shrink-0 items-center justify-center rounded-full ${T.soft} ${T.text}`}><Icon size={17} aria-hidden /></span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[12px] font-medium uppercase tracking-wide text-muted">{label}</span>
                  <span className={`flex items-center gap-1 text-[14px] font-semibold leading-snug ${T.text}`}>
                    <Mark size={14} strokeWidth={2.5} className="shrink-0" aria-hidden /><span className="min-w-0">{s.headline}</span>
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      )}
      {/* esquerda: o orçamento (cobre o pedido? preço?); direita: as fotos (quantidade, leitura do problema) */}
      <div className="mt-4 grid items-start gap-4 lg:grid-cols-2">
        <div className="min-w-0 space-y-4">
          {status["insight-coverage"] && <CoverageCard rows={coverage} s={status["insight-coverage"]} goTo={goTo} />}
          {status["insight-price"] && <PriceCard p={p} v={price} s={status["insight-price"]} goTo={goTo} />}
        </div>
        <div className="min-w-0 space-y-4">
          {status["insight-quantity"] && <QuantityCard checks={checks} byN={byN} p={p} s={status["insight-quantity"]} goTo={goTo} />}
          {status["insight-photos"] && <ProblemCard p={p} problem={problem} s={status["insight-photos"]} goTo={goTo} openPhoto={openPhoto} />}
        </div>
      </div>
    </section>
  );
}

function Card({ id, icon: Icon, title, s, children, link, onLink }: {
  id: string; icon: typeof HardHat; title: string; s: Status; children: React.ReactNode; link: string; onLink: () => void;
}) {
  const T = TONE[s.tone];
  const Mark = T.icon;
  return (
    <article id={id} className={`flex min-w-0 scroll-mt-24 flex-col rounded-xl border border-line border-l-4 ${T.edge} bg-sheet`}>
      <header className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5 border-b border-line/70 px-4 py-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold"><Icon size={16} className={T.text} aria-hidden />{title}</h3>
        <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[12px] font-semibold ${T.chip}`}>
          <Mark size={13} strokeWidth={2.5} aria-hidden />{s.headline}
        </span>
      </header>
      <div className="flex-1 px-4 py-3 text-sm">{children}</div>
      <button onClick={onLink} className="flex items-center justify-end gap-1 border-t border-line/70 px-4 py-2 text-[13px] font-medium text-blueprint hover:bg-paper/60">
        {link} <ArrowRight size={14} />
      </button>
    </article>
  );
}

/** Texto longo em até duas linhas, com "ver mais". */
function Note({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 140;
  return (
    <p className="text-[13px] text-muted">
      <span className={long && !open ? "line-clamp-2" : ""}>{highlight(text)}</span>
      {long && (
        <button onClick={() => setOpen((o) => !o)} className="text-[12px] font-medium text-blueprint hover:underline">
          {open ? "ver menos" : "ver mais"}
        </button>
      )}
    </p>
  );
}

/** 1. Cada serviço pedido tem item que o executa? Os problemas primeiro. */
function CoverageCard({ rows, s, goTo }: { rows: ServiceCoverage[]; s: Status; goTo: GoTo }) {
  const [showCovered, setShowCovered] = useState(false);
  const sorted = [...rows].sort((a, b) => statusOf(a).order - statusOf(b).order || a.n - b.n);
  const problems = sorted.filter((r) => r.covered !== "yes");
  const covered = sorted.filter((r) => r.covered === "yes");
  const fold = problems.length > 0 && covered.length > 3 && !showCovered;
  const shown = fold ? problems : sorted;
  const gapItems = rows.filter((r) => r.covered === "partial").flatMap((r) => r.items);
  return (
    <Card id="insight-coverage" icon={ListChecks} title="O orçamento cobre o pedido?" s={s} link="Ver no orçamento" onLink={() => goTo("quote", { items: gapItems })}>
      <ul className="space-y-3">
        {shown.map((r) => {
          const st = statusOf(r);
          const T = TONE[st.tone];
          const Mark = T.icon;
          return (
            <li key={r.n} className="flex gap-2.5">
              <Mark size={17} className={`mt-0.5 shrink-0 ${T.text}`} aria-hidden />
              <div className="min-w-0 space-y-1">
                <p className="font-medium leading-snug">{r.service}</p>
                <p className="flex flex-wrap items-center gap-1.5 text-[12px]">
                  <span className={`rounded-full px-2 py-px font-semibold ${T.chip}`}>{st.label}</span>
                  {r.items.length > 0 && <span className="text-muted">{highlight(`${r.items.length > 1 ? "itens" : "item"} ${r.items.join(", ")}`)}</span>}
                </p>
                {r.note && <Note text={r.note} />}
              </div>
            </li>
          );
        })}
      </ul>
      {problems.length > 0 && covered.length > 3 && (
        <button onClick={() => setShowCovered((v) => !v)} className="mt-3 inline-flex items-center gap-1 text-[13px] font-medium text-blueprint hover:underline">
          <ChevronDown size={14} className={showCovered ? "rotate-180" : ""} />
          {showCovered ? "Esconder os serviços cobertos" : `+${covered.length} serviços cobertos`}
        </button>
      )}
    </Card>
  );
}

/** 2. Quantidade cobrada × o que as fotos mostram, em barras comparáveis. */
function QuantityCard({ checks, byN, p, s, goTo }: { checks: QuantityCheck[]; byN: Map<number, EvaluatedItem>; p: Assessment; s: Status; goTo: GoTo }) {
  return (
    <Card id="insight-quantity" icon={Ruler} title="Quantidade cobrada × fotos" s={s} link="Ver as fotos" onLink={() => goTo("photos")}>
      <ul className="space-y-3">
        {checks.map((c) => {
          const item = byN.get(c.item)!;
          const est = c.estimated_quantity;
          const max = Math.max(item.quantity, est > 0 ? est : 0) || 1;
          const bad = quantityFlagged(p, c.item);
          return (
            <li key={c.item}>
              <div className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate font-medium" title={item.description}>{item.n}. {item.description}</span>
                {bad && est > 0 && <span className={`whitespace-nowrap rounded-full px-2 py-px text-[12px] font-semibold ${TONE.bad.chip}`}>{pct(item.quantity, est)}</span>}
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

/** Uma linha de comparação de preço: o item à esquerda, o confronto à direita. */
function PriceRow({ item, bad, children, sub }: { item: EvaluatedItem; bad: boolean; children: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <li>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <span className="min-w-0 truncate" title={item.description}>{item.n}. {item.description}</span>
        <span className={`ml-auto whitespace-nowrap tabular-nums ${bad ? "font-semibold text-bad" : "text-muted"}`}>{children}</span>
      </div>
      {sub && <p className="break-words text-[12px] text-muted">{sub}</p>}
    </li>
  );
}

/** 3. Preço × LPU, × item similar da LPU (itens Não LPU) e × preço de mercado anexado. */
function PriceCard({ p, v, s, goTo }: { p: Assessment; v: ReturnType<typeof priceView>; s: Status; goTo: GoTo }) {
  const compared = v.lpu.length + v.similar.length + v.market.length;
  const toQuote = [...new Set([...v.above, ...v.similar, ...v.unref].map((i) => i.n))];
  // uma linha por comparação; as que estão acima da referência sobem para o topo
  const rows: { key: string; item: EvaluatedItem; bad: boolean; text: React.ReactNode; sub?: React.ReactNode }[] = [
    ...v.lpu.map((i) => ({
      key: `l${i.n}`, item: i, bad: v.has("price_above_reference", i.n),
      text: `${brl(i.unit_value)} × LPU ${brl(i.reference_price!)} (${pct(i.unit_value, i.reference_price!)})`,
    })),
    ...v.similar.map((i) => {
      const sim = i.similar_lpu!;
      const sameUnit = sim.unit.trim().toLowerCase() === i.unit.trim().toLowerCase();
      return {
        key: `s${i.n}`, item: i, bad: v.has("similar_lpu_item", i.n),
        text: `${brl(i.unit_value)} × similar ${brl(sim.reference_price)}${sameUnit ? ` (${pct(i.unit_value, sim.reference_price)})` : ""}`,
        sub: <>Não LPU · a LPU tem item similar: <LpuRef code={sim.code} fallback={sim} />{!sameUnit && ` (por ${sim.unit}, não dá para comparar direto)`}</>,
      };
    }),
    ...v.market.map((x, k) => {
      const item = p.items.find((i) => i.n === x.quote_item)!;
      return {
        key: `m${k}`, item, bad: v.has("price_above_market", item.n),
        text: `${brl(item.unit_value)} × anúncio ${brl(x.value)} (${pct(item.unit_value, x.value)})`,
        sub: <>{x.description} · {x.file}{x.same_product && x.same_product !== "yes" ? " · produto não confirmado" : ""}</>,
      };
    }),
  ];
  return (
    <Card id="insight-price" icon={BadgeDollarSign} title="Preço × referência" s={s} link="Ver no orçamento" onLink={() => goTo("quote", { items: toQuote })}>
      {compared === 0 && (
        <p className="text-muted">Nenhum item tem equivalente na LPU e não há preço de mercado anexado: o preço não pôde ser comparado.</p>
      )}
      <ul className="space-y-1.5">
        {rows.sort((a, b) => Number(b.bad) - Number(a.bad) || a.item.n - b.item.n).map((r) => (
          <PriceRow key={r.key} item={r.item} bad={r.bad} sub={r.sub}>{r.text}</PriceRow>
        ))}
      </ul>
      {compared > 0 && v.unref.length > 0 && (
        <div className={`mt-3 rounded-md px-3 py-2 text-[12px] ${TONE.warn.soft}`}>
          <p className="font-semibold text-warn">Sem referência de preço</p>
          <ul className="mt-0.5 text-ink">
            {v.unref.map((i) => <li key={i.n}>{highlight(`item ${i.n}`)} · {i.description} · {brl(i.unit_value)}</li>)}
          </ul>
        </div>
      )}
    </Card>
  );
}

/** 4. O que as fotos mostram do problema (gravidade, risco) e se justificam o serviço, com as fotos à mão. */
function ProblemCard({ p, problem, s, goTo, openPhoto }: { p: Assessment; problem: string; s: Status; goTo: GoTo; openPhoto: (items: LightboxItem[], index: number) => void }) {
  const url = (file: string) => `/api/tickets/${p.ticket_id}/attachments/${encodeURIComponent(file)}`;
  const gallery = p.photos.map((ph) => ({ url: url(ph.file), caption: ph.what_it_shows }));
  const shown = p.photos.slice(0, 5);
  return (
    <Card id="insight-photos" icon={Camera} title="O que as fotos mostram do problema" s={s} link="Ver as fotos" onLink={() => goTo("photos")}>
      {shown.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {shown.map((ph, k) => (
            <button key={ph.file} onClick={() => openPhoto(gallery, k)} aria-label={`Ampliar: ${ph.what_it_shows}`} title={ph.what_it_shows}
              className={`size-16 overflow-hidden rounded-md border-2 hover:border-blueprint ${ph.readable && ph.matches_scope === "no" ? "border-bad" : "border-line"}`}>
              <img src={url(ph.file)} alt="" loading="lazy" className="size-full object-cover" />
            </button>
          ))}
          {p.photos.length > shown.length && (
            <button onClick={() => openPhoto(gallery, shown.length)} className="flex size-16 items-center justify-center rounded-md border border-dashed border-line text-[13px] text-muted hover:border-blueprint">
              +{p.photos.length - shown.length}
            </button>
          )}
        </div>
      )}
      {problem ? <SentenceList text={problem} topics={false} className="text-[14px]" /> : <p className="text-muted">O modelo não registrou uma leitura do problema neste parecer.</p>}
    </Card>
  );
}
