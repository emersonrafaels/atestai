// Contratos da API (espelham os modelos Pydantic de atest/domain.py e atest/api.py)

export type Recommendation =
  | "approve"
  | "approve_with_caveats"
  | "return_to_supplier"
  | "return_locked"
  | "detailed_review"
  | "checklist_returned";

export type Stage = "checklist" | "scope" | "quote" | "photos" | "score" | "assessment" | "done";

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
  scope: string;
  branch: string;
  environment: string;
  supplier: string;
  quoted_value: number | null;
  moment: "quote" | "execution";
  maintenance_type: string;
  n_photos: number;
  expected: Expected | null;
}

export interface QuoteItem {
  n: number;
  description: string;
  unit: string;
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

export interface Option {
  value: string;
  label: string;
}

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
  providers: string[];
  missing_keys: string[];
  signature: string;
  validation: { dataset: string; accuracy_min: number; kappa_min: number; finding_f1_min: number; score_error_max: number };
  rubric?: RubricInfo;
  models?: ModelOption[];
  keyed_providers?: string[];
}

/** Modelo sugerido nos campos de modelo (tabela de preços + configurados). */
export interface ModelOption {
  id: string;
  provider: string;
  name: string;
  input_price: number | null;
  output_price: number | null;
}

export type ValidationKind = "scope" | "quote" | "photos";

/** Régua do score (config/rubric.toml), usada pelo painel para explicar de onde vem cada ponto. */
export interface RubricInfo {
  weights: Record<ValidationKind, number>;
  discount_by_severity: Record<Finding["severity"], number>;
  bands: { score_min: number; recommendation: Recommendation }[];
  confidence: { medium_with_n_reducers: number; low_with_n_reducers: number };
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
}

async function ask<T>(url: string, init?: RequestInit): Promise<T> {
  const json = !(init?.body instanceof FormData);
  const r = await fetch(url, { ...(json ? { headers: { "Content-Type": "application/json" } } : {}), ...init });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const body = await r.json();
      if (body.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
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
