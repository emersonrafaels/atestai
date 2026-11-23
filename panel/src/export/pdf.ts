/**
 * Relatório do chamado e do parecer em PDF (arquivo baixado direto, texto selecionável), com as fotos e os documentos
 * em imagem. Mesmo conteúdo do relatório HTML (report.ts). O pdfmake só é carregado na hora de exportar.
 */
import type { Content, TableCell, TDocumentDefinitions, TVirtualFileSystem } from "pdfmake/interfaces";
import type { Assessment, TicketDetail } from "../api";
import {
  REC, SEVERITY, STAGE_LABEL, MAINTENANCE_LABEL, CONFIDENCE_LABEL, VALIDATION_LABEL,
  brl, brl4, num, branchLabel, envLabel, findingLabel, lpuNote, lpuReadable,
} from "../format";
import { CLASS_LABEL, COVERED, INK, LINE, MATCH, MUTED, PAPER, SEV_HEX, collectImages, day, isPdf } from "./report";

const WIDTH = 523; // A4 (595 pt) menos as margens laterais
const BLUE = "#2450b8", BAD = "#c62f2f";

const h2 = (text: string): Content => ({
  stack: [
    { text, style: "h2" },
    { canvas: [{ type: "line", x1: 0, y1: 2, x2: WIDTH, y2: 2, lineWidth: 0.6, lineColor: LINE }] },
  ],
  margin: [0, 16, 0, 6],
});

/** Caixa com faixa colorida à esquerda (veredito, observações). */
const box = (stack: Content[], color: string, fill: string): Content => ({
  table: { widths: ["*"], body: [[{ stack, fillColor: fill }]] },
  layout: {
    hLineWidth: () => 0,
    vLineWidth: (i: number) => (i === 0 ? 4 : 0),
    vLineColor: () => color,
    paddingLeft: () => 12, paddingRight: () => 12, paddingTop: () => 9, paddingBottom: () => 9,
  },
  margin: [0, 4, 0, 4],
});

/** Tabela com linhas finas entre as linhas e cabeçalho cinza que se repete a cada página. */
const grid = (widths: (string | number)[], head: string[], rows: TableCell[][], right: number[] = []): Content => ({
  table: {
    headerRows: 1,
    dontBreakRows: true,
    widths,
    body: [
      head.map((h, i) => ({ text: h, style: "th", alignment: right.includes(i) ? "right" : "left" })),
      ...rows,
    ],
  },
  layout: {
    hLineWidth: (i: number) => (i === 0 ? 0 : 0.5),
    vLineWidth: () => 0,
    hLineColor: () => LINE,
    fillColor: (row: number) => (row === 0 ? PAPER : null),
    paddingTop: () => 4, paddingBottom: () => 4, paddingLeft: () => 5, paddingRight: () => 5,
  },
  fontSize: 8.5,
});

const muted = (text: string): Content => ({ text, color: MUTED, fontSize: 8 });

