import type { Stage, Recommendation, Finding, RubricInfo, ValidationKind } from "./api";

export const brl = (v: number | null | undefined) =>
  (v ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

export const brl4 = (v: number | null | undefined) =>
  (v ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2, maximumFractionDigits: 4 });

export const num = (v: number) => v.toLocaleString("pt-BR", { maximumFractionDigits: 3 });

// cor = tinta para texto e carimbo (contraste ≥ 4.5:1); marca = preenchimento em gráficos
// (paleta categórica validada para daltonismo na ordem aprovar, ressalvas, análise, devolver, trava, checklist)
export const REC: Record<Recommendation, { label: string; short: string; color: string; mark: string }> = {
  approve: { label: "Aprovar", short: "Aprovar", color: "var(--color-ok)", mark: "#008300" },
  approve_with_caveats: { label: "Aprovar com ressalvas", short: "Ressalvas", color: "var(--color-warn)", mark: "#eda100" },
  return_to_supplier: { label: "Devolver ao fornecedor", short: "Devolver", color: "var(--color-bad)", mark: "#e34948" },
  return_locked: { label: "Devolver por trava de integridade", short: "Trava", color: "var(--color-lock)", mark: "#6250d6" },
  detailed_review: { label: "Análise detalhada", short: "Análise", color: "var(--color-detail)", mark: "#2a78d6" },
  checklist_returned: { label: "Devolvido por checklist incompleto", short: "Checklist", color: "var(--color-return)", mark: "#e87ba4" },
};

export const pct = (v: number | null | undefined, decimals = 0) => (v === null || v === undefined ? "—" : `${(100 * v).toFixed(decimals)}%`);

export const STAGES: { id: Stage; label: string }[] = [
  { id: "checklist", label: "Checklist" },
  { id: "scope", label: "Escopo" },
  { id: "quote", label: "Orçamento" },
  { id: "photos", label: "Fotos" },
  { id: "score", label: "Score" },
  { id: "assessment", label: "Parecer" },
];

export const FINDING_LABELS: Record<string, string> = {
  vague_scope: "Escopo vago",
  out_of_scope_item: "Item fora do escopo",
  unjustified_replacement: "Troca sem justificativa",
  duplicate_item: "Item duplicado",
  quantity_above_expected: "Quantidade acima",
  price_above_reference: "Preço acima da referência",
  photo_mismatch: "Foto não corresponde",
  missing_after_photo: "Sem foto do concluído",
  missing_before_photo: "Sem foto do antes",
  unreadable_photo: "Foto ilegível",
  reused_photo: "Foto reaproveitada",
  photo_dated_before: "Data da foto anterior",
  spreadsheet_mismatch: "Planilha divergente",
  inconsistent_scope: "Escopo incoerente",
};

export const TASK_LABELS: Record<string, string> = {
  identify_attachments: "Identificação dos anexos",
  scope: "Leitura do escopo",
  quote_review: "Orçamento × escopo",
  photos: "Análise das fotos",
  assessment: "Redação do parecer",
};

export const SEVERITY: Record<string, { label: string; color: string }> = {
  critical: { label: "Crítico", color: "var(--color-lock)" },
  high: { label: "Alto", color: "var(--color-bad)" },
  medium: { label: "Médio", color: "var(--color-warn)" },
  low: { label: "Baixo", color: "var(--color-muted)" },
};

export const MISSING: Record<string, string> = {
  after_photo: "Foto do depois",
  removed_items_photo: "Foto dos itens retirados",
  certificate: "Termo de conclusão",
  panel_photo: "Foto da central",
  before_photo: "Foto do antes",
  quote: "Orçamento",
};

/** Rótulos de exibição dos valores de enum que chegam da API (os valores são em inglês; a tela é em português). */
export const CONFIDENCE_LABEL: Record<string, string> = { high: "alta", medium: "média", low: "baixa" };
export const MOMENT_LABEL: Record<string, string> = { before: "antes", after: "depois", during: "durante", undetermined: "indeterminado" };

// ============================================================================ score: de onde vem cada ponto

export const VALIDATION_LABEL: Record<ValidationKind, string> = { scope: "Escopo", quote: "Orçamento × escopo", photos: "Evidências fotográficas" };
export const VALIDATION_SHORT: Record<ValidationKind, string> = { scope: "Escopo", quote: "Orçamento", photos: "Fotos" };
export const VALIDATIONS: ValidationKind[] = ["scope", "quote", "photos"];

/** Régua padrão (config/rubric.toml), usada se a API ainda não expuser a régua. */
export const DEFAULT_RUBRIC: RubricInfo = {
  weights: { scope: 20, quote: 40, photos: 40 },
  discount_by_severity: { critical: 60, high: 35, medium: 15, low: 5 },
  bands: [
    { score_min: 85, recommendation: "approve" },
    { score_min: 70, recommendation: "approve_with_caveats" },
    { score_min: 0, recommendation: "return_to_supplier" },
  ],
  confidence: { medium_with_n_reducers: 1, low_with_n_reducers: 2 },
};

