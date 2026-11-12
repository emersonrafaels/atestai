import { ChevronDown, FileText, PenLine } from "lucide-react";
import type { Assessment, EvaluatedDocument } from "../api";
import { brl } from "../format";
import type { LightboxItem } from "./ui/Lightbox";
import { InfoBox } from "./ui/InfoBox";

const MATCH = {
  yes: { label: "Confere com o chamado", cls: "bg-[#e3f2ea] text-ok" },
  partial: { label: "Confere em parte", cls: "bg-[#fdf1dc] text-warn" },
  no: { label: "Não confere com o chamado", cls: "bg-[#f8e4e2] text-bad" },
  undetermined: { label: "Não dá para avaliar", cls: "bg-paper text-muted" },
} as const;
const LEGIBLE = { yes: "Legível", partial: "Legível em parte", no: "Ilegível", undetermined: "Não avaliado" } as const;
const KIND: Record<string, string> = {
  service_report: "Relatório de atendimento",
  completion_certificate: "Termo de conclusão",
  technical_report: "Laudo / relatório técnico",
  price_reference: "Referência de preço",
  invoice: "Nota fiscal / recibo",
  other: "Documento",
};
const isImage = (f: string) => /\.(jpe?g|png|webp)$/i.test(f);

/** Documentos anexados (foto ou PDF) lidos por OCR: transcrição, campos extraídos e conferência com o chamado. */
export function DocumentsTab({ p, base, openPhoto }: { p: Assessment; base: string; openPhoto: (items: LightboxItem[], index: number) => void }) {
  const docs = p.documents ?? [];
  if (!docs.length) return <p className="text-muted">Nenhum documento neste chamado (relatório, termo, laudo, nota ou print de preço).</p>;
  const gallery = docs.filter((d) => isImage(d.file)).map((d) => ({ url: `${base}/${encodeURIComponent(d.file)}`, caption: KIND[d.kind] ?? d.kind }));
  return (
    <div className="space-y-4">
      <InfoBox id="documentos-ocr">
        O Atest.AI lê (OCR) cada documento anexado, inclusive manuscrito ou em PDF, e confere o que ele diz com o chamado e o orçamento:
        data e horário, agência, problema, solução, assinatura e preços.
      </InfoBox>
      {docs.map((d) => <DocumentCard key={d.file} d={d} p={p} url={`${base}/${encodeURIComponent(d.file)}`}
        open={isImage(d.file) ? () => openPhoto(gallery, gallery.findIndex((g) => g.url.endsWith(encodeURIComponent(d.file)))) : undefined} />)}
    </div>
  );
}

