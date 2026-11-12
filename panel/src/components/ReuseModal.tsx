import { AlertTriangle, ArrowRight, Building2, CalendarClock, Camera, CheckCircle2, Equal, ImageOff, Loader2, Lock, EqualNot, Store, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { api, type PhotoFacts, type ReuseComparison, type TicketFacts } from "../api";
import { brl, REC, envLabel } from "../format";
import type { LightboxItem } from "./ui/Lightbox";
import { Tooltip } from "./ui/Tooltip";

const STATUS: Record<string, { label: string; cls: string }> = {
  approved: { label: "Aprovado", cls: "bg-[#e3f2ea] text-ok" },
  paid: { label: "Pago", cls: "bg-[#e3f2ea] text-ok" },
  rejected: { label: "Recusado", cls: "bg-[#f8e4e2] text-bad" },
  returned: { label: "Devolvido", cls: "bg-[#f8e4e2] text-bad" },
  forwarded_to_backoffice: { label: "No backoffice", cls: "bg-blueprint-soft text-blueprint" },
};

const day = (s: string | null) => (s ? new Date(`${s.slice(0, 10)}T12:00:00`).toLocaleDateString("pt-BR") : "—");
const dateTime = (s: string) => new Date(s).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
const hasTime = (s: string) => !s.endsWith("T00:00:00");
const kb = (n: number | null) => (n === null ? "—" : n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.round(n / 1e3)} KB`);

function gap(hours: number): string {
  const h = Math.abs(hours);
  if (h < 1) return "menos de 1 hora";
  if (h < 48) return `${Math.round(h)} hora${Math.round(h) === 1 ? "" : "s"}`;
  const d = Math.round(h / 24);
  return d < 60 ? `${d} dias` : `${d} dias (~${Math.round(d / 30)} meses)`;
}

interface Props {
  ticket: string;
  file: string;
  origin: string;
  originFile: string;
  onClose: () => void;
  openPhoto: (items: LightboxItem[], index: number) => void;
  /** abre o chamado de origem na Análise, quando ele está na lista */
  openTicket?: (id: string) => void;
}

/** Comparação lado a lado entre o chamado atual e o chamado de onde a foto foi reaproveitada. */
export function ReuseModal({ ticket, file, origin, originFile, onClose, openPhoto, openTicket }: Props) {
  const [data, setData] = useState<ReuseComparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    api.reuse(ticket, file, origin, originFile).then(setData).catch((e) => setError((e as Error).message));
  }, [ticket, file, origin, originFile]);

  useEffect(() => {
    dialog.current?.focus();
    const key = (e: KeyboardEvent) => {
      // Esc fecha a foto ampliada primeiro, se houver
      if (e.key === "Escape" && !document.querySelector('[aria-label="Visualizar foto"]')) onClose();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  return createPortal(
    <div className="fixed inset-0 z-[55] flex items-start justify-center overflow-y-auto bg-ink/60 p-4 sm:p-6" onClick={onClose}>
      <div ref={dialog} role="dialog" aria-modal="true" aria-labelledby="reuse-title" tabIndex={-1}
        className="surgir w-full max-w-5xl rounded-2xl bg-sheet shadow-2xl outline-none" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div>
            <div className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-lock"><Lock size={13} /> Foto reaproveitada</div>
            <h2 id="reuse-title" className="largo text-xl font-bold">Chamado de origem {origin}</h2>
            <p className="text-sm text-muted">Comparação com o chamado {ticket}, que está em análise.</p>
          </div>
          <button aria-label="Fechar" onClick={onClose} className="rounded-full p-1.5 hover:bg-paper"><X size={18} /></button>
        </header>

        {!data && !error && <div className="flex items-center justify-center gap-2 p-16 text-muted"><Loader2 className="animate-spin" /> Carregando os dois chamados…</div>}
        {error && <p className="m-6 rounded-lg bg-[#fbefed] p-4 text-sm text-bad">Não foi possível carregar a comparação: {error}</p>}
        {data && <Body d={data} openPhoto={openPhoto} />}

        {data && (
          <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-6 py-3 text-sm">
            <span className="text-muted">
              {data.origin.source === "history" ? "O chamado de origem está no histórico (já encerrado), por isso não aparece na lista." : "O chamado de origem também está na lista de chamados."}
            </span>
            <div className="flex gap-2">
              {openTicket && data.origin.source === "tickets" && (
                <button onClick={() => { onClose(); openTicket(origin); }} className="flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 font-medium hover:bg-paper">
                  Abrir chamado {origin} <ArrowRight size={15} />
                </button>
              )}
              <button onClick={onClose} className="rounded-lg bg-blueprint px-4 py-1.5 font-semibold text-white hover:bg-[#1d44a0]">Fechar</button>
            </div>
          </footer>
        )}
      </div>
    </div>,
    document.body,
  );
}

function Body({ d, openPhoto }: { d: ReuseComparison; openPhoto: Props["openPhoto"] }) {
  const pair: LightboxItem[] = [
    { url: d.origin_photo.url, caption: `Origem: chamado ${d.origin.ticket_id} · ${d.origin_photo.file}` },
    { url: d.current_photo.url, caption: `Este chamado (${d.current.ticket_id}) · ${d.current_photo.file}` },
  ];
  const identical = d.distance !== null && d.distance <= 3;
  const notes: { tone: "bad" | "warn" | "info"; text: ReactNode }[] = [];
  if (d.same_supplier && !d.same_branch) notes.push({ tone: "bad", text: <>O <b>mesmo fornecedor</b> enviou a foto em <b>outra agência</b> ({d.origin.branch_name}): forte indício de reaproveitamento.</> });
  if (d.same_branch) notes.push({ tone: "warn", text: <>É a <b>mesma agência</b>: pode ser o mesmo local fotografado de novo. Confira se o serviço é de fato diferente.</> });
  if (!d.same_supplier) notes.push({ tone: "warn", text: <>Fornecedores <b>diferentes</b>: a foto pode ter circulado entre empresas. Vale encaminhar à auditoria.</> });
  if (["approved", "paid"].includes(d.origin.status)) notes.push({ tone: "bad", text: <>O chamado de origem já foi <b>{STATUS[d.origin.status].label.toLowerCase()}</b>{d.origin.manager_review ? ` em ${day(d.origin.manager_review)}` : ""}: o mesmo serviço pode ser cobrado duas vezes.</> });
  if (!d.current_photo.taken_at) notes.push({ tone: "info", text: <>A foto deste chamado <b>não tem data de captura (EXIF)</b>. Isso é comum em foto reenviada por WhatsApp ou print de tela.</> });

  return (
    <div className="space-y-5 px-6 py-5">
      {/* veredito de ordem no tempo */}
      <div className={`flex items-start gap-3 rounded-xl border p-4 ${d.chronology_ok ? "border-lock/30 bg-[#f4f0fb]" : "border-warn/40 bg-[#fdf6e4]"}`}>
        {d.chronology_ok ? <CheckCircle2 className="mt-0.5 shrink-0 text-lock" /> : <AlertTriangle className="mt-0.5 shrink-0 text-warn" />}
        <div className="text-sm">
          <div className="font-semibold">
            {d.chronology_ok
              ? <>A origem é anterior: a foto já existia {gap(d.gap_hours)} antes deste chamado.</>
              : <>Ordem inconsistente: a “origem” é {gap(d.gap_hours)} posterior a este chamado. Revise com cuidado.</>}
          </div>
          <div className="mt-0.5 text-ink/75">
            Origem: <b>{hasTime(d.origin_moment) ? dateTime(d.origin_moment) : day(d.origin_moment)}</b> {d.origin_photo.taken_at ? "(foto tirada, EXIF)" : "(dia do envio)"}
            {"  ≤  "}
            Este chamado: <b>{hasTime(d.current_moment) ? dateTime(d.current_moment) : day(d.current_moment)}</b> {d.current_photo.taken_at ? "(foto tirada, EXIF)" : "(dia do envio)"}
          </div>
        </div>
      </div>

      {/* as duas fotos */}
      <div className="grid gap-4 md:grid-cols-2">
        <PhotoCard title={`Origem · chamado ${d.origin.ticket_id}`} p={d.origin_photo} onOpen={() => openPhoto(pair, 0)} accent="lock" />
        <PhotoCard title={`Este chamado · ${d.current.ticket_id}`} p={d.current_photo} onOpen={() => openPhoto(pair, 1)} />
      </div>
      <Similarity d={d} identical={identical} />

      {/* leitura automática */}
      {notes.length > 0 && (
        <ul className="space-y-1.5 text-sm">
          {notes.map((n, k) => (
            <li key={k} className={`flex items-start gap-2 rounded-lg px-3 py-2 ${n.tone === "bad" ? "bg-[#fbefed]" : n.tone === "warn" ? "bg-[#fdf6e4]" : "bg-paper"}`}>
              <span className={`mt-1.5 size-1.5 shrink-0 rounded-full ${n.tone === "bad" ? "bg-bad" : n.tone === "warn" ? "bg-warn" : "bg-muted"}`} />
              <span>{n.text}</span>
            </li>
          ))}
        </ul>
      )}

      {/* os dois chamados lado a lado */}
      <Compare o={d.origin} c={d.current} />
    </div>
  );
}

function PhotoCard({ title, p, onOpen, accent }: { title: string; p: PhotoFacts; onOpen: () => void; accent?: "lock" }) {
  const [broken, setBroken] = useState(false);
  return (
    <figure className={`overflow-hidden rounded-xl border-2 bg-sheet ${accent === "lock" ? "border-lock/50" : "border-line"}`}>
      <figcaption className="flex items-center justify-between gap-2 border-b border-line px-3 py-2 text-sm">
        <b>{title}</b>
        <span className="truncate text-[12px] text-muted" title={p.file}>{p.file}</span>
      </figcaption>
      <button type="button" onClick={onOpen} disabled={broken} aria-label={`Ampliar ${p.file}`} className="group block w-full overflow-hidden bg-paper">
        {broken
          ? <span className="flex aspect-[4/3] flex-col items-center justify-center gap-1 text-sm text-muted"><ImageOff /> imagem indisponível</span>
          : <img src={p.url} alt={p.file} onError={() => setBroken(true)} className="aspect-[4/3] w-full object-cover transition duration-300 group-hover:scale-[1.02]" />}
      </button>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 px-3 py-2.5 text-[13px]">
        <div className="col-span-2 flex items-center gap-1.5">
          <Camera size={14} className="text-muted" />
          <dt className="text-muted">Tirada em</dt>
          <dd className="font-semibold">{p.taken_at ? dateTime(p.taken_at) : <span className="font-normal text-warn">sem EXIF</span>}</dd>
        </div>
        <div><dt className="text-muted">Enviada em</dt><dd className="font-medium">{day(p.uploaded_on)}</dd></div>
        <div><dt className="text-muted">Resolução · tamanho</dt><dd className="font-medium tabular-nums">{p.width && p.height ? `${p.width}×${p.height}` : "—"} · {kb(p.size_bytes)}</dd></div>
      </dl>
    </figure>
  );
}

function Similarity({ d, identical }: { d: ReuseComparison; identical: boolean }) {
  if (d.distance === null) return null;
  const w = Math.max(3, 100 - (100 * d.distance) / 64);
  return (
    <div className="rounded-lg bg-paper/70 px-4 py-3 text-sm">
      <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-semibold">{identical ? "Fotos idênticas" : d.distance <= d.limit ? "Fotos muito semelhantes" : "Fotos diferentes"}</span>
        <Tooltip content={`Distância entre as impressões digitais das fotos (phash + dhash): 0 = idênticas. Acima de ${d.limit}, a régua considera fotos diferentes. A comparação inclui recortes da original, para pegar foto cortada ou reenviada.`}>
          <span className="cursor-help text-[12px] text-muted underline decoration-dotted underline-offset-2">distância {d.distance} (limite {d.limit})</span>
        </Tooltip>
      </div>
      <div className="h-2 rounded-full bg-line/60"><div className="h-2 rounded-full bg-lock" style={{ width: `${w}%` }} /></div>
    </div>
  );
}

function Compare({ o, c }: { o: TicketFacts; c: TicketFacts }) {
  const rows: { icon?: ReactNode; label: string; a: ReactNode; b: ReactNode; same?: boolean; hot?: boolean }[] = [
    { icon: <Building2 size={14} />, label: "Agência", a: <>{o.branch_name} <span className="text-muted">· cód. {o.branch_code}</span></>, b: <>{c.branch_name} <span className="text-muted">· cód. {c.branch_code}</span></>, same: o.branch_code === c.branch_code },
    { label: "Local do chamado", a: envLabel(o.environment), b: envLabel(c.environment), same: o.environment === c.environment },
    { icon: <Store size={14} />, label: "Fornecedor", a: <>{o.supplier_name}<div className="text-[12px] text-muted">CNPJ {o.supplier_cnpj}</div></>, b: <>{c.supplier_name}<div className="text-[12px] text-muted">CNPJ {c.supplier_cnpj}</div></>, same: o.supplier_cnpj === c.supplier_cnpj, hot: o.supplier_cnpj === c.supplier_cnpj },
    { label: "Esteira · categoria", a: <>{o.workstream} · {o.category_label}<div className="text-[12px] text-muted">{o.symptom_label}</div></>, b: <>{c.workstream} · {c.category_label}<div className="text-[12px] text-muted">{c.symptom_label}</div></> },
    { label: "Descrição do problema", a: <span className="italic">“{o.scope}”</span>, b: <span className="italic">“{c.scope}”</span> },
    { icon: <CalendarClock size={14} />, label: "Abertura", a: day(o.opening), b: day(c.opening) },
    { label: "Envio do fornecedor", a: day(o.supplier_submission), b: day(c.supplier_submission) },
    { label: "Revisão do gestor", a: day(o.manager_review), b: day(c.manager_review) },
    { label: "Situação", a: <Status s={o.status} />, b: <Status s={c.status} /> },
    { label: "Valor orçado", a: o.quoted_value !== null ? brl(o.quoted_value) : "—", b: c.quoted_value !== null ? brl(c.quoted_value) : "—" },
    { label: "Último parecer", a: <LastRec t={o} />, b: <LastRec t={c} /> },
    { label: "Fotos no chamado", a: o.n_photos, b: c.n_photos },
  ];
  return (
    <div className="overflow-x-auto rounded-xl border border-line">
      <table className="w-full min-w-[620px] text-sm">
        <thead className="bg-paper text-left text-[13px]">
          <tr>
            <th className="w-44 px-3 py-2 font-medium text-muted" />
            <th className="px-3 py-2 font-semibold text-lock">Origem · {o.ticket_id}</th>
            <th className="w-8" />
            <th className="px-3 py-2 font-semibold">Este chamado · {c.ticket_id}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className={`border-t border-line/70 align-top ${r.hot ? "bg-[#fbefed]/60" : ""}`}>
              <th className="px-3 py-2 text-left font-medium text-muted"><span className="flex items-center gap-1.5">{r.icon}{r.label}</span></th>
              <td className="px-3 py-2">{r.a}</td>
              <td className="py-2 text-center">
                {r.same !== undefined && (
                  <Tooltip content={r.same ? "Igual nos dois chamados" : "Diferente"}>
                    <span className={`inline-flex rounded p-0.5 ${r.same ? (r.hot ? "bg-bad text-white" : "bg-paper text-ink") : "text-muted"}`}>{r.same ? <Equal size={13} /> : <EqualNot size={13} />}</span>
                  </Tooltip>
                )}
              </td>
              <td className="px-3 py-2">{r.b}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Status({ s }: { s: string }) {
  const st = STATUS[s] ?? { label: s, cls: "bg-paper text-muted" };
  return <span className={`rounded-full px-2 py-0.5 text-[12px] font-semibold ${st.cls}`}>{st.label}</span>;
}

function LastRec({ t }: { t: TicketFacts }) {
  if (!t.last_recommendation) return <span className="text-muted">{t.source === "history" ? "anterior ao Atest.AI" : "não analisado"}</span>;
  const r = REC[t.last_recommendation];
  return <span className="font-medium" style={{ color: r.color }}>{r.label}{t.last_score !== null ? ` · score ${t.last_score}` : ""}</span>;
}
