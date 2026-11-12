import { Lock } from "lucide-react";
import { useEffect } from "react";
import type { Assessment } from "../api";
import { MOMENT_LABEL } from "../format";
import type { LightboxItem } from "./ui/Lightbox";
import { Tooltip } from "./ui/Tooltip";

const MATCH = {
  yes: { label: "Corresponde ao escopo", cls: "text-ok" },
  partial: { label: "Corresponde em parte", cls: "text-warn" },
  no: { label: "Não corresponde ao escopo", cls: "text-bad" },
  undetermined: { label: "Não dá para avaliar", cls: "text-muted" },
} as const;

export function PhotosTab({ p, base, openPhoto, highlight = [] }: { p: Assessment; base: string; openPhoto: (items: LightboxItem[], index: number) => void; highlight?: string[] }) {
  useScrollToHighlight(highlight.map((f) => `photo-${f}`));
  if (!p.photos.length) return <p className="text-muted">Nenhuma foto analisada neste chamado.</p>;
  // pareceres antigos gravaram has_done_service_photo (sim/não); os novos, done_service (yes/partial/no/undetermined)
  const summary = p.photo_summary as { has_before_photo: boolean; done_service?: keyof typeof MATCH; has_done_service_photo?: boolean; done_justification: string } | null;
  const done: keyof typeof MATCH = summary?.done_service ?? (summary?.has_done_service_photo ? "yes" : "no");
  const gallery = p.photos.map((f) => ({ url: `${base}/${encodeURIComponent(f.file)}`, caption: f.what_it_shows }));
  return (
    <div className="space-y-4">
      {summary && (
        <div className="flex flex-wrap gap-2 text-sm">
          <Seal ok={summary.has_before_photo} text="Foto do antes" />
          {p.moment === "execution" && (done === "yes" || done === "no"
            ? <Seal ok={done === "yes"} text="Prova do serviço concluído" />
            : <span className="rounded-full bg-[#fdf1dc] px-3 py-1 font-medium text-warn">Serviço aparece, local não confirmado</span>)}
          {done !== "yes" && p.moment === "execution" && <span className="text-muted">{summary.done_justification}</span>}
          {p.moment === "quote" && <span className="text-muted">Aprovação do orçamento: o serviço ainda não foi feito, então não se espera foto do depois.</span>}
        </div>
      )}
      <QuantityChecks p={p} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {p.photos.map((f, idx) => {
          const url = `${base}/${encodeURIComponent(f.file)}`;
          const problem = !f.readable || f.matches_scope === "no" || !!f.reused_from;
          const c = MATCH[f.matches_scope];
          return (
            <figure key={f.file} id={`photo-${f.file}`} className={`overflow-hidden rounded-xl border-2 bg-sheet ${highlight.includes(f.file) ? "destaque " : ""}${f.reused_from ? "border-lock" : problem ? "border-bad" : "border-line"}`}>
              <button onClick={() => openPhoto(gallery, idx)} aria-label={`Ampliar: ${f.what_it_shows}`} className="group relative block w-full overflow-hidden">
                <img src={url} alt={f.what_it_shows} loading="lazy" className="aspect-[4/3] w-full object-cover transition duration-300 group-hover:scale-[1.03]" />
                <span className="absolute left-2 top-2 rounded bg-ink/80 px-2 py-0.5 text-[12px] font-semibold capitalize text-white">{MOMENT_LABEL[f.moment] ?? f.moment}</span>
                {f.reused_from && (
                  <Tooltip className="absolute right-2 top-2 inline-flex" content={`Foto muito parecida com uma de outro chamado (${f.reused_from}). Isso aciona a trava de integridade.`}>
                    <span className="flex items-center gap-1 rounded bg-lock px-2 py-0.5 text-[12px] font-semibold text-white">
                      <Lock size={12} /> Reaproveitada
                    </span>
                  </Tooltip>
                )}
              </button>
              <figcaption className="space-y-1 p-3 text-sm">
                <div className="font-medium">{f.what_it_shows}</div>
                {f.environment && <div className="text-[13px] text-muted">Ambiente: {f.environment}</div>}
                <div className={`text-[13px] font-medium ${f.readable ? c.cls : "text-bad"}`}>{f.readable ? c.label : "Ilegível"}</div>
                {f.reason && f.reason !== "(simulado)" && <div className="text-[13px] text-muted">{f.reason}</div>}
                {f.integrity_signals.map((s, k) => <div key={k} className="text-[13px] text-lock">{s}</div>)}
                <div className="truncate pt-1 text-[11px] text-muted/80">{f.file}</div>
              </figcaption>
            </figure>
          );
        })}
      </div>
    </div>
  );
}

interface QuantityCheck { item: number; what_was_counted: string; per_photo: string; count_seen: number; estimated_quantity: number; reasoning: string }

/** Contagem somando as fotos (ex.: peças de piso quebradas) contra a quantidade cobrada em cada item. */
function QuantityChecks({ p }: { p: Assessment }) {
  const checks = ((p.photo_summary as { quantity_checks?: QuantityCheck[] } | null)?.quantity_checks ?? []).filter((c) => p.items.some((i) => i.n === c.item));
  if (!checks.length) return null;
  const flagged = new Set(p.findings.filter((f) => f.kind === "quantity_above_photos").map((f) => f.reference));
  return (
    <section className="rounded-xl border border-line bg-sheet p-4">
      <h3 className="font-semibold">Quantidade cobrada × o que as fotos mostram</h3>
      <p className="mb-2 text-[13px] text-muted">Contagem somando todas as fotos; o mesmo ponto em duas fotos conta uma vez.</p>
      <ul className="space-y-2 text-sm">
        {checks.map((c) => {
          const it = p.items.find((i) => i.n === c.item)!;
          const over = flagged.has(`item ${it.n}: ${it.description}`);
          return (
            <li key={c.item} className={`rounded-lg px-3 py-2 ${over ? "bg-[#fbefed]" : "bg-paper/60"}`}>
              <div className="flex flex-wrap items-baseline gap-x-2">
                <b>Item {it.n}. {it.description}</b>
                <span className={over ? "font-semibold text-bad" : "text-muted"}>
                  cobrado {it.quantity.toLocaleString("pt-BR")} {it.unit} · fotos: {c.count_seen.toLocaleString("pt-BR")} {c.what_was_counted}
                  {c.estimated_quantity > 0 ? ` ≈ ${c.estimated_quantity.toLocaleString("pt-BR", { maximumFractionDigits: 2 })} ${it.unit}` : " (não dá para estimar)"}
                </span>
              </div>
              <div className="text-[12px] text-muted">{c.per_photo}{c.reasoning ? ` · ${c.reasoning}` : ""}</div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Seal({ ok, text }: { ok: boolean; text: string }) {
  return (
    <span className={`rounded-full px-3 py-1 font-medium ${ok ? "bg-[#e3f2ea] text-ok" : "bg-[#f8e4e2] text-bad"}`}>
      {ok ? "Tem" : "Falta"}: {text.toLowerCase()}
    </span>
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