function DocumentCard({ d, p, url, open }: { d: EvaluatedDocument; p: Assessment; url: string; open?: () => void }) {
  const m = MATCH[d.matches_ticket] ?? MATCH.undetermined;
  const fields: [string, string][] = [
    ["Emitido por", d.issuer], ["Data do atendimento", d.service_date],
    ["Horário", [d.start_time, d.end_time].filter(Boolean).join(" às ")], ["Agência", d.branch],
    ["Problema", d.problem], ["Solução", d.solution],
  ];
  const item = (n: number) => p.items.find((i) => i.n === n);
  return (
    <section className={`grid gap-4 rounded-xl border-2 bg-sheet p-4 md:grid-cols-[220px_1fr] ${d.matches_ticket === "no" || d.legible === "no" ? "border-bad" : "border-line"}`}>
      <div>
        {open ? (
          <button onClick={open} aria-label={`Ampliar ${d.file}`} className="block w-full overflow-hidden rounded-lg border border-line">
            <img src={url} alt={KIND[d.kind] ?? "Documento"} className="max-h-72 w-full object-contain transition-transform hover:scale-[1.02]" loading="lazy" />
          </button>
        ) : (
          <a href={url} target="_blank" rel="noreferrer" className="flex h-40 flex-col items-center justify-center gap-2 rounded-lg border border-line bg-paper text-blueprint hover:underline">
            <FileText size={28} /> Abrir PDF
          </a>
        )}
        <div className="mt-1 truncate text-[12px] text-muted" title={d.file}>{d.file}</div>
      </div>
      <div className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-semibold">{KIND[d.kind] ?? d.kind}</h3>
          <span className={`rounded-full px-2.5 py-0.5 text-[12px] font-semibold ${m.cls}`}>{m.label}</span>
          <span className="rounded-full bg-paper px-2.5 py-0.5 text-[12px] text-muted ring-1 ring-line">{LEGIBLE[d.legible] ?? d.legible}</span>
          {d.handwritten && <span className="flex items-center gap-1 rounded-full bg-paper px-2.5 py-0.5 text-[12px] text-muted ring-1 ring-line"><PenLine size={12} /> Manuscrito</span>}
          <span className="rounded-full bg-paper px-2.5 py-0.5 text-[12px] text-muted ring-1 ring-line">{d.has_signature ? "Com assinatura" : "Sem assinatura"}</span>
          {d.service_status && (
            <span title="O documento prova que o serviço já foi feito? Substantivo (“instalação de…”) e horário de atendimento não provam."
              className={`rounded-full px-2.5 py-0.5 text-[12px] ring-1 ring-line ${d.service_status === "yes" ? "bg-[#fdf1dc] text-warn" : "bg-paper text-muted"}`}>
              {d.service_status === "yes" ? "Diz que o serviço já foi feito" : d.service_status === "no" ? "Descreve o que será feito" : "Não dá para saber se já foi feito"}
            </span>
          )}
        </div>
        <dl className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
          {fields.filter(([, v]) => v).map(([k, v]) => (
            <div key={k} className={k === "Problema" || k === "Solução" ? "sm:col-span-2" : ""}><dt className="text-[12px] text-muted">{k}</dt><dd>{v}</dd></div>
          ))}
        </dl>
        {d.prices.length > 0 && (
          <div className="text-sm">
            <div className="text-[12px] text-muted">Preços no documento</div>
            <ul className="mt-1 space-y-1">
              {d.prices.map((x, k) => {
                const it = item(x.quote_item);
                const above = it && x.value > 0 && it.unit_value > x.value;
                const unsure = it && x.same_product && x.same_product !== "yes";
                return (
                  <li key={k} className="flex flex-wrap items-baseline gap-x-2">
                    <span>{x.description}: <b className="tabular-nums">{brl(x.value)}</b></span>
                    {it && (
                      <span className={`text-[13px] ${above ? "text-bad" : "text-muted"}`}>
                        item {it.n} cobrado a {brl(it.unit_value)}{above ? ` (${Math.round(100 * (it.unit_value / x.value - 1))}% acima)` : ""}{unsure ? (x.same_product === "no" ? " · outro produto, não comparado" : " · produto não confirmado") : ""}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
        {d.divergences.length > 0 && (
          <div className="rounded-lg bg-[#fbefed] px-3 py-2 text-sm">
            <div className="text-[12px] font-semibold text-bad">Divergências</div>
            <ul className="mt-0.5 list-disc pl-5">{d.divergences.map((x, k) => <li key={k}>{x}</li>)}</ul>
          </div>
        )}
        {d.reason && <p className="text-[13px] text-muted">{d.reason}</p>}
        {d.transcription && (
          <details className="group rounded-lg border border-line">
            <summary className="flex cursor-pointer list-none items-center gap-1.5 px-3 py-2 text-sm font-medium">
              <ChevronDown size={15} className="text-muted transition group-open:rotate-180" /> Transcrição (OCR)
            </summary>
            <pre className="whitespace-pre-wrap border-t border-line px-3 py-2 font-sans text-[13px] leading-relaxed">{d.transcription}</pre>
          </details>
        )}
      </div>
    </section>
  );
}
