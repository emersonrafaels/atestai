// Contratos da API (espelham os modelos Pydantic de atest/domain.py e atest/api.py)

export type Recommendation =
  | "approve"
  | "approve_with_caveats"
  | "return_to_supplier"
  | "return_locked"
  | "detailed_review"
  | "checklist_returned";

export type Stage = "checklist" | "scope" | "quote" | "photos" | "documents" | "score" | "assessment" | "done";

export interface Expected {
  recommendation: Recommendation;
  score: number | null;
  findings: string[];
  optional: string[];
  missing: string[];
}

export interface LastAssessment {
  assessment_id: number;
  run_id: string | null;
  generated_at: string;
  recommendation: Recommendation;
  score: number | null;
  mode: string;
  feedback: string | null;
}

export interface TicketSummary {
  ticket_id: string;
  origin: "dataset" | "upload";
  dataset: string;
  last: LastAssessment | null;
  workstream: "SETA" | "SISR";
  category: string;
  category_label: string;
  symptom: string;
  symptom_label: string;
  /** descrição detalhada do problema (o escopo pedido) */
  scope: string;
  branch: string;
  environment: string;
  /** o problema está impedindo a abertura da agência? (null = não informado) */
  blocks_opening?: boolean | null;
  /** descrição da solução (opcional; pode vir já na aprovação do orçamento) */
  solution_description?: string;
  supplier: string;
  quoted_value: number | null;
  moment: "quote" | "execution";
  maintenance_type: string;
  n_photos: number;
  expected: Expected | null;
  /** tipos de cenário de teste que o gabarito descreve (atest/scenarios.py) */
  tags?: string[];
  /** catálogo de cenários (0300…): o que este chamado testa */
  scenario?: { id: string; title: string; description: string } | null;
}

/** Tipo de cenário de teste (GET /api/scenarios). */
export interface ScenarioTag {
  id: string;
  group: string;
  group_label: string;
  label: string;
  description: string;
}

export interface QuoteItem {
  n: number;
  description: string;
  unit: string;
  /** item da tabela de preços (LPU); planilhas sem a coluna vêm como true */
  lpu?: boolean;
  quantity: number;
  unit_value: number;
  total_value: number;
}

export interface Quote {
  file: string;
  number: string;
  supplier: string;
  data: string | null;
  category: string;
  symptom: string;
  scope: string;
  items: QuoteItem[];
  total_value: number;
}

export interface AttachmentInfo {
  index: number;
  name: string;
  content_type: string;
  url: string;
  is_image: boolean;
}

export interface TicketDetail extends TicketSummary {
  dates: Record<string, string | null>;
  quote: Quote | null;
  quote_error: string | null;
  attachments: AttachmentInfo[];
}

export interface Finding {
  kind: string;
  validation: "scope" | "quote" | "photos";
  severity: "critical" | "high" | "medium" | "low";
  discount: number;
  description: string;
  evidence: string;
  reference: string;
  lock: boolean;
  reduces_confidence: boolean;
  phase: number;
  amount_at_issue: number;
  /** tipo que absorveu este apontamento (régua: `absorbs`): segue como evidência, mas não desconta */
  absorbed_by?: string;
}

export interface EvaluatedItem extends QuoteItem {
  classification: "compliant" | "out_of_scope" | "to_justify";
  reason: string;
  lpu_code: string;
  reference_price: number | null;
  expected_quantity_max: number | null;
  amount_at_issue: number;
  findings: Finding[];
}

export interface EvaluatedPhoto {
  file: string;
  environment: string;
  what_it_shows: string;
  moment: string;
  readable: boolean;
  matches_scope: "yes" | "no" | "partial" | "undetermined";
  reason: string;
  covered_items: number[];
  exif_date: string | null;
  reused_from: string | null;
  integrity_signals: string[];
}

export interface ClassifiedAttachment {
  index: number;
  name: string;
  category: string;
  moment: string;
  readable: boolean;
  short_description: string;
}

export interface LlmCall {
  task: string;
  model: string;
  start: string;
  duration_s: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost_usd: number;
  from_cache: boolean;
  simulated: boolean;
  via_batch: boolean;
  batch_id: string | null;
  response: Record<string, unknown>;
}

