/**
 * Relatório do chamado e do parecer para compartilhar: um HTML autocontido (CSS e fotos embutidos), que abre em
 * qualquer navegador e imprime bem em A4. O PDF sai da impressão do navegador ("Salvar como PDF").
 */
import type { Assessment, Finding, TicketDetail } from "../api";
import {
  REC, SEVERITY, STAGE_LABEL, MAINTENANCE_LABEL, CONFIDENCE_LABEL, VALIDATION_LABEL,
  brl, brl4, num, branchLabel, envLabel, findingLabel, lpuNote, lpuReadable,
} from "../format";

const esc = (s: unknown) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
export const day = (d?: string | null) => (d ? d.slice(0, 10).split("-").reverse().join("/") : "—");

// cores fixas (o relatório não tem as variáveis do painel)
export const INK = "#12233f", MUTED = "#5e6b7e", LINE = "#dfe3ea", PAPER = "#f6f7f9";
export const SEV_HEX: Record<string, string> = { critical: "#6250d6", high: "#c62f2f", medium: "#b26a00", low: "#5e6b7e" };
export const CLASS_LABEL: Record<string, string> = { compliant: "Aderente", out_of_scope: "Fora do escopo", to_justify: "Sem justificativa" };
export const COVERED: Record<string, string> = { yes: "Coberto", partial: "Só em parte", no: "Sem item", undetermined: "Não conferido" };
export const MATCH: Record<string, string> = { yes: "sim", partial: "em parte", no: "não", undetermined: "indeterminado" };