export interface FindingImpact {
  /** pontos tirados da nota da validação (0–100) */
  gradePts: number;
  /** pontos que isso representa no score final (nota × peso) */
  scorePts: number;
  /** o mesmo tipo já descontou nesta validação: este não desconta de novo */
  repeated: boolean;
  /** a nota já tinha chegado a zero: o desconto foi limitado */
  capped: boolean;
}

/** Reproduz a régua (atest/score.py): cada tipo desconta uma vez por validação, nota mínima 0, score = média ponderada. */
export function explainFindings(findings: Finding[], rubric: RubricInfo): FindingImpact[] {
  const totalWeight = VALIDATIONS.reduce((s, v) => s + rubric.weights[v], 0) || 100;
  const seen: Record<ValidationKind, Set<string>> = { scope: new Set(), quote: new Set(), photos: new Set() };
  const used: Record<ValidationKind, number> = { scope: 0, quote: 0, photos: 0 };
  return findings.map((f) => {
    if (seen[f.validation].has(f.kind)) return { gradePts: 0, scorePts: 0, repeated: true, capped: false };
    seen[f.validation].add(f.kind);
    const pts = Math.max(0, Math.min(f.discount, 100 - used[f.validation]));
    used[f.validation] += pts;
    return { gradePts: pts, scorePts: (pts * rubric.weights[f.validation]) / totalWeight, repeated: false, capped: pts < f.discount };
  });
}

/** Número de pontos com no máximo uma casa decimal (14 · 6 · 2,5). */
export const pts = (v: number) => v.toLocaleString("pt-BR", { maximumFractionDigits: 1 });