export interface EvaluatedDocument {
  file: string;
  kind: string;
  handwritten: boolean;
  legible: "yes" | "partial" | "no" | "undetermined";
  transcription: string;
  issuer: string;
  service_date: string;
  start_time: string;
  end_time: string;
  branch: string;
  problem: string;
  solution: string;
  has_signature: boolean;
  /** o documento prova que o serviço já foi feito? (yes só com afirmação explícita) */
  service_status?: "yes" | "partial" | "no" | "undetermined";
  prices: { description: string; value: number; quote_item: number; same_product?: "yes" | "partial" | "no" | "undetermined" }[];
  matches_ticket: "yes" | "partial" | "no" | "undetermined";
  divergences: string[];
  reason: string;
}

export interface Assessment {
  ticket_id: string;
  workstream: string;
  category: string;
  symptom: string;
  moment: string;
  supplier: string;
  quoted_value: number | null;
  generated_at: string;
  rubric_version: string;
  prompts_version: string;
  phase: number;
  mode: string;
  batch_mode: string;
  models: Record<string, string>;
  run_id: string | null;
  record_id: number | null;
  maintenance_type: string;
  checklist: {
    complete: boolean;
    uploaded: number;
    total: number;
    requirements: { id: string; description: string; met: boolean; attachments: string[] }[];
    missing: string[];
  };
  attachments: ClassifiedAttachment[];
  recommendation: Recommendation;
  recommendation_reason: string;
  score: number | null;
  grades: { scope: number; quote: number; photos: number } | null;
  confidence: "high" | "medium" | "low" | null;
  confidence_reducers: string[];
  findings: Finding[];
  amount_at_issue: number;
  amount_at_issue_pct: number;
  scope: Record<string, unknown> | null;
  items: EvaluatedItem[];
  quote_notes: string[];
  photos: EvaluatedPhoto[];
  photo_summary: Record<string, unknown> | null;
  /** documentos lidos por OCR (foto de documento ou PDF) */
  documents?: EvaluatedDocument[];
  summary: string;
  supplier_message: string;
  llm_calls: LlmCall[];
  duration_s: number;
  stage_durations_s: Record<string, number>;
  cost_usd: number;
  cost_brl: number;
}

export interface Comparison {
  ticket_id: string;
  expected: Recommendation;
  obtained: Recommendation;
  expected_score: number | null;
  obtained_score: number | null;
  recommendation_ok: boolean;
  direction_ok: boolean;
  checklist_ok: boolean;
  missed: string[];
  extra: string[];
}

export interface TicketState {
  ticket_id: string;
  recommendation: Recommendation | null;
  score: number | null;
  status: "queue" | "running" | "done" | "error";
  stage: Stage | null;
  completed_stages: Stage[];
  assessment: Assessment | null;
  comparison: Comparison | null;
  error: string | null;
}

export interface Run {
  id: string;
  created_at: string;
  completed_at: string | null;
  status: "running" | "completed";
  mode: "api" | "simulated";
  batch_mode: "sync" | "batch";
  phase: number;
  models: Record<string, string>;
  tickets: Record<string, TicketState>;
  evaluation: {
    n: number;
    exact_recommendation: number;
    direction: number;
    checklist: number;
    avg_score_error: number | null;
  } | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  cost_brl: number;
  api_batches: string[];
  output_folder: string | null;
  label: string;
  signature: string;
  simulated_noise: number;
  has_validation: boolean;
}

/** Item do cadastro (categoria, sintoma ou local), como vem de /api/config e do portal. */
export interface Option {
  value: string;
  label: string;
  enabled?: boolean;
  /** categoria: esteiras em que vale (vazio = SETA e SISR) */
  workstreams?: string[];
  /** sintoma: categorias em que vale (vazio = todas) */
  categories?: string[];
}

export type CatalogKind = "categories" | "symptoms" | "locations";
export type CatalogConfig = Record<CatalogKind, Required<Option>[]>;
export interface CatalogUsage { tickets: number; ground_truth: number; rules: number }

export interface AppSettings {
  environment: string;
  version: string;
  api_available: boolean;
  main_model: string;
  fast_model: string;
  phase: number;
  batch_mode: "sync" | "batch";
  rubric_version: string;
  prompts_version: string;
  usd_brl_rate: number;
  categories: Option[];
  symptoms: Option[];
  locations?: Option[];
  providers: string[];
  missing_keys: string[];
  signature: string;
  validation: { dataset: string; accuracy_min: number; kappa_min: number; finding_f1_min: number; score_error_max: number };
  rubric?: RubricInfo;
  models?: ModelOption[];
  keyed_providers?: string[];
  /** seletor de provedor (config/settings.toml: [panel.providers]); o primeiro é o da configuração */
  provider_choices?: ProviderChoice[];
  /** revisão do contrato com o servidor; ausente ou menor = servidor antigo rodando */
  panel_api?: number;
}

