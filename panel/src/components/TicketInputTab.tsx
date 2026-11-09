import { FileSpreadsheet } from "lucide-react";
import type { TicketDetail } from "../api";
import { brl, num, envLabel, MAINTENANCE_LABEL, STAGE_LABEL, STAGE_DOCS } from "../format";
import { InfoTip } from "./ui/Tooltip";
import type { LightboxItem } from "./ui/Lightbox";

/** O que chegou do Salesforce: escopo, categoria, sintoma, planilha de orçamento e anexos. */
export function TicketInputTab({ ch, openPhoto }: { ch: TicketDetail; openPhoto: (items: LightboxItem[], index: number) => void }) {
  const spreadsheet = ch.attachments.find((a) => !a.is_image);
  const photos = ch.attachments.filter((a) => a.is_image);
  const gallery = photos.map((f) => ({ url: f.url, caption: `Anexo ${f.index}: ${f.name}` }));
  return (
    <div className="space-y-6">
      <section className="grid gap-4 md:grid-cols-[1fr_260px]">
        <figure className="rounded-xl border border-line bg-sheet p-5">
          <figcaption className="text-sm text-muted">Escopo descrito por quem abriu o chamado</figcaption>
          <blockquote className="mt-2 text-xl leading-snug">“{ch.scope}”</blockquote>
        </figure>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border border-line bg-sheet p-5 text-sm md:grid-cols-1">
          <div><dt className="text-muted">Categoria</dt><dd className="font-semibold">{ch.category_label}</dd></div>
          <div><dt className="text-muted">Sintoma</dt><dd className="font-semibold">{ch.symptom_label}</dd></div>
          <div><dt className="flex items-center gap-1 text-muted">Tipo de manutenção <InfoTip term="maintenance" size={12} /></dt><dd className="font-semibold">{MAINTENANCE_LABEL[ch.maintenance_type] ?? ch.maintenance_type}</dd></div>
          <div>
            <dt className="flex items-center gap-1 text-muted">Etapa da esteira <InfoTip term="stage" size={12} /></dt>
            <dd className="font-semibold">{STAGE_LABEL[ch.moment] ?? ch.moment}</dd>
            <dd className="mt-1 text-[12px] text-muted">Nesta etapa o fornecedor envia: {(STAGE_DOCS[ch.moment] ?? []).join(", ").toLowerCase()}.</dd>
          </div>
        </dl>
      </section>

      <dl className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
        <div><dt className="text-muted">Agência</dt><dd>{ch.branch}{ch.environment ? `, ${envLabel(ch.environment)}` : ""}</dd></div>
        <div><dt className="text-muted">Fornecedor</dt><dd>{ch.supplier}</dd></div>
        <div><dt className="text-muted">Abertura / envio</dt><dd className="tabular-nums">{fmtData(ch.dates.opening)} / {fmtData(ch.dates.supplier_submission)}</dd></div>
        <div><dt className="text-muted">Valor orçado</dt><dd className="font-semibold tabular-nums">{brl(ch.quoted_value)}</dd></div>
      </dl>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="font-semibold">Orçamento do fornecedor</h3>
          {spreadsheet && (
            <a href={spreadsheet.url} download className="flex items-center gap-1.5 text-sm text-blueprint hover:underline">
              <FileSpreadsheet size={16} /> Baixar {spreadsheet.name}
            </a>
          )}
        </div>
        {ch.quote ? (
          <div className="overflow-hidden rounded-xl border border-line bg-sheet">
            <table className="w-full text-sm">
              <thead className="bg-[#e7eef9] text-left text-[13px]">
                <tr>
                  <th className="px-3 py-2 font-semibold">Item</th><th className="px-3 py-2 font-semibold">Descrição</th>
                  <th className="px-3 py-2 font-semibold">Unidade</th><th className="px-3 py-2 text-right font-semibold">Quantidade</th>
                  <th className="px-3 py-2 text-right font-semibold">Valor unitário</th><th className="px-3 py-2 text-right font-semibold">Valor total</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {ch.quote.items.map((i) => (
                  <tr key={i.n} className="border-t border-line/70">
                    <td className="px-3 py-2">{i.n}</td><td className="px-3 py-2">{i.description}</td><td className="px-3 py-2">{i.unit}</td>
                    <td className="px-3 py-2 text-right">{num(i.quantity)}</td><td className="px-3 py-2 text-right">{brl(i.unit_value)}</td>
                    <td className="px-3 py-2 text-right">{brl(i.total_value)}</td>
                  </tr>
                ))}
                <tr className="border-t-2 border-ink/20 font-semibold">
                  <td colSpan={5} className="px-3 py-2 text-right">Total</td><td className="px-3 py-2 text-right">{brl(ch.quote.total_value)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        ) : (
          <p className="rounded-xl border border-bad/40 bg-sheet p-4 text-sm text-bad">Planilha não lida: {ch.quote_error}</p>
        )}
      </section>

      <section>
        <h3 className="mb-2 font-semibold">Fotos e documentos enviados ({photos.length}) <span className="text-sm font-normal text-muted">· clique para ampliar</span></h3>
        {!photos.length && <p className="rounded-xl border border-dashed border-line bg-sheet p-4 text-sm text-muted">Nenhuma foto enviada neste chamado.</p>}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
          {photos.map((f, idx) => (
            <button key={f.name} onClick={() => openPhoto(gallery, idx)} className="group overflow-hidden rounded-lg border border-line bg-sheet text-left">
              <img src={f.url} alt={f.name} loading="lazy" className="aspect-[4/3] w-full object-cover transition group-hover:opacity-90" />
              <span className="block truncate px-2 py-1.5 text-[12px] text-muted">Anexo {f.index}: {f.name}</span>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

export const fmtData = (d: string | null | undefined) => (d ? new Date(`${d}T12:00:00`).toLocaleDateString("pt-BR") : "—");
