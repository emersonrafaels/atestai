import { AlertTriangle, ArrowRight, Building2, CalendarClock, CheckCircle2, CircleDot, Copy, ExternalLink, Link2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { DuplicateModal } from "./DuplicateModal";
import type { LightboxItem } from "./ui/Lightbox";
import type { Assessment, RelatedTicket, TicketDetail } from "../api";
import { branchLabel, brl, envLabel } from "../format";
import { InfoBox } from "./ui/InfoBox";
import { InfoTip } from "./ui/Tooltip";
import { ProbabilityBar, dateBR, statusLabel, whenLabel } from "./RelatedBits";

const RELATION: Record<RelatedTicket["relation"], { label: string; tone: string }> = {
  same_problem: { label: "Mesmo problema", tone: "text-bad" },
  related: { label: "Relacionado", tone: "text-warn" },
  different: { label: "Outro problema", tone: "text-muted" },
};

/**
 * Aba Agência: os chamados da mesma agência que entraram na comparação (abertos na janela de dias ou que seguem
 * abertos), a chance de cada um ser o mesmo problema e o que coincide ou difere.
 */
export function RelatedTab({ p, ticket, openTicket, openPhoto }: {
  p: Assessment; ticket: TicketDetail | null; openTicket?: (id: string) => void; openPhoto: (items: LightboxItem[], index: number) => void;
}) {
  const c = p.related;
  const [compare, setCompare] = useState<RelatedTicket | null>(null);
  if (!c) {
    return (
      <InfoBox tone="tip" title="Sem comparação com chamados da agência">
        {p.recommendation === "checklist_returned"
          ? "O chamado voltou no checklist mínimo, antes desta etapa. Depois que o fornecedor completar os documentos, a análise compara o chamado com os outros da mesma agência."
          : "Este parecer é de uma versão anterior do Atest.AI, sem a comparação com chamados da mesma agência. Analise de novo para ver."}
      </InfoBox>
    );
  }
  const criteria = (
    <>abertos até <b>{c.window_days} dia{c.window_days === 1 ? "" : "s"}</b> antes ou depois deste{c.include_still_open && <> e os que <b>seguem abertos</b>, qualquer que seja a data</>}</>
  );
  const flagged = c.tickets.filter((r) => r.flagged);
  return (
    <div className="space-y-5">
      <section className="flex flex-wrap items-start gap-x-8 gap-y-3 rounded-xl border border-line bg-sheet p-5">
        <div className="min-w-0 flex-1">
          <h3 className="flex items-center gap-2 font-semibold"><Building2 size={17} className="text-blueprint" /> Chamados da mesma agência
            <InfoTip text="É comum a agência abrir mais de um chamado para o mesmo problema (pessoas diferentes, reabertura, categoria escolhida diferente). O Atest.AI compara este chamado com os outros da mesma agência: mesmo número do ponto ou, sem ele, mesmo nome. O modelo lê os escopos e dá a chance de ser o mesmo problema; a régua decide o que vira apontamento." size={13} />
          </h3>
          <p className="mt-1 text-sm text-muted">
            Agência <b className="text-ink">{ticket?.branch ?? branchLabel(p.branch)}</b>. Entram na comparação os chamados {criteria}.
            {" "}A partir de <b>{c.min_probability}%</b> vira <b>possível chamado duplicado</b> (análise detalhada); a partir de <b>{c.show_probability}%</b> aparece no parecer como relacionado.
          </p>
        </div>
        <div className="flex gap-6 text-center">
          <Stat n={c.tickets.length} label={c.candidates_found > c.tickets.length ? `comparados (de ${c.candidates_found})` : "comparados"} />
          <Stat n={flagged.length} label="possível duplicado" tone={flagged.length ? "text-bad" : undefined} />
        </div>
      </section>

      {c.skipped && (
        <InfoBox tone="tip" title="A comparação não rodou">{c.skipped}.</InfoBox>
      )}
      {!c.skipped && c.tickets.length === 0 && (
        <InfoBox tone="tip" title="Nenhum outro chamado da agência">
          Não há chamado da mesma agência {criteria}. Nada a comparar.
        </InfoBox>
      )}

      {c.tickets.map((r) => (
        <article key={r.ticket_id} className={`rounded-xl border bg-sheet p-5 ${r.flagged ? "border-bad/60 ring-1 ring-bad/20" : "border-line"}`}>
          <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="largo text-lg font-bold tabular-nums">{r.ticket_id}</span>
                <span className={`flex items-center gap-1 text-sm font-semibold ${RELATION[r.relation].tone}`}>
                  {r.flagged ? <Copy size={15} /> : r.relation === "related" ? <Link2 size={15} /> : <CircleDot size={15} />}
                  {r.flagged ? "Possível chamado duplicado" : RELATION[r.relation].label}
                </span>
                {r.source === "history" && <span className="rounded-full bg-paper px-2 py-0.5 text-[12px] text-muted">histórico</span>}
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-3 text-[13px] text-muted">
                <span className="flex items-center gap-1"><CalendarClock size={13} /> {dateBR(r.opening)} · {whenLabel(r)}</span>
                <span className={r.is_open ? "font-medium text-ink" : ""}>{statusLabel(r.status)}{!r.in_window && " · entrou por seguir aberto"}</span>
              </div>
            </div>
            <div className="w-full sm:w-64"><ProbabilityBar r={r} show={c.show_probability} min={c.min_probability} /></div>
          </header>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <ScopeBox title="Este chamado" scope={ticket?.scope ?? p.requested_scope ?? ""} meta={[ticket?.category_label, ticket?.symptom_label, envLabel(ticket?.environment ?? "")].filter(Boolean).join(" · ")} supplier={p.supplier} value={p.quoted_value} />
            <ScopeBox title={`Chamado ${r.ticket_id}`} scope={r.scope} meta={[r.category_label, r.symptom_label, envLabel(r.environment)].filter(Boolean).join(" · ")} supplier={r.supplier} value={r.quoted_value} />
          </div>

          {(r.reason || r.matching_points.length > 0 || r.differences.length > 0) && (
            <div className="mt-4 grid gap-4 text-sm lg:grid-cols-3">
              {r.reason && <p className="lg:col-span-3"><b>Leitura do modelo:</b> {r.reason}</p>}
              {r.matching_points.length > 0 && (
                <List icon={<AlertTriangle size={14} className="text-bad" />} title="O que coincide" items={r.matching_points} />
              )}
              {r.differences.length > 0 && (
                <List icon={<CheckCircle2 size={14} className="text-ok" />} title="O que difere" items={r.differences} />
              )}
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-4">
            <button onClick={() => setCompare(r)} aria-haspopup="dialog"
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-semibold ${r.flagged ? "bg-bad text-white hover:brightness-110" : "border border-line hover:bg-paper"}`}>
              Comparar os chamados <ArrowRight size={14} />
            </button>
            {openTicket && r.source === "tickets" && (
              <button onClick={() => openTicket(r.ticket_id)} className="flex items-center gap-1 text-sm font-medium text-blueprint hover:underline">
                Abrir o chamado {r.ticket_id}{r.days_apart > 0 ? " (mais antigo)" : ""} <ExternalLink size={13} />
              </button>
            )}
          </div>
        </article>
      ))}
      {compare && <DuplicateModal p={p} current={ticket} r={compare} onClose={() => setCompare(null)} openPhoto={openPhoto} openTicket={openTicket} />}
    </div>
  );
}

function Stat({ n, label, tone }: { n: number; label: string; tone?: string }) {
  return (
    <div>
      <div className={`largo text-[30px] font-bold leading-none tabular-nums ${tone ?? ""}`}>{n}</div>
      <div className="text-[12px] text-muted">{label}</div>
    </div>
  );
}

function ScopeBox({ title, scope, meta, supplier, value }: { title: string; scope: string; meta: string; supplier: string; value: number | null }) {
  return (
    <div className="rounded-lg bg-paper/50 px-4 py-3">
      <div className="flex items-center gap-1 text-[12px] font-medium text-muted"><ArrowRight size={12} /> {title}</div>
      <p className="mt-1 text-[15px] leading-snug">“{scope}”</p>
      <div className="mt-1.5 text-[12px] text-muted">{meta}{meta && " · "}{supplier}{value ? ` · ${brl(value)}` : ""}</div>
    </div>
  );
}

function List({ icon, title, items }: { icon: ReactNode; title: string; items: string[] }) {
  return (
    <div>
      <div className="mb-1 flex items-center gap-1 text-[12px] font-medium text-muted">{icon} {title}</div>
      <ul className="list-disc space-y-0.5 pl-5">{items.map((x, k) => <li key={k}>{x}</li>)}</ul>
    </div>
  );
}