/** Provedor oferecido no seletor do painel, com os modelos que ele preenche ao ser escolhido. */
export interface ProviderChoice {
  id: string;
  label: string;
  main: string;
  fast: string;
  available: boolean;
  /** variáveis de ambiente exigidas (só os nomes) */
  credentials: string[];
}

/** Modelo sugerido nos campos de modelo (tabela de preços + configurados). */
export interface ModelOption {
  id: string;
  provider: string;
  name: string;
  input_price: number | null;
  output_price: number | null;
  /** complemento, ex.: backend da IARA (azure_openai, bedrock, vertex) */
  detail?: string;
  /** não lê imagens: falha nas tarefas com fotos e anexos */
  text_only?: boolean;
}

export type ValidationKind = "scope" | "quote" | "photos";

/** Régua do score (config/rubric.toml), usada pelo painel para explicar de onde vem cada ponto. */
export interface RubricInfo {
  weights: Record<ValidationKind, number>;
  discount_by_severity: Record<Finding["severity"], number>;
  bands: { score_min: number; recommendation: Recommendation }[];
  confidence: { medium_with_n_reducers: number; low_with_n_reducers: number };
  /** tipo de apontamento → tipos da mesma validação que ele absorve (deixam de descontar quando ele aparece) */
  absorbs?: Record<string, string[]>;
}

export interface Dataset {
  name: string;
  label: string;
  n: number;
}

export interface Interval {
  value: number;
  ci_low: number;
  ci_high: number;
}

export interface BinaryMetric {
  tp: number;
  fp: number;
  fn: number;
  tn: number;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  specificity: number | null;
}

export interface ValidationReport {
  n: number;
  no_ground_truth: number;
  classes: Recommendation[];
  matrix: number[][];
  accuracy: Interval;
  balanced_accuracy: number;
  kappa: number | null;
  problem_catch: BinaryMetric;
  problem_catch_f1_ci: Interval | null;
  checklist_accuracy: number;
  findings: { kind: string; support: number; tp: number; fp: number; fn: number; precision: number | null; recall: number | null; f1: number | null }[];
  findings_micro: BinaryMetric;
  finding_macro_f1: number | null;
  score_pairs: { ticket_id: string; expected: number; obtained: number }[];
  score_mae: number | null;
  score_rmse: number | null;
  score_bias: number | null;
  score_pearson: number | null;
  expected_amount_at_issue: number;
  obtained_amount_at_issue: number;
  amount_at_issue_mae: number | null;
  by_category: { name: string; n: number; hits: number; accuracy: number }[];
  by_service_template: { name: string; n: number; hits: number; accuracy: number }[];
  operations: { latency_p50_s: number | null; latency_p95_s: number | null; avg_cost_brl: number; p95_cost_brl: number; total_cost_brl: number; avg_input_tokens: number; avg_output_tokens: number };
  mismatches: { ticket_id: string; category: string; expected: Recommendation; obtained: Recommendation; expected_score: number | null; obtained_score: number | null; missed: string[]; extra: string[] }[];
  gate: { metric: string; value: number | null; limit: number; direction: string; passed: boolean }[];
  gate_passed: boolean;
}

export interface PhotoFacts {
  file: string;
  url: string;
  taken_at: string | null;
  uploaded_on: string | null;
  size_bytes: number | null;
  width: number | null;
  height: number | null;
  detail: number | null;
}

export interface TicketFacts {
  ticket_id: string;
  source: "tickets" | "history";
  workstream: string;
  category_label: string;
  symptom_label: string;
  scope: string;
  branch_code: string;
  branch_name: string;
  environment: string;
  supplier_name: string;
  supplier_cnpj: string;
  quoted_value: number | null;
  opening: string;
  supplier_submission: string;
  manager_review: string | null;
  status: string;
  n_photos: number;
  last_recommendation: Recommendation | null;
  last_score: number | null;
}

