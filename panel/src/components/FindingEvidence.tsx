import { ArrowRight, ExternalLink, FileSpreadsheet, ImageOff, Lock } from "lucide-react";
import { ReuseModal } from "./ReuseModal";
import { useState } from "react";
import type { Assessment, EvaluatedItem, EvaluatedPhoto, Finding, TicketDetail } from "../api";
import { brl, num, MOMENT_LABEL } from "../format";
import { locate, type Located } from "../evidence";
import type { LightboxItem } from "./ui/Lightbox";

export type GoTo = (tab: "quote" | "photos" | "input", highlight?: { items?: number[]; files?: string[] }) => void;

interface Props {
  f: Finding;
  p: Assessment;
  ticket: TicketDetail | null;
  openPhoto: (items: LightboxItem[], index: number) => void;
  goTo: GoTo;
  /** abre outro chamado na Análise (usado no modal de foto reaproveitada) */
  openTicket?: (id: string) => void;
}

const photoUrl = (ticket: string, file: string) => `/api/tickets/${ticket}/attachments/${encodeURIComponent(file)}`;

/** Resumo curto de onde o apontamento está, para mostrar no card antes de abrir. */
export function whereLabel(loc: Located, p: Assessment): string {
  if (loc.scope) return "Texto do escopo";
  if (loc.spreadsheet) return "Cabeçalho da planilha";
  if (loc.items.length) {
    const ns = [loc.items[0].n, ...(loc.duplicateOf ? [loc.duplicateOf.n] : [])];
    return ns.length > 1 ? `Linhas ${ns.join(" e ")} do orçamento` : `Linha ${ns[0]} do orçamento`;
  }
  if (loc.absence) return `Conferir as ${p.photos.length} fotos`;
  if (loc.photos.length) return loc.photos.length === 1 ? loc.photos[0].file : `${loc.photos.length} fotos`;
  return "";
}

