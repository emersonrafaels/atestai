import { AlertTriangle, ArrowRight, Building2, CalendarClock, CheckCircle2, Copy, Equal, EqualNot, History, ImageOff, Link2, Loader2, Receipt, Store, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { api, type Assessment, type RelatedTicket, type TicketDetail } from "../api";
import { REC, brl, envLabel, num } from "../format";
import { ProbabilityBar, statusLabel } from "./RelatedBits";
import type { LightboxItem } from "./ui/Lightbox";
import { Tooltip } from "./ui/Tooltip";

const day = (s: string | null | undefined) => (s ? new Date(`${s.slice(0, 10)}T12:00:00`).toLocaleDateString("pt-BR") : "—");
const norm = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\b(ltda|me|eireli|s\.?a\.?|\(ficticio\))\b/g, "").replace(/[^a-z0-9]+/g, " ").trim();

interface Props {
  p: Assessment;
  /** este chamado (aba Entrada), com escopo, datas, orçamento e anexos */
  current: TicketDetail | null;
  r: RelatedTicket;
  onClose: () => void;
  openPhoto: (items: LightboxItem[], index: number) => void;
  /** abre o outro chamado na Análise */
  openTicket?: (id: string) => void;
  /** leva para a aba Agência, com todos os chamados comparados */
  showAll?: () => void;
}

/**
 * Possível chamado duplicado: os dois chamados lado a lado (o mais antigo à esquerda), com a leitura do modelo, o que
 * coincide e o que difere, e o atalho para entrar no outro chamado.
 */