/** Comparação de uma foto reaproveitada com a original (GET /api/tickets/{id}/reuse). */
export interface ReuseComparison {
  current: TicketFacts;
  current_photo: PhotoFacts;
  origin: TicketFacts;
  origin_photo: PhotoFacts;
  distance: number | null;
  limit: number;
  basis: "exif" | "mixed" | "dates";
  origin_moment: string;
  current_moment: string;
  chronology_ok: boolean;
  gap_hours: number;
  same_branch: boolean;
  same_supplier: boolean;
}

export type FeedbackAction = "accept" | "adjust" | "disagree";

export interface FeedbackInput {
  action: FeedbackAction;
  final_decision?: Recommendation | null;
  unfounded_findings: string[];
  comment: string;
  author?: string;
}

export interface Feedback extends FeedbackInput {
  id: number;
  assessment_id: number;
  ticket_id: string;
  created_at: string;
  atest_recommendation: Recommendation;
}

export interface RunSummary {
  id: string;
  created_at: string;
  completed_at: string | null;
  status: string;
  mode: string;
  batch_mode: string;
  phase: number;
  tickets: string[];
  cost_brl: number;
  input_tokens: number;
  output_tokens: number;
  evaluation: { n: number; exact_recommendation: number } | null;
  errors: Record<string, string> | null;
  label: string | null;
  signature: string | null;
  validation: { n: number; accuracy: Interval; kappa: number | null; finding_f1: number | null; problem_catch_f1: number | null; score_mae: number | null; gate_passed: boolean } | null;
}

export interface OperationsView {
  assessments: number;
  tickets: number;
  cost_usd: number;
  cost_brl: number;
  avg_cost_brl: number | null;
  avg_duration_s: number | null;
  amount_at_issue: number;
  runs: number;
  with_errors: number | null;
  by_recommendation: { recommendation: Recommendation; n: number }[];
  cost_by_workstream: { workstream: string; n: number; cost_brl: number; avg_brl: number }[];
  by_task: { task: string; model: string; calls: number; avg_duration_s: number; input_tokens: number; output_tokens: number; cache_read_tokens: number; cost_usd: number; via_batch: number; from_cache: number }[];
  feedback: { action: FeedbackAction; n: number }[];
  feedback_agreement: { total: number; accepted: number | null; different_decision: number | null };
  unfounded_findings: { kind: string; n: number }[];
  by_day: { day: string; n: number; cost_brl: number }[];
}

export interface RunRequest {
  tickets?: string[];
  dataset?: string;
  sample?: number | null;
  simulated_noise?: number;
  label?: string;
  mode: "api" | "simulated";
  batch_mode: "sync" | "batch";
  phase: number;
  main_model?: string;
  fast_model?: string;
  provider?: string;
  /** executa o agente de novo, sem reaproveitar respostas salvas no cache */
  refresh?: boolean;
}

// Tipos de erro de validação do FastAPI/Pydantic → português (a mensagem original vem em inglês).
const VALIDATION_PT: Record<string, string> = {
  missing: "campo obrigatório",
  extra_forbidden: "campo não reconhecido",
  float_parsing: "número inválido",
  int_parsing: "número inteiro inválido",
  bool_parsing: "valor sim/não inválido",
  string_type: "texto esperado",
  string_too_short: "texto curto demais",
  string_too_long: "texto longo demais",
  date_parsing: "data inválida",
  date_from_datetime_parsing: "data inválida",
  enum: "valor não permitido",
  literal_error: "valor não permitido",
  greater_than_equal: "valor abaixo do mínimo",
  less_than_equal: "valor acima do máximo",
  json_invalid: "JSON inválido",
};

/** Lista de erros 422 do FastAPI em uma frase: "campo › subcampo: motivo; ...". */
function validationMessage(detail: unknown): string {
  if (!Array.isArray(detail)) return "Dados inválidos";
  const parts = detail.slice(0, 3).map((d: { loc?: (string | number)[]; type?: string }) => {
    const loc = (d.loc ?? []).filter((x) => x !== "body" && x !== "query" && x !== "path").join(" › ");
    const reason = VALIDATION_PT[d.type ?? ""] ?? "valor inválido";
    return loc ? `${loc}: ${reason}` : reason;
  });
  return `Dados inválidos: ${parts.join("; ")}${detail.length > 3 ? `; e mais ${detail.length - 3}` : ""}`;
}

async function ask<T>(url: string, init?: RequestInit): Promise<T> {
  const json = !(init?.body instanceof FormData);
  const r = await fetch(url, { ...(json ? { headers: { "Content-Type": "application/json" } } : {}), ...init });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const body = await r.json();
      if (body.detail) msg = typeof body.detail === "string" ? body.detail : validationMessage(body.detail);
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(msg);
  }
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}