// ============================================================================ glossário (tooltips, tour e modal de ajuda)
export const GLOSSARY: Record<string, { term: string; text: string }> = {
  score: { term: "Score de conformidade", text: "Nota de 0 a 100 do chamado. É a média ponderada das notas de Escopo, Orçamento e Fotos. Quem dá a nota é a régua, não o modelo: o modelo só aponta divergências." },
  grade: { term: "Nota da validação", text: "Cada validação começa com 100 e perde pontos a cada apontamento, conforme a severidade. Nunca fica abaixo de 0." },
  weight: { term: "Peso", text: "Quanto cada validação vale no score final. Ex.: um desconto de 35 na nota de Orçamento (peso 40%) tira 14 pontos do score." },
  severity: { term: "Severidade", text: "Gravidade do apontamento. Define quantos pontos ele tira da nota da validação: Crítico −60, Alto −35, Médio −15, Baixo −5." },
  once: { term: "Desconto único por tipo", text: "Se o mesmo tipo de apontamento aparece várias vezes na mesma validação, ele desconta uma vez só. As demais ocorrências ficam listadas como evidência." },
  lock: { term: "Trava de integridade", text: "Apontamento grave (ex.: foto reaproveitada de outro chamado). Devolve o chamado qualquer que seja o score." },
  confidence: { term: "Confiança", text: "Quanto dá para confiar na análise com a entrada recebida. Escopo vago ou foto ilegível reduzem a confiança. Confiança baixa manda o chamado para análise detalhada." },
  amount: { term: "Valor potencial divergente", text: "Quanto do orçamento pode estar divergente do escopo ou da referência. Item fora do escopo, sem justificativa ou duplicado conta inteiro; preço ou quantidade acima contam só o excedente." },
  bands: { term: "Faixas de recomendação", text: "85 ou mais: aprovar. De 70 a 84: aprovar com ressalvas. Abaixo de 70: devolver ao fornecedor. Travas e confiança baixa vencem a faixa." },
  checklist: { term: "Checklist mínimo", text: "Documentos obrigatórios para a categoria (ex.: foto do depois, termo de conclusão). Se faltar algo, o chamado volta antes de qualquer análise e não recebe score." },
  phase: { term: "Fase da régua", text: "Fase 1 é o MVP: não cobra foto do antes nem checa ilegibilidade e reaproveitamento. Fase 2 inclui essas checagens." },
  mode: { term: "Modo", text: "Simulado demonstra o fluxo com respostas simuladas, sem chamar o modelo e sem custo. API chama o modelo de verdade e gera custo." },
  batch: { term: "Envio em lote", text: "Os pedidos vão juntos para a API de lotes do provedor (Message Batches). Custa metade, mas o resultado demora mais." },
  stage: { term: "Etapa da esteira", text: "Aprovação de Orçamento: o fornecedor envia escopo, orçamento e fotos do antes. Atestação do Serviço: além disso, envia as fotos do depois e os demais documentos do checklist da categoria." },
  maintenance: { term: "Tipo de manutenção", text: "Corretiva: conserta um problema que apareceu. Preventiva: manutenção programada para evitar problemas (ex.: limpeza mensal do ar-condicionado)." },
  ground_truth: { term: "Gabarito", text: "A decisão esperada para o chamado, definida por especialistas. Serve para medir se o Atest.AI acertou." },
  accuracy: { term: "Acurácia", text: "Percentual de chamados em que a recomendação do Atest.AI foi igual à do gabarito. O IC 95% mostra a faixa provável do valor real." },
  kappa: { term: "Kappa de Cohen", text: "Concordância com o gabarito descontando o acerto por acaso. 0 = acaso; acima de 0,6 = boa; acima de 0,8 = muito boa." },
  balanced: { term: "Acurácia balanceada", text: "Média da acurácia de cada classe. Evita que uma classe muito frequente esconda erros nas raras." },
  catch: { term: "Pegar problema", text: "Trata a decisão como sim/não: o chamado deveria parar (devolver, travar, checklist ou análise detalhada)? O número grande é o F1, que equilibra cobertura (recall: quantos problemas reais foram pegos) e precisão (quantas paradas estavam certas)." },
  precision: { term: "Precisão (precision)", text: "Dos casos que o Atest.AI sinalizou, quantos estavam certos: VP ÷ (VP + FP). Baixa precisão = alarmes falsos e retrabalho." },
  recall: { term: "Cobertura (recall)", text: "Dos problemas reais, quantos o Atest.AI encontrou: VP ÷ (VP + FN). Também chamada de sensibilidade. Baixa cobertura = problemas que passam despercebidos." },
  f1: { term: "F1", text: "Equilíbrio entre precisão e cobertura (média harmônica): 2 × P × C ÷ (P + C). Não é o recall: só chega a 100% se precisão e cobertura forem as duas 100%." },
  specificity: { term: "Especificidade", text: "Dos chamados bons, quantos o Atest.AI deixou seguir: VN ÷ (VN + FP). Baixa especificidade = chamados bons parados sem necessidade." },
  mae: { term: "Erro médio do score", text: "Em média, quantos pontos o score do Atest.AI ficou longe do score do gabarito." },
  bias: { term: "Viés", text: "Positivo: o Atest.AI dá notas mais altas que o gabarito. Negativo: é mais rigoroso." },
  pearson: { term: "Correlação (r)", text: "Se os scores sobem e descem juntos com o gabarito. 1 = acompanham perfeitamente." },
  gate: { term: "Portão de qualidade", text: "Limites mínimos que uma configuração precisa atingir para ir para produção (acurácia, kappa, F1, erro do score)." },
  noise: { term: "Erro simulado", text: "No modo simulado, a fração de vezes em que o simulador erra de propósito, para imitar um modelo real." },
  p95: { term: "p95", text: "95% dos chamados ficaram abaixo deste valor. Mostra o pior caso típico, sem os extremos." },
};

// ============================================================================ classificação do chamado (valores da API → português)
export const MAINTENANCE_LABEL: Record<string, string> = { corrective: "Corretiva", preventive: "Preventiva" };
export const STAGE_LABEL: Record<string, string> = { quote: "Aprovação de Orçamento", execution: "Atestação do Serviço" };
/** rótulo curto da etapa, para selos nos cards */
export const STAGE_SHORT: Record<string, string> = { quote: "Aprov. orçamento", execution: "Atest. serviço" };
/** O que o fornecedor envia em cada etapa da esteira. */
export const STAGE_DOCS: Record<string, string[]> = {
  quote: ["Escopo", "Orçamento (planilha padrão)", "Fotos do antes"],
  execution: ["Escopo", "Orçamento (planilha padrão)", "Fotos do antes", "Fotos do depois", "Demais documentos do checklist da categoria"],
};

/** Ambientes da agência como chegam no chamado. Valores fora da lista aparecem como vieram. */
export const ENV_LABEL: Record<string, string> = {
  backoffice: "backoffice", back_office: "backoffice", corridor: "corredor", self_service: "autoatendimento",
  service: "salão de atendimento", boxes: "caixas", kitchen: "cozinha", parking: "estacionamento", treasury: "tesouraria",
  hall: "salão", facade: "fachada", restroom: "banheiro",
};
export const envLabel = (v: string | null | undefined) => (v ? ENV_LABEL[v] ?? v.replace(/_/g, " ") : "");

export const PROVIDER_LABEL: Record<string, string> = { anthropic: "Anthropic", openai: "OpenAI", google: "Google", iara: "IARA" };
export const providerLabel = (v: string) => PROVIDER_LABEL[v] ?? v;

export const ENV_NAME: Record<string, string> = { development: "desenvolvimento", staging: "homologação", production: "produção" };
