import { useEffect } from "react";
import type { Assessment } from "../api";
import { brl, num, findingLabel } from "../format";

const CLASS = {
  compliant: { label: "Aderente", cls: "bg-[#e3f2ea] text-ok" },
  out_of_scope: { label: "Fora do escopo", cls: "bg-[#f8e4e2] text-bad" },
  to_justify: { label: "Sem justificativa", cls: "bg-[#f8eedb] text-warn" },
} as const;

export function QuoteTab({ p, highlight = [] }: { p: Assessment; highlight?: number[] }) {
  useScrollToHighlight(highlight.map((n) => `quote-item-${n}`));
  if (!p.items.length) return <p className="text-muted">O orçamento não foi conferido neste chamado.</p>;
  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-xl border border-line bg-sheet">
        <table className="w-full min-w-[920px] text-sm">
          <thead className="bg-paper text-left text-[13px] text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">#</th><th className="px-3 py-2 font-medium">Item cobrado e leitura do modelo</th>
              <th className="px-3 py-2 text-right font-medium">Qtd</th><th className="px-3 py-2 text-right font-medium">Unitário</th>
              <th className="px-3 py-2 text-right font-medium">Referência</th><th className="px-3 py-2 text-right font-medium">Total</th>
              <th className="px-3 py-2 text-right font-medium">Potencial divergente</th>
              <th className="px-3 py-2 font-medium">Classificação</th>
            </tr>
          </thead>
          <tbody>
            {p.items.map((i) => {
              const c = CLASS[i.classification];
              const above = i.reference_price !== null && i.unit_value > i.reference_price * 1.1;
              return (
                <tr key={i.n} id={`quote-item-${i.n}`} className={`border-t border-line/70 align-top ${highlight.includes(i.n) ? "destaque" : i.findings.length ? "bg-[#fffaf3]" : ""}`}>
                  <td className="px-3 py-2.5 tabular-nums">{i.n}</td>
                  <td className="px-3 py-2.5">
                    <div className="font-medium">{i.description}</div>
                    <div className="text-[13px] text-muted">{i.reason}{i.lpu_code && i.lpu_code !== "NO_REFERENCE" && i.lpu_code !== "SEM_REFERENCIA" ? ` · ${i.lpu_code}` : " · sem referência na LPU"}</div>
                    {i.findings.filter((a) => a.kind !== "out_of_scope_item" && a.kind !== "unjustified_replacement").map((a, k) => (
                      <div key={k} className="mt-1 text-[13px] text-warn">{findingLabel(a.kind)}: {a.evidence}</div>
                    ))}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{num(i.quantity)} {i.unit}</td>
                  <td className={`px-3 py-2.5 text-right tabular-nums ${above ? "font-semibold text-bad" : ""}`}>{brl(i.unit_value)}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-muted">{i.reference_price ? brl(i.reference_price) : "—"}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{brl(i.total_value)}</td>
                  <td className={`px-3 py-2.5 text-right tabular-nums ${i.amount_at_issue ? "font-semibold text-bad" : "text-muted"}`}>
                    {i.amount_at_issue ? brl(i.amount_at_issue) : "—"}
                    {i.amount_at_issue > 0 && i.amount_at_issue < i.total_value && <div className="text-[11px] font-normal text-muted">só o excedente</div>}
                  </td>
                  <td className="px-3 py-2.5"><span className={`whitespace-nowrap rounded-full px-2.5 py-0.5 text-[12px] font-semibold ${c.cls}`}>{c.label}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap gap-x-8 gap-y-1 text-sm">
        <span>Total orçado <b className="tabular-nums">{brl(p.items.reduce((s, i) => s + i.total_value, 0))}</b></span>
        <span>Valor potencial divergente <b className="tabular-nums text-bad">{brl(p.amount_at_issue)}</b> ({p.amount_at_issue_pct.toFixed(0)}%)</span>
        <span className="text-muted">Item fora do escopo, sem justificativa ou duplicado conta inteiro; preço e quantidade acima contam só o excedente.</span>
      </div>
      {p.quote_notes.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted">{p.quote_notes.map((o, k) => <li key={k}>{o}</li>)}</ul>
      )}
    </div>
  );
}

/** rola até o primeiro elemento destacado (vindo do clique num apontamento) */
function useScrollToHighlight(ids: string[]) {
  const key = ids.join("|");
  useEffect(() => {
    if (!key) return;
    const t = window.setTimeout(() => document.getElementById(key.split("|")[0])?.scrollIntoView({ block: "center", behavior: "smooth" }), 80);
    return () => window.clearTimeout(t);
  }, [key]);
}