export const api = {
  config: () => ask<AppSettings>("/api/config"),
  tickets: () => ask<TicketSummary[]>("/api/tickets"),
  ticket: (id: string) => ask<TicketDetail>(`/api/tickets/${id}`),
  run: (p: RunRequest) => ask<Run>("/api/runs", { method: "POST", body: JSON.stringify(p) }),
  execution: (id: string, light = false) => ask<Run>(`/api/runs/${id}${light ? "?light=true" : ""}`),
  datasets: () => ask<Dataset[]>("/api/datasets"),
  scenarios: () => ask<ScenarioTag[]>("/api/scenarios"),
  validation: (id: string) => ask<ValidationReport>(`/api/runs/${id}/validation`),
  validations: () => ask<RunSummary[]>("/api/validations"),
  runs: () => ask<RunSummary[]>("/api/runs"),
  assessment: (id: number) => ask<Assessment>(`/api/assessments/${id}`),
  feedbacks: (id: number) => ask<Feedback[]>(`/api/assessments/${id}/feedback`),
  sendFeedback: (id: number, f: FeedbackInput) =>
    ask<Feedback>(`/api/assessments/${id}/feedback`, { method: "POST", body: JSON.stringify(f) }),
  metrics: () => ask<OperationsView>("/api/metrics"),
  sendTicket: (data: FormData) => ask<TicketSummary>("/api/tickets", { method: "POST", body: data }),
  deleteTicket: (id: string) => ask<void>(`/api/tickets/${id}`, { method: "DELETE" }),
  reuse: (id: string, file: string, origin: string, originFile: string) =>
    ask<ReuseComparison>(`/api/tickets/${id}/reuse?${new URLSearchParams({ file, origin, origin_file: originFile })}`),
};

// ============================================================================ portal de configuração (com login)
export interface FindingTypeConfig {
  validation: ValidationKind;
  severity: Finding["severity"];
  description: string;
  phase: number;
  reduces_confidence: boolean;
  lock: boolean;
  amount_at_issue: "item" | "excess" | "none";
  enabled: boolean;
  /** tipos da mesma validação que deixam de descontar quando este aparece */
  absorbs?: string[];
  /** ajustes por esteira: o que vier null segue o padrão */
  by_workstream?: Partial<Record<"SETA" | "SISR", { enabled?: boolean | null; severity?: Finding["severity"] | null }>>;
}

export interface RubricConfig {
  version: string;
  weights: Record<ValidationKind, number>;
  discount_by_severity: Record<Finding["severity"], number>;
  counts: string;
  bands: { score_min: number; recommendation: Recommendation }[];
  confidence: { medium_with_n_reducers: number; low_with_n_reducers: number };
  price_tolerance_pct: number;
  hash_max_distance: number;
  hash_max_distance_low_detail: number;
  hash_crops: number[];
  hash_min_detail: number;
  hash_method: string;
  spreadsheet_value_tolerance: number;
  photo_date_tolerance_days: number;
  relevant_amount_at_issue_pct: number;
  photo_quantity_tolerance_pct?: number;
  max_amount_at_issue_for_approve_pct?: number;
  market_price_tolerance_pct?: number;
  finding_types: Record<string, FindingTypeConfig>;
}

export interface ChecklistRequirementConfig {
  id: string;
  description: string;
  accepted: string[];
  enabled: boolean;
}

export interface ChecklistRuleConfig {
  /** esteira: "SETA", "SISR" ou "*" (qualquer) */
  workstream?: string;
  category: string;
  maintenance: string;
  moment: string;
  requirements: ChecklistRequirementConfig[];
  enabled: boolean;
}

export interface ChecklistsConfig {
  attachment_categories: Record<string, string>;
  rules: ChecklistRuleConfig[];
}

export interface SectionState<T> {
  data: T;
  base: T;
  overridden: boolean;
  version_id: number | null;
}