/** Gaveta aberta ao clicar num apontamento: mostra a linha do orçamento, a foto ou o trecho do escopo com o problema. */
export function FindingEvidence({ f, p, ticket, openPhoto, goTo, openTicket }: Props) {
  const loc = locate(f, p);
  return (
    <div className="surgir mt-3 space-y-3 rounded-lg border border-line bg-paper/50 p-3 text-sm">
      {loc.scope && <ScopeEvidence p={p} ticket={ticket} />}
      {loc.spreadsheet && <SpreadsheetEvidence ticket={ticket} goTo={goTo} />}
      {loc.items.length > 0 && <QuoteEvidence f={f} loc={loc} goTo={goTo} />}
      {loc.reusedFrom && loc.photos[0] && <ReusedEvidence p={p} photo={loc.photos[0]} other={loc.reusedFrom} openPhoto={openPhoto} openTicket={openTicket} />}
      {!loc.reusedFrom && loc.photos.length > 0 && <PhotoEvidence f={f} p={p} photos={loc.photos} openPhoto={openPhoto} goTo={goTo} />}
      {loc.absence && <AbsenceEvidence p={p} kind={loc.absence} openPhoto={openPhoto} goTo={goTo} />}
      {!loc.scope && !loc.spreadsheet && !loc.items.length && !loc.photos.length && !loc.absence && (
        <p className="text-muted">Este apontamento não cita uma linha do orçamento nem uma foto específica. A evidência é o texto acima.</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------- orçamento
function QuoteEvidence({ f, loc, goTo }: { f: Finding; loc: Located; goTo: GoTo }) {
  const rows: { item: EvaluatedItem; role?: string }[] = [{ item: loc.items[0], role: loc.duplicateOf ? "cobrado de novo" : undefined }];
  if (loc.duplicateOf) rows.unshift({ item: loc.duplicateOf, role: "original" });
  const hot = (col: "qty" | "unit" | "row") =>
    (f.kind === "quantity_above_expected" && col === "qty") || (f.kind === "price_above_reference" && col === "unit") ? "bg-[#f8e4e2] font-semibold text-bad" : "";
  const whole = ["out_of_scope_item", "unjustified_replacement", "duplicate_item"].includes(f.kind);
  const it = loc.items[0];
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="font-medium">Onde está no orçamento</span>
        <button onClick={() => goTo("quote", { items: rows.map((r) => r.item.n) })} className="flex items-center gap-1 text-[13px] font-medium text-blueprint hover:underline">
          Ver no orçamento completo <ArrowRight size={14} />
        </button>
      </div>
      <div className="overflow-x-auto rounded-md border border-line bg-sheet">
        <table className="w-full min-w-[620px] text-[13px]">
          <thead className="bg-paper text-left text-muted">
            <tr>
              <th className="px-2.5 py-1.5 font-medium">Linha</th><th className="px-2.5 py-1.5 font-medium">Descrição</th>
              <th className="px-2.5 py-1.5 text-right font-medium">Qtd</th><th className="px-2.5 py-1.5 text-right font-medium">Unitário</th>
              <th className="px-2.5 py-1.5 text-right font-medium">Total</th><th className="px-2.5 py-1.5 text-right font-medium">Em questão</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {rows.map(({ item, role }) => {
              const flagged = item === it;
              return (
                <tr key={item.n} className={`border-t border-line/70 align-top ${flagged && whole ? "bg-[#fbefed]" : ""}`}>
                  <td className="px-2.5 py-2 font-semibold">{item.n}{role && <div className="text-[11px] font-normal text-muted">{role}</div>}</td>
                  <td className="px-2.5 py-2">
                    <div className={flagged && whole ? "font-medium text-bad" : ""}>{item.description}</div>
                    {flagged && item.reason && <div className="text-[12px] text-muted">Leitura do modelo: {item.reason}</div>}
                  </td>
                  <td className={`whitespace-nowrap px-2.5 py-2 text-right ${flagged ? hot("qty") : ""}`}>
                    {num(item.quantity)} {item.unit}
                    {flagged && item.expected_quantity_max !== null && <div className="text-[11px] font-normal text-muted">esperado até {num(item.expected_quantity_max)}</div>}
                  </td>
                  <td className={`whitespace-nowrap px-2.5 py-2 text-right ${flagged ? hot("unit") : ""}`}>
                    {brl(item.unit_value)}
                    {flagged && item.reference_price !== null && (
                      <div className="text-[11px] font-normal text-muted">
                        referência {brl(item.reference_price)}{item.unit_value > item.reference_price ? ` (+${Math.round((100 * (item.unit_value - item.reference_price)) / item.reference_price)}%)` : ""}
                      </div>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-2.5 py-2 text-right">{brl(item.total_value)}</td>
                  <td className={`whitespace-nowrap px-2.5 py-2 text-right ${flagged && item.amount_at_issue ? "font-semibold text-bad" : "text-muted"}`}>
                    {flagged && item.amount_at_issue ? brl(item.amount_at_issue) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-1.5 text-[12px] text-muted">
        {whole ? "A linha inteira entra no valor em questão." : f.kind === "price_above_reference" ? "Só o que passa da referência (com a tolerância) entra no valor em questão." : "Só o excedente de quantidade entra no valor em questão."}
      </p>
    </div>
  );
}

function SpreadsheetEvidence({ ticket, goTo }: { ticket: TicketDetail | null; goTo: GoTo }) {
  const sheet = ticket?.attachments.find((a) => !a.is_image);
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span>A divergência está no cabeçalho da planilha (aba <b>Chamado</b>), comparado aos dados do chamado.</span>
      <span className="flex gap-3">
        {sheet && <a href={sheet.url} download className="flex items-center gap-1 text-[13px] font-medium text-blueprint hover:underline"><FileSpreadsheet size={14} /> Baixar planilha</a>}
        <button onClick={() => goTo("input")} className="flex items-center gap-1 text-[13px] font-medium text-blueprint hover:underline">Ver entrada do chamado <ArrowRight size={14} /></button>
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------- escopo
function ScopeEvidence({ p, ticket }: { p: Assessment; ticket: TicketDetail | null }) {
  const s = (p.scope ?? {}) as { requested_services?: string[]; acceptance_criteria?: string[]; environment?: string };
  return (
    <div className="space-y-2">
      <div>
        <div className="mb-1 font-medium">Escopo como foi escrito</div>
        <blockquote className="rounded-md border-l-4 border-warn bg-sheet px-3 py-2 text-[15px] leading-snug">“{ticket?.scope ?? "—"}”</blockquote>
        {ticket && <div className="mt-1 text-[12px] text-muted">Categoria {ticket.category_label} · sintoma {ticket.symptom_label}{ticket.environment ? ` · ambiente ${ticket.environment}` : ""}</div>}
      </div>
      {(s.requested_services?.length || s.acceptance_criteria?.length) ? (
        <div className="grid gap-2 md:grid-cols-2">
          {!!s.requested_services?.length && <List title="O que o modelo entendeu como pedido" items={s.requested_services} />}
          {!!s.acceptance_criteria?.length && <List title="Critérios para conferir" items={s.acceptance_criteria} />}
        </div>
      ) : null}
    </div>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-md bg-sheet p-2.5">
      <div className="mb-1 text-[12px] font-medium text-muted">{title}</div>
      <ul className="list-disc space-y-0.5 pl-4 text-[13px]">{items.map((x, k) => <li key={k}>{x}</li>)}</ul>
    </div>
  );
}

// ---------------------------------------------------------------------------- fotos
const MATCH_LABEL = { yes: "corresponde ao escopo", partial: "corresponde em parte", no: "não corresponde ao escopo", undetermined: "não dá para avaliar" } as const;

function PhotoEvidence({ f, p, photos, openPhoto, goTo }: { f: Finding; p: Assessment; photos: EvaluatedPhoto[]; openPhoto: Props["openPhoto"]; goTo: GoTo }) {
  const gallery = photos.map((ph) => ({ url: photoUrl(p.ticket_id, ph.file), caption: ph.what_it_shows }));
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="font-medium">Foto com o problema</span>
        <button onClick={() => goTo("photos", { files: photos.map((x) => x.file) })} className="flex items-center gap-1 text-[13px] font-medium text-blueprint hover:underline">
          Ver entre todas as fotos <ArrowRight size={14} />
        </button>
      </div>
      <div className="space-y-2">
        {photos.map((ph, k) => (
          <div key={ph.file} className="flex gap-3 rounded-md bg-sheet p-2">
            <Thumb url={gallery[k].url} alt={ph.what_it_shows} onClick={() => openPhoto(gallery, k)} className="w-44" />
            <dl className="min-w-0 space-y-0.5 text-[13px]">
              <div className="font-medium">{ph.what_it_shows}</div>
              <div className="text-muted">Momento: {MOMENT_LABEL[ph.moment] ?? ph.moment} · {ph.readable ? MATCH_LABEL[ph.matches_scope] : "ilegível"}</div>
              {ph.environment && <div className="text-muted">Ambiente na foto: {ph.environment}{p.scope && (p.scope as { environment?: string }).environment ? ` · pedido: ${(p.scope as { environment?: string }).environment}` : ""}</div>}
              {f.kind === "photo_dated_before" && ph.exif_date && <div className="font-medium text-bad">Data gravada na foto: {new Date(ph.exif_date).toLocaleString("pt-BR")}</div>}
              {ph.reason && ph.reason !== "(simulado)" && <div className="text-muted">{ph.reason}</div>}
              <div className="truncate text-[11px] text-muted/80">{ph.file}</div>
            </dl>
          </div>
        ))}
      </div>
    </div>
  );
}

function ReusedEvidence({ p, photo, other, openPhoto, openTicket }: { p: Assessment; photo: EvaluatedPhoto; other: { ticket: string; file: string }; openPhoto: Props["openPhoto"]; openTicket?: Props["openTicket"] }) {
  const [modal, setModal] = useState(false);
  const link = (
    <button type="button" onClick={() => setModal(true)} disabled={!other.file}
      className="inline-flex items-center gap-1 rounded font-semibold text-lock underline decoration-lock/40 underline-offset-2 hover:decoration-lock disabled:no-underline">
      chamado {other.ticket} <ExternalLink size={12} />
    </button>
  );
  const pair: LightboxItem[] = [
    { url: photoUrl(p.ticket_id, photo.file), caption: `Este chamado (${p.ticket_id}): ${photo.file}` },
    ...(other.file ? [{ url: photoUrl(other.ticket, other.file), caption: `Chamado ${other.ticket}: ${other.file}` }] : []),
  ];
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 font-medium text-lock"><Lock size={14} /> Compare lado a lado com o {link}</span>
        {other.file && (
          <button type="button" onClick={() => setModal(true)} className="flex items-center gap-1 rounded-md border border-lock/30 bg-sheet px-2.5 py-1 text-[13px] font-medium text-lock hover:bg-[#f4f0fb]">
            Ver agência, datas e detalhes <ArrowRight size={14} />
          </button>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {pair.map((it, k) => (
          <figure key={k} className="rounded-md bg-sheet p-2">
            <Thumb url={it.url} alt={it.caption ?? ""} onClick={() => openPhoto(pair, k)} className="w-full" />
            <figcaption className="mt-1 text-[12px]">{k === 0 ? <b>Este chamado</b> : link} <span className="text-muted">· {k === 0 ? photo.file : other.file}</span></figcaption>
          </figure>
        ))}
      </div>
      {photo.integrity_signals.length > 0 && <ul className="mt-1.5 text-[12px] text-lock">{photo.integrity_signals.map((s, k) => <li key={k}>{s}</li>)}</ul>}
      {modal && <ReuseModal ticket={p.ticket_id} file={photo.file} origin={other.ticket} originFile={other.file} onClose={() => setModal(false)} openPhoto={openPhoto} openTicket={openTicket} />}
    </div>
  );
}

function AbsenceEvidence({ p, kind, openPhoto, goTo }: { p: Assessment; kind: "before" | "after"; openPhoto: Props["openPhoto"]; goTo: GoTo }) {
  const gallery = p.photos.map((ph) => ({ url: photoUrl(p.ticket_id, ph.file), caption: `${MOMENT_LABEL[ph.moment] ?? ph.moment}: ${ph.what_it_shows}` }));
  const counts = p.photos.reduce<Record<string, number>>((acc, ph) => ({ ...acc, [ph.moment]: (acc[ph.moment] ?? 0) + 1 }), {});
  const summary = Object.entries(counts).map(([m, n]) => `${n} ${MOMENT_LABEL[m] ?? m}`).join(", ");
  const wanted = kind === "before" ? "antes" : "depois (serviço concluído)";
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
        <span>
          <b className="font-medium">Nenhuma das {p.photos.length} fotos foi classificada como “{wanted}”.</b>
          {summary && <span className="text-muted"> Classificação: {summary}.</span>}
        </span>
        {p.photos.length > 0 && (
          <button onClick={() => goTo("photos")} className="flex items-center gap-1 text-[13px] font-medium text-blueprint hover:underline">Ver todas as fotos <ArrowRight size={14} /></button>
        )}
      </div>
      {p.photos.length ? (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {p.photos.map((ph, k) => (
            <figure key={ph.file} className="w-32 shrink-0">
              <Thumb url={gallery[k].url} alt={ph.what_it_shows} onClick={() => openPhoto(gallery, k)} className="w-32" badge={MOMENT_LABEL[ph.moment] ?? ph.moment} />
            </figure>
          ))}
        </div>
      ) : <p className="text-muted">O chamado não tem fotos.</p>}
      <p className="mt-1 text-[12px] text-muted">Confira se alguma delas mostra o {kind === "before" ? "estado anterior" : "serviço pronto"} e o modelo errou a classificação: nesse caso, marque “Não procede”.</p>
    </div>
  );
}

function Thumb({ url, alt, onClick, className, badge }: { url: string; alt: string; onClick: () => void; className: string; badge?: string }) {
  const [broken, setBroken] = useState(false);
  return (
    <button type="button" onClick={onClick} disabled={broken} className={`group relative shrink-0 overflow-hidden rounded-md bg-paper ${className}`} aria-label={`Ampliar: ${alt}`}>
      {broken ? (
        <span className="flex aspect-[4/3] w-full flex-col items-center justify-center gap-1 text-[11px] text-muted"><ImageOff size={18} /> imagem indisponível</span>
      ) : (
        <img src={url} alt={alt} loading="lazy" onError={() => setBroken(true)} className="aspect-[4/3] w-full object-cover transition duration-300 group-hover:scale-[1.04]" />
      )}
      {badge && <span className="absolute left-1 top-1 rounded bg-ink/80 px-1.5 text-[11px] font-semibold capitalize text-white">{badge}</span>}
    </button>
  );
}
