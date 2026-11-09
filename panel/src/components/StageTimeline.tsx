import { Check, FileText, Hammer, Receipt, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import type { TicketDetail } from "../api";
import { STAGE_DOCS } from "../format";
import { Tooltip } from "./ui/Tooltip";

type State = "done" | "current" | "next";
interface Step {
  key: string;
  title: string;
  icon: ReactNode;
  state: State;
  when: string;
  detail: string;
  docs?: string[];
}

/** rótulos curtos para os selos (o texto completo fica no tooltip) */
const CHIP: Record<string, string> = { "Orçamento (planilha padrão)": "Orçamento", "Demais documentos do checklist da categoria": "Checklist da categoria" };

const day = (d?: string | null) => (d ? new Date(`${d.slice(0, 10)}T12:00:00`).toLocaleDateString("pt-BR") : null);
const daysBetween = (a?: string | null, b?: string | null) =>
  a && b ? Math.round((new Date(`${b.slice(0, 10)}T12:00:00`).getTime() - new Date(`${a.slice(0, 10)}T12:00:00`).getTime()) / 86400000) : null;

/**
 * Linha do tempo da esteira: abertura → aprovação de orçamento → execução → atestação do serviço.
 * Destaca em qual etapa este chamado está e o que o fornecedor envia em cada uma.
 */
export function StageTimeline({ ticket }: { ticket: TicketDetail }) {
  const quote = ticket.moment === "quote";
  const opened = day(ticket.dates.opening);
  const sent = day(ticket.dates.supplier_submission);
  const review = day(ticket.dates.manager_review);
  const gap = daysBetween(ticket.dates.opening, ticket.dates.supplier_submission);
  const sentLine = sent ? `Enviado em ${sent}${gap !== null && gap > 0 ? ` (${gap} dia${gap === 1 ? "" : "s"} após a abertura)` : ""}` : "Envio sem data";

  const steps: Step[] = [
    { key: "open", title: "Abertura", icon: <FileText size={15} />, state: "done", when: opened ?? "—", detail: "Chamado aberto pela agência" },
    {
      key: "quote", title: "Aprovação de Orçamento", icon: <Receipt size={15} />, state: quote ? "current" : "done",
      when: quote ? sentLine : "Concluída", detail: quote ? "O fornecedor enviou o orçamento para aprovação" : "Orçamento aprovado antes da execução",
      docs: STAGE_DOCS.quote,
    },
    {
      key: "work", title: "Execução do serviço", icon: <Hammer size={15} />, state: quote ? "next" : "done",
      when: quote ? "Depois da aprovação" : "Concluída", detail: quote ? "Só começa depois que o orçamento for aprovado" : "Serviço executado pelo fornecedor",
    },
    {
      key: "service", title: "Atestação do Serviço", icon: <ShieldCheck size={15} />, state: quote ? "next" : "current",
      when: quote ? "Próxima etapa" : sentLine, detail: quote ? "Virá com as fotos do depois e os demais documentos" : "O fornecedor enviou as evidências do serviço concluído",
      docs: STAGE_DOCS.execution,
    },
  ];
  const current = steps.find((s) => s.state === "current")!;

  return (
    <section aria-label="Linha do tempo do chamado" className="mb-5 rounded-xl border border-line bg-sheet px-5 pb-4 pt-3">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">
          Este chamado está na etapa <span className="text-blueprint">{current.title}</span>
        </h3>
        <span className="text-[12px] text-muted">
          {quote ? "O Atest.AI confere escopo, orçamento e fotos do antes." : "O Atest.AI confere escopo, orçamento, fotos do antes e do depois e o checklist da categoria."}
          {review && <> · Revisão do gestor em {review}</>}
        </span>
      </div>

      <ol className="grid gap-3 md:grid-cols-4 md:gap-0">
        {steps.map((s, i) => (
          <li key={s.key} className="relative flex gap-3 md:flex-col md:items-center md:gap-2 md:px-2 md:text-center">
            {/* conector com o próximo passo */}
            {i < steps.length - 1 && (
              <span aria-hidden className={`absolute left-[15px] top-8 h-[calc(100%-8px)] w-0.5 md:left-[calc(50%+18px)] md:top-[15px] md:h-0.5 md:w-[calc(100%-36px)] ${
                steps[i + 1].state === "next" ? "border-l-2 border-dashed border-line md:border-l-0 md:border-t-2 bg-transparent" : "bg-blueprint"}`} />
            )}
            <Tooltip className="relative z-10 inline-flex shrink-0" content={
              <>
                <b>{s.title}</b><br />{s.detail}
                {s.docs && <span className="mt-1 block">Fornecedor envia: {s.docs.join(", ").toLowerCase()}.</span>}
              </>
            }>
              <span className={`flex size-8 cursor-help items-center justify-center rounded-full transition-colors ${
                s.state === "current" ? "bg-blueprint text-white shadow-[0_0_0_5px_rgb(36_80_184/0.15)]"
                  : s.state === "done" ? "bg-blueprint-soft text-blueprint"
                  : "border-2 border-dashed border-line bg-sheet text-muted"}`}>
                {s.state === "done" ? <Check size={15} strokeWidth={3} /> : s.icon}
              </span>
            </Tooltip>
            <div className="min-w-0 pb-1">
              <div className={`text-[13px] font-semibold leading-tight ${s.state === "next" ? "text-muted" : s.state === "current" ? "text-blueprint" : ""}`}>
                {s.title}
                {s.state === "current" && <span className="ml-1.5 rounded bg-blueprint px-1.5 py-px align-middle text-[10px] font-bold uppercase tracking-wide text-white">agora</span>}
              </div>
              <div className={`text-[12px] ${s.state === "current" ? "text-ink/80" : "text-muted"}`}>{s.when}</div>
              {s.state === "current" && s.docs && (
                <div className="mt-1 flex flex-wrap gap-1 md:justify-center">
                  {s.docs.map((d) => <span key={d} title={d} className="rounded-full bg-paper px-2 py-px text-[11px] text-ink/70">{CHIP[d] ?? d}</span>)}
                </div>
              )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