export interface AdminOverview {
  sections: { rubric: SectionState<RubricConfig>; checklists: SectionState<ChecklistsConfig>; catalog: SectionState<CatalogConfig> };
  catalog: {
    categories: (Required<Option> & { tickets: number; usage: CatalogUsage; symptoms_seen: string[] })[];
    symptoms: (Required<Option> & { tickets: number; usage: CatalogUsage })[];
    locations: (Required<Option> & { tickets: number; usage: CatalogUsage })[];
    usage: Record<CatalogKind, Record<string, CatalogUsage>>;
    tickets: number;
  };
  lpu: Record<string, { code: string; description: string; unit: string; reference_price: number }[]>;
  system: {
    rubric_version: string; prompts_version: string; signature: string; base_signature: string;
    main_model: string; fast_model: string; phase: number; environment: string; version: string;
    validation: { dataset: string; accuracy_min: number; kappa_min: number; finding_f1_min: number; score_error_max: number };
  };
}

export interface AdminHistoryItem {
  id: number;
  section: "rubric" | "checklists" | "catalog";
  author: string;
  comment: string;
  summary: string[];
  created_at: string;
  is_default: boolean;
}

/** Parecer gravado, na lista de limpeza do histórico (portal). */
export interface AdminAssessmentItem {
  id: number;
  run_id: string | null;
  ticket_id: string;
  generated_at: string;
  recommendation: Recommendation;
  score: number | null;
  mode: string;
  cost_brl: number | null;
  run_label: string | null;
  run_status: string | null;
  feedbacks: number;
}

export interface DeleteAssessmentsResult {
  assessments: number;
  feedbacks: number;
  runs_touched: string[];
  runs_removed: string[];
}

export interface AdminUser {
  username: string;
  created_at: string;
  created_by: string | null;
  last_login: string | null;
}

/** Revisão da API que este front-end espera (atest/api.py: PANEL_API). */
export const PANEL_API = 7;
export const serverOutdated = (c: AppSettings | null) => !!c && (c.panel_api ?? 0) < PANEL_API;

const TOKEN_KEY = "atest.admin.token";
export const ADMIN_LOGOUT_EVENT = "atest:admin-logout";

/** Sessão do portal: o token fica só nesta aba do navegador (sessionStorage) e some ao fechá-la. */
export const adminSession = {
  get: (): string | null => { try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set: (t: string) => { try { sessionStorage.setItem(TOKEN_KEY, t); } catch { /* armazenamento indisponível */ } },
  clear: () => { try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* armazenamento indisponível */ } },
};

async function askAdmin<T>(url: string, init?: RequestInit): Promise<T> {
  const token = adminSession.get();
  try {
    return await ask<T>(url, { ...init, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  } catch (e) {
    if ((e as Error).message.startsWith("Sessão expirada")) {
      adminSession.clear();
      window.dispatchEvent(new Event(ADMIN_LOGOUT_EVENT));
    }
    throw e;
  }
}

export const adminApi = {
  login: (username: string, password: string) =>
    ask<{ token: string; username: string; expires_at: string }>("/api/admin/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  logout: () => askAdmin<void>("/api/admin/logout", { method: "POST" }),
  me: () => askAdmin<{ username: string }>("/api/admin/me"),
  overview: () => askAdmin<AdminOverview>("/api/admin/overview"),
  save: (section: "rubric" | "checklists" | "catalog", data: unknown, comment: string) =>
    askAdmin<AdminOverview>(`/api/admin/config/${section}`, { method: "PUT", body: JSON.stringify({ data, comment }) }),
  reset: (section: "rubric" | "checklists" | "catalog", comment: string) =>
    askAdmin<AdminOverview>(`/api/admin/config/${section}/reset`, { method: "POST", body: JSON.stringify({ comment }) }),
  restore: (id: number, comment: string) =>
    askAdmin<AdminOverview>(`/api/admin/history/${id}/restore`, { method: "POST", body: JSON.stringify({ comment }) }),
  history: () => askAdmin<AdminHistoryItem[]>("/api/admin/history"),
  assessments: () => askAdmin<AdminAssessmentItem[]>("/api/admin/assessments"),
  deleteAssessments: (sel: { ids: number[] } | { all: true }) =>
    askAdmin<DeleteAssessmentsResult>("/api/admin/assessments/delete", { method: "POST", body: JSON.stringify(sel) }),
  users: () => askAdmin<AdminUser[]>("/api/admin/users"),
  addUser: (username: string, password: string) =>
    askAdmin<AdminUser[]>("/api/admin/users", { method: "POST", body: JSON.stringify({ username, password }) }),
  changePassword: (current: string, next: string) =>
    askAdmin<void>("/api/admin/password", { method: "POST", body: JSON.stringify({ current, new: next }) }),
};