/** Imagem do anexo reduzida (lado maior ≤ max px) em JPEG, como data URI; null se não carregar. */
async function shrink(url: string, max = 900, quality = 0.78): Promise<string | null> {
  try {
    const blob = await (await fetch(url)).blob();
    const bmp = await createImageBitmap(blob);
    const k = Math.min(1, max / Math.max(bmp.width, bmp.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bmp.width * k);
    canvas.height = Math.round(bmp.height * k);
    canvas.getContext("2d")!.drawImage(bmp, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", quality);
  } catch {
    return null;
  }
}

/**
 * Imagens do chamado embutidas, pelo nome do arquivo (o parecer cita fotos e documentos pelo nome). Documentos (foto de
 * relatório, termo, print de preço) saem maiores e mais nítidos, para o texto continuar legível.
 */
export async function collectImages(p: Assessment, ticket: TicketDetail | null): Promise<Map<string, string>> {
  const out = new Map<string, string>();
  const docs = new Set((p.documents ?? []).map((d) => d.file));
  const images = (ticket?.attachments ?? []).filter((a) => a.is_image);
  const shots = await Promise.all(images.map((a) => (docs.has(a.name) ? shrink(a.url, 1400, 0.85) : shrink(a.url))));
  images.forEach((a, i) => { if (shots[i]) out.set(a.name, shots[i]!); });
  return out;
}

/** Documento anexado em PDF (não dá para embutir a página; o relatório cita o arquivo). */
export const isPdf = (name: string, ticket: TicketDetail | null) =>
  /\.pdf$/i.test(name) || (ticket?.attachments ?? []).some((a) => a.name === name && a.content_type === "application/pdf");

const section = (title: string, body: string, sub = "") =>
  body ? `<section><h2>${esc(title)}</h2>${sub ? `<p class="sub">${esc(sub)}</p>` : ""}${body}</section>` : "";

function findingRow(f: Finding): string {
  const sev = SEVERITY[f.severity];
  return `<tr>
    <td><b>${esc(findingLabel(f.kind))}</b>${f.lock ? ' <span class="tag lock">trava</span>' : ""}${f.absorbed_by ? ' <span class="tag">absorvido</span>' : ""}
      <div class="muted">${esc(VALIDATION_LABEL[f.validation])}${f.reference ? ` · ${esc(f.reference)}` : ""}</div></td>
    <td><span class="sev" style="color:${SEV_HEX[f.severity]}">${esc(sev?.label ?? f.severity)}</span></td>
    <td>${esc(f.evidence)}</td>
    <td class="num">${f.discount ? `−${f.discount}` : "—"}</td>
    <td class="num">${f.amount_at_issue ? brl(f.amount_at_issue) : "—"}</td>
  </tr>`;
}

/**
 * Monta o relatório.
 *
 * @param p parecer exibido no painel.
 * @param ticket detalhe do chamado (datas, anexos); sem ele o relatório sai sem fotos e com menos dados de entrada.
 * @returns HTML completo (documento), pronto para baixar ou imprimir.
 */
export async function buildReport(p: Assessment, ticket: TicketDetail | null, images?: Map<string, string>): Promise<string> {
  p = lpuReadable(p); // código da LPU → "Nome (CÓDIGO)" nos textos: no documento não há hover
  const photos = images ?? (await collectImages(p, ticket));
  const rec = REC[p.recommendation];
  const branch = p.branch ?? (ticket ? { code: ticket.branch_code ?? "", name: ticket.branch_name ?? "", environment: ticket.environment } : null);
  const place = envLabel(branch?.environment ?? ticket?.environment);
  const total = p.items.reduce((s, i) => s + i.total_value, 0);

  const facts: [string, string][] = [
    ["Esteira", `${p.workstream} · ${MAINTENANCE_LABEL[p.maintenance_type] ?? p.maintenance_type}`],
    ["Etapa", STAGE_LABEL[p.moment] ?? p.moment],
    ["Agência", branchLabel(branch)],
    ["Local", place || "—"],
    ["Fornecedor", p.supplier || ticket?.supplier || "—"],
    ["Categoria", ticket ? `${ticket.category_label} — ${ticket.symptom_label}` : p.category],
    ["Abertura / envio", ticket ? `${day(ticket.dates?.opening)} · ${day(ticket.dates?.supplier_submission)}` : "—"],
    ["Valor orçado", p.quoted_value !== null ? brl(p.quoted_value) : brl(total)],
  ];

  const header = `<header>
    <div class="brand">Atest.AI · pré-análise de chamado</div>
    <h1>Chamado ${esc(p.ticket_id)}</h1>
    <dl class="facts">${facts.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>
  </header>`;

  const verdict = `<section class="verdict" style="border-left-color:${rec.mark}">
    <div class="rec" style="color:${rec.mark}">${esc(rec.label)}</div>
    <div class="score">${p.score !== null ? `Score <b>${p.score}</b>` : "Sem score"}${p.confidence ? ` · confiança <b>${esc(CONFIDENCE_LABEL[p.confidence])}</b>` : ""}${p.amount_at_issue > 0 ? ` · valor potencial divergente <b class="bad">${brl(p.amount_at_issue)}</b> (${p.amount_at_issue_pct.toFixed(0)}%)` : ""}</div>
    <p class="why">Por quê: ${esc(p.recommendation_reason)}</p>
    ${p.summary ? `<p class="summary">${esc(p.summary)}</p>` : ""}
  </section>`;

  const scope = (p.requested_scope ?? ticket?.scope) ? section("Pedido do chamado", `<blockquote>${esc(p.requested_scope ?? ticket?.scope)}</blockquote>${ticket?.solution_description ? `<p><b>Solução descrita:</b> ${esc(ticket.solution_description)}</p>` : ""}`) : "";

  const findings = p.findings.length
    ? `<table><thead><tr><th>Apontamento</th><th>Severidade</th><th>Evidência</th><th class="num">Desconto</th><th class="num">Divergente</th></tr></thead><tbody>${p.findings.map(findingRow).join("")}</tbody></table>`
    : `<p class="muted">Nenhum apontamento.</p>`;

  const notes = p.quote_notes.filter(Boolean).length ? `<div class="notes"><h3>Observações da conferência do orçamento</h3><ul>${p.quote_notes.filter(Boolean).map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>` : "";
  const coverage = (p.service_coverage ?? []).length
    ? `<h3>Serviços pedidos × itens do orçamento</h3><ul class="cov">${p.service_coverage!.map((c) => `<li><span class="tag">${esc(COVERED[c.covered] ?? c.covered)}</span> <b>${esc(c.service)}</b>${c.items.length ? ` · ${c.items.length > 1 ? "itens" : "item"} ${c.items.join(", ")}` : ""}${c.note ? `<div class="muted">${esc(c.note)}</div>` : ""}</li>`).join("")}</ul>`
    : "";
  const quote = p.items.length
    ? `${notes}<table><thead><tr><th>#</th><th>Item</th><th class="num">Qtd</th><th class="num">Unitário</th><th class="num">LPU</th><th class="num">Total</th><th class="num">Divergente</th><th>Classificação</th></tr></thead><tbody>${p.items.map((i) => `<tr>
        <td>${i.n}</td><td><b>${esc(i.description)}</b><div class="muted">${esc(i.reason)}${esc(lpuNote(i))}</div></td>
        <td class="num">${num(i.quantity)} ${esc(i.unit)}</td><td class="num">${brl(i.unit_value)}</td>
        <td class="num">${i.reference_price ? brl(i.reference_price) : i.similar_lpu ? `${brl(i.similar_lpu.reference_price)}<div class="muted">similar ${esc(i.similar_lpu.code)}</div>` : "—"}</td><td class="num">${brl(i.total_value)}</td>
        <td class="num ${i.amount_at_issue ? "bad" : ""}">${i.amount_at_issue ? brl(i.amount_at_issue) : "—"}</td><td>${esc(CLASS_LABEL[i.classification] ?? i.classification)}</td></tr>`).join("")}
        <tr class="total"><td></td><td>Total orçado</td><td></td><td></td><td></td><td class="num">${brl(total)}</td><td class="num bad">${p.amount_at_issue ? brl(p.amount_at_issue) : "—"}</td><td></td></tr></tbody></table>${coverage}`
    : `<p class="muted">O orçamento não foi conferido neste chamado.</p>`;

  const photoCards = p.photos.map((ph) => {
    const src = photos.get(ph.file);
    return `<figure>${src ? `<img src="${src}" alt="${esc(ph.file)}">` : `<div class="noimg">${esc(ph.file)}</div>`}
      <figcaption><b>${esc(ph.file)}</b>${ph.exif_date ? ` · ${esc(day(ph.exif_date))}` : ""}<br>${esc(ph.what_it_shows)}
      <div class="muted">Corresponde ao escopo: ${esc(MATCH[ph.matches_scope] ?? ph.matches_scope)}${ph.reused_from ? ` · <b class="bad">reaproveitada de ${esc(ph.reused_from)}</b>` : ""}</div></figcaption></figure>`;
  }).join("");
  const problem = typeof p.photo_summary?.problem_assessment === "string" ? `<p>${esc(p.photo_summary.problem_assessment)}</p>` : "";

  const docs = (p.documents ?? []).map((d) => `<div class="doc"><b>${esc(d.file)}</b> <span class="muted">· legível: ${esc(MATCH[d.legible])} · confere com o chamado: ${esc(MATCH[d.matches_ticket])}</span>
      ${photos.get(d.file) ? `<img class="docimg" src="${photos.get(d.file)}" alt="${esc(d.file)}">` : isPdf(d.file, ticket) ? `<div class="muted">Documento em PDF: veja o anexo ${esc(d.file)} no chamado.</div>` : ""}
      ${d.problem ? `<div>Problema: ${esc(d.problem)}</div>` : ""}${d.solution ? `<div>Solução: ${esc(d.solution)}</div>` : ""}
      ${d.prices.length ? `<div>Preços citados: ${d.prices.map((x) => `${esc(x.description)} ${brl(x.value)}${x.quote_item ? ` (item ${x.quote_item})` : ""}`).join("; ")}</div>` : ""}
      ${d.divergences.length ? `<ul>${d.divergences.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div>`).join("");

  const related = (p.related?.tickets ?? []).filter((r) => r.flagged || r.probability >= (p.related?.show_probability ?? 40));
  const relatedHtml = related.map((r) => `<div class="doc"><b>${esc(r.ticket_id)}</b>${r.flagged ? ' <span class="tag lock">possível duplicado</span>' : ""} <span class="muted">· aberto em ${esc(day(r.opening))} · ${esc(r.category_label)} · chance ${r.probability}%</span><div>${esc(r.reason)}</div></div>`).join("");

  const message = p.supplier_message ? `<blockquote class="msg">${esc(p.supplier_message)}</blockquote>` : "";

  const body = [
    header,
    verdict,
    scope,
    section("Apontamentos", findings),
    section("Orçamento", quote),
    section("Fotos", problem + (photoCards ? `<div class="grid">${photoCards}</div>` : ""), p.photos.length ? `${p.photos.length} foto(s) analisada(s)` : ""),
    section("Documentos", docs),
    section("Chamados da mesma agência", relatedHtml),
    section("Mensagem sugerida ao fornecedor", message),
  ].join("\n");

  const generated = new Date().toLocaleString("pt-BR");
  return `<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Parecer do chamado ${esc(p.ticket_id)}</title>
<style>
  *{box-sizing:border-box} body{margin:0;background:${PAPER};color:${INK};font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  main{max-width:980px;margin:24px auto;background:#fff;padding:32px 36px;border:1px solid ${LINE};border-radius:12px}
  .brand{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:${MUTED}} h1{font-size:26px;margin:2px 0 12px}
  h2{font-size:17px;margin:0 0 8px;padding-bottom:4px;border-bottom:1px solid ${LINE}} h3{font-size:14px;margin:14px 0 6px}
  section{margin-top:22px;break-inside:auto} .sub,.muted{color:${MUTED};font-size:12.5px} .bad{color:#c62f2f}
  .facts{display:grid;grid-template-columns:repeat(4,1fr);gap:8px 16px;margin:0} .facts dt{font-size:11px;color:${MUTED};text-transform:uppercase;letter-spacing:.04em} .facts dd{margin:0;font-weight:600}
  .verdict{border:1px solid ${LINE};border-left:5px solid;border-radius:10px;padding:14px 16px;background:#fbfcfd;break-inside:avoid}
  .rec{font-size:22px;font-weight:800} .why{margin:6px 0 0;color:${MUTED}} .summary{margin:10px 0 0;font-size:15px}
  blockquote{margin:0;padding:10px 14px;background:${PAPER};border-radius:8px} .msg{white-space:pre-line}
  table{width:100%;border-collapse:collapse;font-size:12.5px} th{text-align:left;color:${MUTED};font-weight:600;background:${PAPER}} th,td{padding:6px 8px;border-top:1px solid ${LINE};vertical-align:top}
  tr{break-inside:avoid} .num{text-align:right;white-space:nowrap} .total td{font-weight:700}
  .sev{font-weight:700} .tag{display:inline-block;padding:0 6px;border-radius:999px;background:${PAPER};font-size:11px;font-weight:600} .tag.lock{background:#fbefed;color:#c62f2f}
  .notes{border-left:4px solid #2450b8;background:#f3f6fd;padding:8px 14px;border-radius:8px;margin-bottom:10px} .notes h3{margin:0 0 4px} .notes ul{margin:0;padding-left:18px}
  .cov{list-style:none;padding:0;margin:0} .cov li{margin:4px 0}
  .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px} figure{margin:0;border:1px solid ${LINE};border-radius:8px;overflow:hidden;break-inside:avoid}
  figure img{display:block;width:100%;height:170px;object-fit:cover} .noimg{height:170px;display:flex;align-items:center;justify-content:center;background:${PAPER};color:${MUTED};font-size:12px}
  figcaption{padding:6px 8px;font-size:12px} .doc{padding:8px 0;border-top:1px solid ${LINE};font-size:13px} .doc ul{margin:4px 0 0;padding-left:18px}
  .docimg{display:block;max-width:100%;max-height:520px;margin:8px 0;border:1px solid ${LINE};border-radius:6px;break-inside:avoid}
  footer{margin-top:26px;padding-top:10px;border-top:1px solid ${LINE};font-size:11.5px;color:${MUTED}}
  @page{size:A4;margin:14mm} @media print{body{background:#fff} main{margin:0;padding:0;border:0;max-width:none} .grid{grid-template-columns:repeat(3,1fr)}}
  @media (max-width:700px){.facts{grid-template-columns:repeat(2,1fr)} .grid{grid-template-columns:1fr 1fr} main{padding:20px}}
</style></head>
<body><main>
${body}
<footer>Gerado pelo Atest.AI em ${esc(generated)} · parecer de ${esc(new Date(p.generated_at).toLocaleString("pt-BR"))} · régua ${esc(p.rubric_version)} · prompts ${esc(p.prompts_version)} · modo ${p.mode === "api" ? `API (${brl4(p.cost_brl)})` : "simulado"}<br>
Este documento é uma recomendação: a decisão final é da pessoa analista.</footer>
</main></body></html>`;
}

/** Baixa um texto como arquivo. */
export function download(content: string, name: string, type: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([content], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
