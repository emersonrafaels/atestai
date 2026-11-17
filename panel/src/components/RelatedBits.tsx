import type { RelatedTicket } from "../api";

/* Pedaços da comparação com chamados da mesma agência, usados na aba Agência, no parecer e no modal de duplicidade. */

/** Situação do chamado (Salesforce) → português (atest/related.py: STATUS_PT). */
const STATUS_PT: Record<string, string> = {
  forwarded_to_backoffice: "em análise no backoffice",
  open: "aberto",
  in_progress: "em execução",
  awaiting_supplier: "aguardando o fornecedor",
  awaiting_quote: "aguardando orçamento",
  approved: "aprovado",
  rejected: "recusado",
  cancelled: "cancelado",
  closed: "encerrado",
  completed: "concluído",
  paid: "pago",
};
export const statusLabel = (s: string) => STATUS_PT[s] ?? s.replace(/_/g, " ");

export const dateBR = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString("pt-BR");

/** "aberto 3 dias antes deste", "no mesmo dia", "2 dias depois" */
export function whenLabel(r: RelatedTicket): string {
  if (r.days_apart === 0) return "aberto no mesmo dia";
  const n = Math.abs(r.days_apart);
  return `aberto ${n} dia${n === 1 ? "" : "s"} ${r.days_apart > 0 ? "antes" : "depois"} deste`;
}

/** Barra da chance de ser o mesmo problema, com as marcas da régua (aparece no parecer / vira apontamento). */
export function ProbabilityBar({ r, show, min }: { r: RelatedTicket; show: number; min: number }) {
  const color = r.flagged ? "var(--color-bad)" : r.probability >= show ? "var(--color-warn)" : "var(--color-muted)";
  return (
    <div className="w-full min-w-[150px]">
      <div className="flex items-baseline justify-between text-[12px]">
        <span className="text-muted">Chance de ser o mesmo problema</span>
        <b className="text-[15px] tabular-nums" style={{ color }}>{r.probability}%</b>
      </div>
      <div className="relative mt-1 h-2 rounded-full bg-paper">
        <div className="h-2 rounded-full" style={{ width: `${r.probability}%`, background: color }} />
        <span className="absolute top-[-3px] h-[14px] w-px bg-ink/40" style={{ left: `${show}%` }} title={`a partir de ${show}%: aparece no parecer`} />
        <span className="absolute top-[-3px] h-[14px] w-0.5 bg-bad" style={{ left: `${min}%` }} title={`a partir de ${min}%: possível chamado duplicado`} />
      </div>
    </div>
  );
}
