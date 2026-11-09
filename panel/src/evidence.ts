import type { Assessment, EvaluatedItem, EvaluatedPhoto, Finding, Recommendation, RubricInfo, ValidationKind } from "./api";
import { VALIDATIONS, explainFindings } from "./format";

// ============================================================================ onde está o erro
export interface Located {
  /** linhas do orçamento envolvidas (a primeira é a do apontamento) */
  items: EvaluatedItem[];
  /** linha que o item duplica, quando é duplicidade */
  duplicateOf: EvaluatedItem | null;
  /** fotos envolvidas */
  photos: EvaluatedPhoto[];
  /** foto de outro chamado, quando é reaproveitamento */
  reusedFrom: { ticket: string; file: string } | null;
  /** apontamento sobre a ausência de algo: o painel mostra todas as fotos para conferir */
  absence: "before" | "after" | null;
  /** apontamento sobre o texto do escopo */
  scope: boolean;
  /** divergência entre a planilha e o chamado */
  spreadsheet: boolean;
}

const sameFinding = (a: Finding, b: Finding) => a.kind === b.kind && a.evidence === b.evidence;

/** Liga o apontamento às linhas do orçamento e às fotos que ele cita (pela referência gravada pelo backend). */
export function locate(f: Finding, p: Assessment): Located {
  const out: Located = { items: [], duplicateOf: null, photos: [], reusedFrom: null, absence: null, scope: false, spreadsheet: false };
  if (f.validation === "scope") {
    out.scope = true;
    return out;
  }
  if (f.validation === "quote") {
    if (f.kind === "spreadsheet_mismatch") {
      out.spreadsheet = true;
      return out;
    }
    // 1º: o item que carrega este mesmo apontamento; 2º: "item N: ..." na referência
    let item = p.items.find((i) => i.findings.some((x) => sameFinding(x, f)));
    const n = /^item (\d+)/i.exec(f.reference)?.[1];
    if (!item && n) item = p.items.find((i) => i.n === Number(n));
    if (item) out.items.push(item);
    if (f.kind === "duplicate_item") {
      const dup = /linha (\d+)/i.exec(f.evidence)?.[1];
      out.duplicateOf = dup ? p.items.find((i) => i.n === Number(dup)) ?? null : null;
    }
    return out;
  }
  // fotos
  if (f.kind === "missing_before_photo") out.absence = "before";
  if (f.kind === "missing_after_photo") out.absence = "after";
  if (f.reference) {
    const ph = p.photos.find((x) => x.file === f.reference);
    if (ph) out.photos.push(ph);
  }
  if (f.kind === "reused_photo") {
    // reused_from vem como "chamado/arquivo"; a evidência em texto é o plano B
    const origin = out.photos[0]?.reused_from;
    const slash = origin ? origin.indexOf("/") : -1;
    const m = /chamado (\S+) \((.+)\)\s*$/i.exec(f.evidence);
    if (origin && slash > 0) out.reusedFrom = { ticket: origin.slice(0, slash), file: origin.slice(slash + 1) };
    else if (m) out.reusedFrom = { ticket: m[1], file: m[2] };
  }
  return out;
}

// ============================================================================ e se este apontamento não procedesse?
export interface Simulation {
  grades: Record<ValidationKind, number>;
  score: number;
  confidence: "high" | "medium" | "low";
  recommendation: Recommendation;
  /** apontamentos que sobraram */
  kept: number;
}

/**
 * Reaplica a régua (atest/score.py) sem os tipos de apontamento marcados como improcedentes.
 * Serve para a pessoa analista ver, antes de registrar, o que a régua decidiria com a revisão dela.
 */
export function simulate(p: Assessment, rubric: RubricInfo, removed: Set<string>): Simulation | null {
  if (p.score === null || !p.grades) return null;
  const kept = p.findings.filter((f) => !removed.has(f.kind));
  const impacts = explainFindings(kept, rubric);
  const lost: Record<ValidationKind, number> = { scope: 0, quote: 0, photos: 0 };
  kept.forEach((f, k) => (lost[f.validation] += impacts[k].gradePts));
  const grades = { scope: 100 - lost.scope, quote: 100 - lost.quote, photos: 100 - lost.photos };
  const totalW = VALIDATIONS.reduce((s, v) => s + rubric.weights[v], 0) || 100;
  const score = Math.round(VALIDATIONS.reduce((s, v) => s + grades[v] * rubric.weights[v], 0) / totalW);

  // redutores que não vêm de apontamentos (ex.: anexos ilegíveis) continuam valendo
  const kinds = new Set(p.findings.map((f) => f.kind));
  const reducers = new Set([...kept.filter((f) => f.reduces_confidence).map((f) => f.kind), ...p.confidence_reducers.filter((r) => !kinds.has(r))]);
  const confidence = reducers.size >= rubric.confidence.low_with_n_reducers ? "low" : reducers.size >= rubric.confidence.medium_with_n_reducers ? "medium" : "high";

  let recommendation: Recommendation;
  if (kept.some((f) => f.lock)) recommendation = "return_locked";
  else if (confidence === "low") recommendation = "detailed_review";
  else recommendation = [...rubric.bands].sort((a, b) => b.score_min - a.score_min).find((b) => score >= b.score_min)?.recommendation ?? "return_to_supplier";
  return { grades, score, confidence, recommendation, kept: kept.length };
}

// ============================================================================ motivos rápidos para o comentário
export const REASONS_BY_KIND: Record<string, string> = {
  missing_before_photo: "Foto do antes não é exigida para este serviço",
  missing_after_photo: "O serviço concluído está comprovado em outro anexo",
  photo_mismatch: "A foto mostra o ambiente certo, só de outro ângulo",
  unreadable_photo: "A foto está legível o suficiente",
  reused_photo: "Não é reaproveitamento: mesmo local, serviço diferente",
  photo_dated_before: "A data da câmera está errada",
  out_of_scope_item: "O item é necessário para executar o escopo",
  unjustified_replacement: "A troca tem justificativa técnica",
  duplicate_item: "Não é duplicidade: são itens diferentes",
  quantity_above_expected: "A quantidade confere com a medição no local",
  price_above_reference: "Preço acima da referência é aceitável neste caso",
  spreadsheet_mismatch: "Divergência irrelevante na planilha",
  vague_scope: "O escopo é suficiente para avaliar",
  inconsistent_scope: "O escopo é coerente com a categoria",
};

export const REASONS_BY_DECISION: Partial<Record<Recommendation, string[]>> = {
  approve: ["Serviço conferido pelas evidências"],
  approve_with_caveats: ["Aprovar e orientar o fornecedor para os próximos chamados"],
  return_to_supplier: ["Fornecedor precisa corrigir o orçamento", "Fornecedor precisa reenviar as fotos"],
  return_locked: ["Indício de fraude: encaminhar para auditoria"],
  detailed_review: ["Precisa de vistoria no local", "Precisa consultar o gestor da agência"],
};