/** Monta a definição do documento (separado do download para poder testar e reaproveitar). */
export async function pdfDefinition(p: Assessment, ticket: TicketDetail | null, images?: Map<string, string>): Promise<TDocumentDefinitions> {
  p = lpuReadable(p); // código da LPU → "Nome (CÓDIGO)" nos textos: no papel não há hover
  const img = images ?? (await collectImages(p, ticket));
  const rec = REC[p.recommendation];
  const branch = p.branch ?? (ticket ? { code: ticket.branch_code ?? "", name: ticket.branch_name ?? "", environment: ticket.environment } : null);
  const total = p.items.reduce((s, i) => s + i.total_value, 0);
  const out: Content[] = [];

  // ---- cabeçalho do chamado
  out.push({ text: "ATEST.AI · PRÉ-ANÁLISE DE CHAMADO", color: MUTED, fontSize: 7.5, characterSpacing: 0.6 });
  out.push({ text: `Chamado ${p.ticket_id}`, fontSize: 20, bold: true, margin: [0, 2, 0, 8] });
  const facts: [string, string][] = [
    ["ESTEIRA", `${p.workstream} · ${MAINTENANCE_LABEL[p.maintenance_type] ?? p.maintenance_type}`],
    ["ETAPA", STAGE_LABEL[p.moment] ?? p.moment],
    ["AGÊNCIA", branchLabel(branch)],
    ["LOCAL", envLabel(branch?.environment ?? ticket?.environment) || "—"],
    ["FORNECEDOR", p.supplier || ticket?.supplier || "—"],
    ["CATEGORIA", ticket ? `${ticket.category_label} — ${ticket.symptom_label}` : p.category],
    ["ABERTURA / ENVIO", ticket ? `${day(ticket.dates?.opening)} · ${day(ticket.dates?.supplier_submission)}` : "—"],
    ["VALOR ORÇADO", p.quoted_value !== null ? brl(p.quoted_value) : brl(total)],
  ];
  const cell = ([k, v]: [string, string]): TableCell => ({ stack: [{ text: k, color: MUTED, fontSize: 6.5 }, { text: v, bold: true }], margin: [0, 0, 6, 4] });
  out.push({ table: { widths: ["*", "*", "*", "*"], body: [facts.slice(0, 4).map(cell), facts.slice(4).map(cell)] }, layout: "noBorders" });

  // ---- veredito
  const scoreLine: Content[] = [p.score !== null ? { text: [`Score `, { text: String(p.score), bold: true }] } : "Sem score"];
  if (p.confidence) scoreLine.push({ text: [" · confiança ", { text: CONFIDENCE_LABEL[p.confidence], bold: true }] });
  if (p.amount_at_issue > 0) scoreLine.push({ text: [" · valor potencial divergente ", { text: brl(p.amount_at_issue), bold: true, color: BAD }, ` (${p.amount_at_issue_pct.toFixed(0)}%)`] });
  out.push({
    ...(box([
      { text: rec.label, fontSize: 16, bold: true, color: rec.mark },
      { text: scoreLine, margin: [0, 2, 0, 0] },
      { text: `Por quê: ${p.recommendation_reason}`, color: MUTED, margin: [0, 3, 0, 0] },
      ...(p.summary ? [{ text: p.summary, fontSize: 10, margin: [0, 6, 0, 0] } as Content] : []),
    ], rec.mark, "#fbfcfd") as object),
    unbreakable: true,
    margin: [0, 10, 0, 0],
  } as Content);

  // ---- pedido
  const scope = p.requested_scope ?? ticket?.scope;
  if (scope) {
    out.push(h2("Pedido do chamado"));
    out.push({ table: { widths: ["*"], body: [[{ text: scope, fillColor: PAPER, margin: [6, 4, 6, 4] }]] }, layout: "noBorders" });
    if (ticket?.solution_description) out.push({ text: [{ text: "Solução descrita: ", bold: true }, ticket.solution_description], margin: [0, 6, 0, 0] });
  }

  // ---- apontamentos
  out.push(h2("Apontamentos"));
  out.push(p.findings.length
    ? grid([118, 46, "*", 40, 54], ["Apontamento", "Severidade", "Evidência", "Desconto", "Divergente"],
      p.findings.map((f) => [
        { stack: [{ text: findingLabel(f.kind) + (f.lock ? " (trava)" : "") + (f.absorbed_by ? " (absorvido)" : ""), bold: true }, muted(`${VALIDATION_LABEL[f.validation]}${f.reference ? ` · ${f.reference}` : ""}`)] },
        { text: SEVERITY[f.severity]?.label ?? f.severity, bold: true, color: SEV_HEX[f.severity] },
        { text: f.evidence },
        { text: f.discount ? `−${f.discount}` : "—", alignment: "right" },
        { text: f.amount_at_issue ? brl(f.amount_at_issue) : "—", alignment: "right" },
      ]), [3, 4])
    : muted("Nenhum apontamento."));

  // ---- orçamento
  out.push(h2("Orçamento"));
  const notes = p.quote_notes.filter(Boolean);
  if (notes.length) {
    out.push(box([{ text: "Observações da conferência do orçamento", bold: true, margin: [0, 0, 0, 3] }, { ul: notes, fontSize: 9 }], BLUE, "#f3f6fd"));
  }
  if (p.items.length) {
    out.push(grid([14, "*", 40, 50, 50, 52, 52, 56], ["#", "Item", "Qtd", "Unitário", "LPU", "Total", "Divergente", "Classificação"], [
      ...p.items.map((i): TableCell[] => [
        String(i.n),
        { stack: [{ text: i.description, bold: true }, muted(`${i.reason}${lpuNote(i)}`)] },
        { text: `${num(i.quantity)} ${i.unit}`, alignment: "right" },
        { text: brl(i.unit_value), alignment: "right" },
        { text: i.reference_price ? brl(i.reference_price) : i.similar_lpu ? `${brl(i.similar_lpu.reference_price)} (similar)` : "—", alignment: "right" },
        { text: brl(i.total_value), alignment: "right" },
        { text: i.amount_at_issue ? brl(i.amount_at_issue) : "—", alignment: "right", color: i.amount_at_issue ? BAD : INK },
        CLASS_LABEL[i.classification] ?? i.classification,
      ]),
      ["", { text: "Total orçado", bold: true }, "", "", "", { text: brl(total), bold: true, alignment: "right" },
        { text: p.amount_at_issue ? brl(p.amount_at_issue) : "—", bold: true, alignment: "right", color: BAD }, ""],
    ], [2, 3, 4, 5, 6]));
    const cov = p.service_coverage ?? [];
    if (cov.length) {
      out.push({ text: "Serviços pedidos × itens do orçamento", bold: true, margin: [0, 10, 0, 3] });
      out.push({ ul: cov.map((c) => ({ text: [{ text: `${COVERED[c.covered] ?? c.covered}: `, bold: true }, c.service, c.items.length ? ` · ${c.items.length > 1 ? "itens" : "item"} ${c.items.join(", ")}` : "", c.note ? { text: `\n${c.note}`, color: MUTED, fontSize: 8 } : ""] })) });
    }
  } else {
    out.push(muted("O orçamento não foi conferido neste chamado."));
  }

  // ---- fotos (3 por linha)
  if (p.photos.length) {
    out.push(h2(`Fotos (${p.photos.length})`));
    const problem = p.photo_summary?.problem_assessment;
    if (typeof problem === "string" && problem) out.push({ text: problem, margin: [0, 0, 0, 6] });
    const cells: TableCell[] = p.photos.map((ph) => ({
      unbreakable: true,
      stack: [
        img.get(ph.file) ? { image: img.get(ph.file)!, fit: [165, 124], alignment: "center" } : { text: ph.file, color: MUTED, alignment: "center", margin: [0, 50, 0, 50] },
        { text: [{ text: ph.file, bold: true }, ph.exif_date ? ` · ${day(ph.exif_date)}` : ""], fontSize: 7.5, margin: [0, 3, 0, 0] },
        { text: ph.what_it_shows, fontSize: 7.5 },
        { text: [`Corresponde ao escopo: ${MATCH[ph.matches_scope] ?? ph.matches_scope}`, ph.reused_from ? { text: ` · reaproveitada de ${ph.reused_from}`, color: BAD, bold: true } : ""], fontSize: 7, color: MUTED },
      ],
      margin: [0, 0, 0, 8],
    }));
    while (cells.length % 3) cells.push("");
    const rows: TableCell[][] = [];
    for (let k = 0; k < cells.length; k += 3) rows.push(cells.slice(k, k + 3));
    out.push({ table: { widths: ["*", "*", "*"], body: rows, dontBreakRows: true }, layout: { defaultBorder: false, paddingLeft: () => 3, paddingRight: () => 3 } });
  }

  // ---- documentos (imagem grande, para continuar legível)
  const docs = p.documents ?? [];
  if (docs.length) {
    out.push(h2(`Documentos (${docs.length})`));
    for (const d of docs) {
      const parts: Content[] = [
        { text: [{ text: d.file, bold: true }, { text: ` · legível: ${MATCH[d.legible]} · confere com o chamado: ${MATCH[d.matches_ticket]}`, color: MUTED }] },
      ];
      if (img.get(d.file)) parts.push({ image: img.get(d.file)!, fit: [WIDTH, 360], alignment: "center", margin: [0, 6, 0, 6] });
      else if (isPdf(d.file, ticket)) parts.push(muted(`Documento em PDF: veja o anexo ${d.file} no chamado.`));
      if (d.problem) parts.push({ text: [{ text: "Problema: ", bold: true }, d.problem] });
      if (d.solution) parts.push({ text: [{ text: "Solução: ", bold: true }, d.solution] });
      if (d.prices.length) parts.push({ text: [{ text: "Preços citados: ", bold: true }, d.prices.map((x) => `${x.description} ${brl(x.value)}${x.quote_item ? ` (item ${x.quote_item})` : ""}`).join("; ")] });
      if (d.divergences.length) parts.push({ ul: [...d.divergences], margin: [0, 2, 0, 0] });
      out.push({ stack: parts, unbreakable: true, margin: [0, 4, 0, 10] });
    }
  }

  // ---- chamados da agência
  const related = (p.related?.tickets ?? []).filter((r) => r.flagged || r.probability >= (p.related?.show_probability ?? 40));
  if (related.length) {
    out.push(h2("Chamados da mesma agência"));
    for (const r of related) {
      out.push({
        stack: [
          { text: [{ text: r.ticket_id, bold: true }, r.flagged ? { text: "  possível duplicado", color: BAD, bold: true } : "", { text: ` · aberto em ${day(r.opening)} · ${r.category_label} · chance ${r.probability}%`, color: MUTED }] },
          { text: r.reason },
        ],
        margin: [0, 0, 0, 6],
      });
    }
  }

  // ---- mensagem ao fornecedor
  if (p.supplier_message) {
    out.push(h2("Mensagem sugerida ao fornecedor"));
    out.push({ table: { widths: ["*"], body: [[{ text: p.supplier_message, fillColor: PAPER, margin: [6, 4, 6, 4] }]] }, layout: "noBorders" });
  }

  out.push({
    text: [
      `Gerado pelo Atest.AI em ${new Date().toLocaleString("pt-BR")} · parecer de ${new Date(p.generated_at).toLocaleString("pt-BR")} · régua ${p.rubric_version} · prompts ${p.prompts_version} · modo ${p.mode === "api" ? `API (${brl4(p.cost_brl)})` : "simulado"}\n`,
      "Este documento é uma recomendação: a decisão final é da pessoa analista.",
    ],
    color: MUTED, fontSize: 7.5, margin: [0, 18, 0, 0],
  });

  return {
    pageSize: "A4",
    pageMargins: [36, 36, 36, 40],
    info: { title: `Parecer do chamado ${p.ticket_id}`, author: "Atest.AI", subject: "Pré-análise de chamado de manutenção" },
    defaultStyle: { font: "Roboto", fontSize: 9, color: INK, lineHeight: 1.2 },
    styles: { h2: { fontSize: 12, bold: true }, th: { bold: true, color: MUTED, fontSize: 8 } },
    content: out,
    footer: (page: number, pages: number) => ({
      columns: [
        { text: `Atest.AI · chamado ${p.ticket_id}`, color: MUTED, fontSize: 7 },
        { text: `página ${page} de ${pages}`, color: MUTED, fontSize: 7, alignment: "right" },
      ],
      margin: [36, 14, 36, 0],
    }),
  };
}

/** Gera o PDF e baixa o arquivo `parecer_<nº>.pdf`. */
export async function downloadPdf(p: Assessment, ticket: TicketDetail | null): Promise<void> {
  // o pdfmake altera no próprio lugar as listas que recebe (cada texto de um `ul` vira objeto): ele trabalha sobre uma
  // cópia, para o parecer da tela (e o HTML exportado depois) continuar intacto
  const [doc, pm, fonts] = await Promise.all([
    pdfDefinition(structuredClone(p), ticket && structuredClone(ticket)),
    import("pdfmake/build/pdfmake"),
    import("pdfmake/build/vfs_fonts"),
  ]);
  // o build do pdfmake é UMD: o objeto vem em `default` (ou no próprio módulo, conforme o empacotador)
  const pdfMake = ((pm as unknown as { default?: typeof pm }).default ?? pm) as typeof pm;
  const vfs = ((fonts as { default?: TVirtualFileSystem }).default ?? fonts) as TVirtualFileSystem;
  pdfMake.addVirtualFileSystem(vfs);
  await pdfMake.createPdf(doc).download(`parecer_${p.ticket_id}.pdf`);
}