export function DuplicateModal({ p, current, r, onClose, openPhoto, openTicket, showAll }: Props) {
  const [other, setOther] = useState<TicketDetail | null>(null);
  const [loading, setLoading] = useState(r.source === "tickets");
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setOther(null);
    if (r.source !== "tickets") return setLoading(false);
    setLoading(true);
    // chamado do histórico não está na lista: fica só com o que a comparação gravou
    api.ticket(r.ticket_id).then(setOther).catch(() => setOther(null)).finally(() => setLoading(false));
  }, [r.ticket_id, r.source]);

  useEffect(() => {
    dialog.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !document.querySelector('[aria-label="Visualizar foto"]')) onClose();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  const relation = r.flagged ? "Possível chamado duplicado" : r.relation === "related" ? "Chamado relacionado" : "Outro problema da mesma agência";
  // dias_apart > 0: o outro foi aberto antes deste
  const otherIsOlder = r.days_apart > 0 || (r.days_apart === 0 && r.ticket_id < p.ticket_id);
  const gap = Math.abs(r.days_apart);
  const gapText = gap === 0 ? "no mesmo dia" : `${gap} dia${gap === 1 ? "" : "s"} ${r.days_apart > 0 ? "antes" : "depois"} deste`;
  const c = p.related;

  // colunas: o mais antigo à esquerda
  const mine: Side = {
    id: p.ticket_id, label: "Este chamado", detail: current,
    scope: current?.scope ?? p.requested_scope ?? "", solution: current?.solution_description ?? "",
    category: current?.category_label ?? p.category, symptom: current?.symptom_label ?? p.symptom,
    environment: current?.environment ?? p.branch?.environment ?? "", supplier: current?.supplier ?? p.supplier,
    opening: current?.dates.opening ?? null, submission: current?.dates.supplier_submission ?? null,
    status: null, value: p.quoted_value, last: { recommendation: p.recommendation, score: p.score, note: "este parecer" },
  };
  const theirs: Side = {
    id: r.ticket_id, label: `Chamado ${r.ticket_id}`, detail: other,
    scope: other?.scope ?? r.scope, solution: other?.solution_description ?? "",
    category: other?.category_label ?? r.category_label, symptom: other?.symptom_label ?? r.symptom_label,
    environment: other?.environment ?? r.environment, supplier: other?.supplier ?? r.supplier,
    opening: other?.dates.opening ?? r.opening, submission: other?.dates.supplier_submission ?? null,
    status: r.status, value: other?.quoted_value ?? r.quoted_value,
    last: other?.last ? { recommendation: other.last.recommendation, score: other.last.score, note: `em ${day(other.last.generated_at)}` } : null,
  };
  const [left, right] = otherIsOlder ? [theirs, mine] : [mine, theirs];
  const olderId = left.id;

  return createPortal(
    <div className="fixed inset-0 z-[55] flex items-start justify-center overflow-y-auto bg-ink/60 p-4 sm:p-6" onClick={onClose}>
      <div ref={dialog} role="dialog" aria-modal="true" aria-labelledby="dup-title" tabIndex={-1}
        className="surgir w-full max-w-5xl rounded-2xl bg-sheet shadow-2xl outline-none" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div className="min-w-0">
            <div className={`flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide ${r.flagged ? "text-bad" : "text-warn"}`}>
              {r.flagged ? <Copy size={13} /> : <Link2 size={13} />} {relation}
            </div>
            <h2 id="dup-title" className="largo text-xl font-bold">Chamado {r.ticket_id} × este chamado ({p.ticket_id})</h2>
            <p className="text-sm text-muted">Mesma agência · {r.ticket_id} foi aberto {gapText} · {statusLabel(r.status)}{!r.in_window && " (entrou por seguir aberto)"}</p>
          </div>
          <button aria-label="Fechar" onClick={onClose} className="rounded-full p-1.5 hover:bg-paper"><X size={18} /></button>
        </header>

        <div className="space-y-5 px-6 py-5">
          {/* veredito */}
          <div className={`grid gap-4 rounded-xl border p-4 md:grid-cols-[1fr_260px] ${r.flagged ? "border-bad/30 bg-[#fbefed]" : "border-warn/40 bg-[#fdf6e4]"}`}>
            <div className="flex items-start gap-3 text-sm">
              <AlertTriangle className={`mt-0.5 shrink-0 ${r.flagged ? "text-bad" : "text-warn"}`} />
              <div>
                <div className="font-semibold">
                  {r.flagged
                    ? <>Pode ser o mesmo problema: há risco de pagar duas vezes pelo mesmo serviço.</>
                    : <>Os chamados têm relação, mas a chance de ser o mesmo problema ficou abaixo de {c?.min_probability ?? 70}%.</>}
                </div>
                {r.reason && <p className="mt-1 text-ink/80">{r.reason}</p>}
                <p className="mt-1.5 text-ink/80">
                  O mais antigo é o <b>{olderId}</b>{olderId === p.ticket_id ? " (este chamado)" : ""}. Confira com a agência se é o mesmo problema
                  {r.flagged ? " e, se for, siga com um chamado só." : "."}
                </p>
              </div>
            </div>
            <div className="self-center"><ProbabilityBar r={r} show={c?.show_probability ?? 40} min={c?.min_probability ?? 70} /></div>
          </div>

          {(r.matching_points.length > 0 || r.differences.length > 0) && (
            <div className="grid gap-3 md:grid-cols-2">
              <Points tone="bad" icon={<Equal size={14} />} title="O que coincide" items={r.matching_points} empty="nada em comum apontado" />
              <Points tone="ok" icon={<EqualNot size={14} />} title="O que difere" items={r.differences} empty="nenhuma diferença apontada" />
            </div>
          )}

          {loading && <div className="flex items-center justify-center gap-2 py-6 text-muted"><Loader2 className="animate-spin" size={18} /> Carregando o chamado {r.ticket_id}…</div>}

          {!loading && (
            <>
              <Compare left={left} right={right} olderId={olderId} />
              <div className="grid gap-4 md:grid-cols-2">
                <Evidence side={left} older={left.id === olderId} openPhoto={openPhoto} />
                <Evidence side={right} older={right.id === olderId} openPhoto={openPhoto} />
              </div>
            </>
          )}
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-6 py-3 text-sm">
          <span className="text-muted">
            {r.source === "history" ? "O outro chamado está no histórico (já encerrado), por isso não aparece na lista." : showAll && (
              <button onClick={() => { onClose(); showAll(); }} className="font-medium text-blueprint hover:underline">Ver todos os chamados da agência</button>
            )}
          </span>
          <div className="flex flex-wrap gap-2">
            {openTicket && r.source === "tickets" && (
              <button onClick={() => { onClose(); openTicket(r.ticket_id); }}
                className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 font-semibold ${otherIsOlder ? "bg-blueprint text-white hover:bg-[#1d44a0]" : "border border-line hover:bg-paper"}`}>
                {otherIsOlder ? <History size={15} /> : null}
                {otherIsOlder ? `Abrir o chamado mais antigo (${r.ticket_id})` : `Abrir o chamado ${r.ticket_id}`} <ArrowRight size={15} />
              </button>
            )}
            <button onClick={onClose} className={`rounded-lg px-4 py-1.5 font-semibold ${otherIsOlder && openTicket && r.source === "tickets" ? "border border-line hover:bg-paper" : "bg-blueprint text-white hover:bg-[#1d44a0]"}`}>Fechar</button>
          </div>
        </footer>
      </div>
    </div>,
    document.body,
  );
}

interface Side {
  id: string;
  label: string;
  detail: TicketDetail | null;
  scope: string;
  solution: string;
  category: string;
  symptom: string;
  environment: string;
  supplier: string;
  opening: string | null;
  submission: string | null;
  status: string | null;
  value: number | null;
  last: { recommendation: Assessment["recommendation"]; score: number | null; note: string } | null;
}

function Points({ tone, icon, title, items, empty }: { tone: "bad" | "ok"; icon: ReactNode; title: string; items: string[]; empty: string }) {
  return (
    <div className={`rounded-lg px-4 py-3 text-sm ${tone === "bad" ? "bg-[#fbefed]/70" : "bg-[#e3f2ea]/60"}`}>
      <div className={`mb-1 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide ${tone === "bad" ? "text-bad" : "text-ok"}`}>{icon} {title}</div>
      {items.length ? <ul className="list-disc space-y-0.5 pl-5">{items.map((x, k) => <li key={k}>{x}</li>)}</ul> : <p className="text-muted">{empty}</p>}
    </div>
  );
}

function Compare({ left, right, olderId }: { left: Side; right: Side; olderId: string }) {
  const rows: { icon?: ReactNode; label: string; a: ReactNode; b: ReactNode; same?: boolean; hot?: boolean }[] = [
    { label: "Descrição do problema", a: <span className="italic">“{left.scope}”</span>, b: <span className="italic">“{right.scope}”</span> },
    { label: "Descrição da solução", a: left.solution || <span className="text-muted">—</span>, b: right.solution || <span className="text-muted">—</span> },
    { icon: <Building2 size={14} />, label: "Local do chamado", a: envLabel(left.environment) || "—", b: envLabel(right.environment) || "—", same: !!left.environment && left.environment === right.environment, hot: !!left.environment && left.environment === right.environment },
    { label: "Categoria · sintoma", a: <>{left.category}<div className="text-[12px] text-muted">{left.symptom}</div></>, b: <>{right.category}<div className="text-[12px] text-muted">{right.symptom}</div></>, same: left.category === right.category },
    { icon: <Store size={14} />, label: "Fornecedor", a: left.supplier, b: right.supplier, same: norm(left.supplier) === norm(right.supplier) },
    { icon: <CalendarClock size={14} />, label: "Abertura", a: day(left.opening), b: day(right.opening) },
    { label: "Envio do fornecedor", a: day(left.submission), b: day(right.submission) },
    { label: "Situação", a: left.status ? statusLabel(left.status) : "em análise agora", b: right.status ? statusLabel(right.status) : "em análise agora" },
    { icon: <Receipt size={14} />, label: "Valor orçado", a: left.value !== null ? brl(left.value) : "—", b: right.value !== null ? brl(right.value) : "—" },
    { label: "Último parecer", a: <Last s={left} />, b: <Last s={right} /> },
  ];
  const head = (s: Side) => (
    <span className="flex flex-wrap items-center gap-1.5">
      {s.label}{s.label === "Este chamado" && <span className="font-normal text-muted">· {s.id}</span>}
      {s.id === olderId && <span className="rounded-full bg-ink px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-white">mais antigo</span>}
    </span>
  );
  return (
    <div className="overflow-x-auto rounded-xl border border-line">
      <table className="w-full min-w-[640px] text-sm">
        <thead className="bg-paper text-left text-[13px]">
          <tr>
            <th className="w-40 px-3 py-2 font-medium text-muted" />
            <th className="px-3 py-2 font-semibold">{head(left)}</th>
            <th className="w-8" />
            <th className="px-3 py-2 font-semibold">{head(right)}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((x) => (
            <tr key={x.label} className={`border-t border-line/70 align-top ${x.hot ? "bg-[#fbefed]/50" : ""}`}>
              <th className="px-3 py-2 text-left font-medium text-muted"><span className="flex items-center gap-1.5">{x.icon}{x.label}</span></th>
              <td className="px-3 py-2">{x.a}</td>
              <td className="py-2 text-center">
                {x.same !== undefined && (
                  <Tooltip content={x.same ? "Igual nos dois chamados" : "Diferente"}>
                    <span className={`inline-flex rounded p-0.5 ${x.same ? "bg-paper text-ink" : "text-muted"}`}>{x.same ? <Equal size={13} /> : <EqualNot size={13} />}</span>
                  </Tooltip>
                )}
              </td>
              <td className="px-3 py-2">{x.b}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Last({ s }: { s: Side }) {
  if (!s.last) return <span className="text-muted">ainda não analisado</span>;
  return (
    <span>
      <b style={{ color: REC[s.last.recommendation].color }}>{REC[s.last.recommendation].label}</b>
      {s.last.score !== null && <span className="tabular-nums"> · score {s.last.score}</span>}
      <span className="text-[12px] text-muted"> · {s.last.note}</span>
    </span>
  );
}

/** Itens do orçamento e fotos de um dos chamados (quando ele está na lista). */
function Evidence({ side, older, openPhoto }: { side: Side; older: boolean; openPhoto: Props["openPhoto"] }) {
  const d = side.detail;
  const photos = (d?.attachments ?? []).filter((a) => a.is_image);
  const items: LightboxItem[] = photos.map((a) => ({ url: a.url, caption: `${side.label === "Este chamado" ? `Este chamado (${side.id})` : side.label} · ${a.name}` }));
  return (
    <section className={`rounded-xl border-2 bg-sheet ${older ? "border-ink/25" : "border-line"}`}>
      <h3 className="flex items-center justify-between gap-2 border-b border-line px-3 py-2 text-sm font-semibold">
        <span>{side.label}{side.label === "Este chamado" ? ` · ${side.id}` : ""}</span>
        {older && <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">mais antigo</span>}
      </h3>
      {!d ? (
        <p className="px-3 py-4 text-[13px] text-muted">Orçamento e fotos indisponíveis (chamado fora da lista).</p>
      ) : (
        <div className="space-y-3 px-3 py-3">
          <div>
            <div className="mb-1 text-[12px] font-medium text-muted">Itens do orçamento</div>
            {d.quote?.items.length ? (
              <table className="w-full text-[13px]">
                <tbody>
                  {d.quote.items.map((i) => (
                    <tr key={i.n} className="border-t border-line/60 first:border-0 align-top">
                      <td className="w-6 py-1 text-muted tabular-nums">{i.n}</td>
                      <td className="py-1 pr-2">{i.description}</td>
                      <td className="whitespace-nowrap py-1 text-right tabular-nums text-muted">{num(i.quantity)} {i.unit}</td>
                      <td className="whitespace-nowrap py-1 pl-2 text-right tabular-nums">{brl(i.total_value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="text-[13px] text-muted">{d.quote_error ?? "sem itens"}</p>}
          </div>
          <div>
            <div className="mb-1 text-[12px] font-medium text-muted">Fotos ({photos.length})</div>
            {photos.length ? (
              <div className="grid grid-cols-3 gap-1.5">
                {photos.map((a, k) => <Thumb key={a.name} url={a.url} name={a.name} onOpen={() => openPhoto(items, k)} />)}
              </div>
            ) : <p className="flex items-center gap-1 text-[13px] text-muted"><CheckCircle2 size={13} /> nenhuma foto enviada</p>}
          </div>
        </div>
      )}
    </section>
  );
}

function Thumb({ url, name, onOpen }: { url: string; name: string; onOpen: () => void }) {
  const [broken, setBroken] = useState(false);
  return (
    <button type="button" onClick={onOpen} disabled={broken} aria-label={`Ampliar ${name}`} title={name}
      className="group block overflow-hidden rounded-md bg-paper">
      {broken
        ? <span className="flex aspect-[4/3] items-center justify-center text-muted"><ImageOff size={16} /></span>
        : <img src={url} alt={name} onError={() => setBroken(true)} className="aspect-[4/3] w-full object-cover transition duration-300 group-hover:scale-[1.04]" />}
    </button>
  );
}
