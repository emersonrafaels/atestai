/**
 * Filtros da lista de chamados (aba Análise): busca livre e filtros por campo. Tudo no navegador, sobre o
 * resumo de /api/tickets; o estado fica no localStorage para sobreviver ao recarregar a página.
 */
import type { Assessment, Recommendation, TicketSummary } from "./api";
import { REC, STAGE_SHORT, MAINTENANCE_LABEL, envLabel, brl } from "./format";

export type VerdictFilter = "" | "none" | "any" | "dup" | "diverged" | Recommendation;

export interface ListFilters {
  /** busca livre: nº do chamado (vários separados por espaço ou vírgula), agência, fornecedor, texto */
  q: string;
  /** agência: nome (trecho) ou código (com ou sem zeros à esquerda) */
  branch: string;
  stage: "" | "quote" | "execution";
  kind: "" | "corrective" | "preventive";
  category: string;
  supplier: string;
  environment: string;
  verdict: VerdictFilter;
  blocks: "" | "yes" | "no" | "unknown";
  photos: "" | "with" | "without";
  minValue: string;
  maxValue: string;
  /** abertura, AAAA-MM-DD */
  from: string;
  to: string;
}

export const EMPTY_FILTERS: ListFilters = {
  q: "", branch: "", stage: "", kind: "", category: "", supplier: "", environment: "", verdict: "",
  blocks: "", photos: "", minValue: "", maxValue: "", from: "", to: "",
};

const STORAGE_KEY = "atest.list.filters";

export function loadFilters(): ListFilters {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY_FILTERS;
    const parsed = JSON.parse(raw) as Partial<ListFilters>;
    const out = { ...EMPTY_FILTERS };
    for (const k of Object.keys(EMPTY_FILTERS) as (keyof ListFilters)[]) {
      if (typeof parsed[k] === "string") (out as Record<string, string>)[k] = parsed[k] as string;
    }
    return out;
  } catch {
    return EMPTY_FILTERS;
  }
}

export function saveFilters(f: ListFilters) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(f));
  } catch { /* armazenamento indisponível */ }
}

/** Minúsculas e sem acento, para comparar "Guarulhos" com "guarulhos" e "Cambuí" com "cambui". */
export const norm = (s: string | null | undefined) =>
  (s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();

/** Nº de chamado na busca: 5 dígitos ou mais (códigos de agência têm até 4). */
const isTicketToken = (t: string) => /^\d{5,}$/.test(t);

/** Valor digitado em reais ("1.500,50", "1500.5", "2 mil" não) → número; vazio ou inválido = null. */
export function parseMoney(v: string): number | null {
  const t = v.trim().replace(/[R$\s]/g, "");
  if (!t) return null;
  // vírgula = decimal brasileiro; ponto seguido de grupos de 3 dígitos ("5.000", "1.250.000") = milhar
  const brazilian = t.includes(",") || /^\d{1,3}(\.\d{3})+$/.test(t);
  const n = Number(brazilian ? t.replace(/\./g, "").replace(",", ".") : t);
  return Number.isFinite(n) ? n : null;
}

/** A agência bate com o que foi digitado: código (418 = 0418) ou trecho do nome/rótulo. */
export function branchMatches(c: TicketSummary, query: string): boolean {
  const q = query.trim();
  if (!q) return true;
  const code = c.branch_code ?? "";
  if (/^\d{1,4}$/.test(q)) return !!code && (Number(code) === Number(q) || code.startsWith(q));
  // escolhido na lista de sugestões: o rótulo inteiro
  if (q === c.branch) return true;
  const nq = norm(q).replace(/^ag(encia|\.)?\s+/, "");
  return norm(c.branch_name).includes(nq) || norm(c.branch).includes(nq);
}

/** Parecer que vale para o filtro: o desta execução, se houver; senão o último gravado. */
export interface Verdict {
  recommendation: Recommendation | null;
  duplicates: string[];
}

export function verdictOf(c: TicketSummary, a: Assessment | null | undefined, inRun: boolean): Verdict {
  if (a) return { recommendation: a.recommendation, duplicates: (a.related?.tickets ?? []).filter((r) => r.flagged).map((r) => r.ticket_id) };
  if (inRun) return { recommendation: null, duplicates: [] };
  return { recommendation: c.last?.recommendation ?? null, duplicates: c.last?.duplicate_of ?? [] };
}

/** Texto onde a busca livre procura (sem acento, minúsculo). */
function haystack(c: TicketSummary): string {
  return norm([
    c.ticket_id, c.branch, c.branch_name, c.branch_code, c.supplier, c.category_label, c.symptom_label, c.scope,
    c.solution_description, c.scenario?.title, c.scenario?.id, envLabel(c.environment), c.status, c.workstream,
  ].filter(Boolean).join(" • "));
}

export function matches(c: TicketSummary, f: ListFilters, v: Verdict): boolean {
  // busca livre: números de chamado formam um "ou"; as demais palavras, um "e"
  const tokens = f.q.split(/[\s,;]+/).map((t) => t.trim()).filter(Boolean);
  if (tokens.length) {
    const ids = tokens.filter(isTicketToken);
    const words = tokens.filter((t) => !isTicketToken(t));
    if (ids.length && !ids.some((id) => c.ticket_id.includes(id))) return false;
    if (words.length) {
      const h = haystack(c);
      for (const w of words) {
        // número curto: código de agência exato (418 = 0418) ou trecho de qualquer campo
        if (/^\d{1,4}$/.test(w) && c.branch_code && Number(c.branch_code) === Number(w)) continue;
        if (!h.includes(norm(w))) return false;
      }
    }
  }
  if (!branchMatches(c, f.branch)) return false;
  if (f.stage && c.moment !== f.stage) return false;
  if (f.kind && c.maintenance_type !== f.kind) return false;
  if (f.category && c.category !== f.category) return false;
  if (f.supplier && c.supplier !== f.supplier) return false;
  if (f.environment && c.environment !== f.environment) return false;
  if (f.blocks) {
    const b = c.blocks_opening;
    if (f.blocks === "yes" && b !== true) return false;
    if (f.blocks === "no" && b !== false) return false;
    if (f.blocks === "unknown" && b !== null && b !== undefined) return false;
  }
  if (f.photos === "with" && c.n_photos === 0) return false;
  if (f.photos === "without" && c.n_photos > 0) return false;
  const min = parseMoney(f.minValue);
  const max = parseMoney(f.maxValue);
  if (min !== null && (c.quoted_value ?? null) === null) return false;
  if (min !== null && (c.quoted_value ?? 0) < min) return false;
  if (max !== null && (c.quoted_value ?? null) === null) return false;
  if (max !== null && (c.quoted_value ?? 0) > max) return false;
  if (f.from && (!c.opened_at || c.opened_at < f.from)) return false;
  if (f.to && (!c.opened_at || c.opened_at > f.to)) return false;
  if (f.verdict) {
    const r = v.recommendation;
    if (f.verdict === "none" && r) return false;
    if (f.verdict === "any" && !r) return false;
    if (f.verdict === "dup" && !v.duplicates.length) return false;
    if (f.verdict === "diverged" && !(r && c.expected && c.expected.recommendation !== r)) return false;
    if (f.verdict in REC && r !== f.verdict) return false;
  }
  return true;
}

export const VERDICT_LABEL: Record<Exclude<VerdictFilter, "" | Recommendation>, string> = {
  none: "Ainda não analisado",
  any: "Já analisado",
  dup: "Possível duplicado",
  diverged: "Diferente do gabarito",
};

const BLOCKS_LABEL = { yes: "Impede a abertura", no: "Não impede a abertura", unknown: "Impede a abertura: não informado" };
const PHOTOS_LABEL = { with: "Com fotos", without: "Sem fotos" };
const fmtDate = (d: string) => d.split("-").reverse().join("/");

/** Um selo por filtro ativo (rótulo e o que apagar ao fechar), na ordem em que aparecem no painel. */
export function activeChips(f: ListFilters, names: { category: (v: string) => string }): { key: (keyof ListFilters)[]; label: string }[] {
  const out: { key: (keyof ListFilters)[]; label: string }[] = [];
  if (f.q.trim()) out.push({ key: ["q"], label: `Busca: “${f.q.trim()}”` });
  if (f.branch.trim()) out.push({ key: ["branch"], label: `Agência: ${f.branch.trim()}` });
  if (f.stage) out.push({ key: ["stage"], label: STAGE_SHORT[f.stage] ?? f.stage });
  if (f.kind) out.push({ key: ["kind"], label: MAINTENANCE_LABEL[f.kind] ?? f.kind });
  if (f.category) out.push({ key: ["category"], label: names.category(f.category) });
  if (f.supplier) out.push({ key: ["supplier"], label: `Fornecedor: ${f.supplier}` });
  if (f.environment) out.push({ key: ["environment"], label: `Local: ${envLabel(f.environment)}` });
  if (f.verdict) out.push({ key: ["verdict"], label: f.verdict in REC ? `Parecer: ${REC[f.verdict as Recommendation].label}` : VERDICT_LABEL[f.verdict as keyof typeof VERDICT_LABEL] });
  if (f.blocks) out.push({ key: ["blocks"], label: BLOCKS_LABEL[f.blocks] });
  if (f.photos) out.push({ key: ["photos"], label: PHOTOS_LABEL[f.photos] });
  const min = parseMoney(f.minValue);
  const max = parseMoney(f.maxValue);
  if (min !== null || max !== null) {
    out.push({
      key: ["minValue", "maxValue"],
      label: min !== null && max !== null ? `Valor: ${brl(min)} a ${brl(max)}` : min !== null ? `Valor ≥ ${brl(min)}` : `Valor ≤ ${brl(max)}`,
    });
  }
  if (f.from || f.to) {
    out.push({
      key: ["from", "to"],
      label: f.from && f.to ? `Aberto de ${fmtDate(f.from)} a ${fmtDate(f.to)}` : f.from ? `Aberto desde ${fmtDate(f.from)}` : `Aberto até ${fmtDate(f.to)}`,
    });
  }
  return out;
}

/** Filtros do painel "Mais filtros" ativos (a busca livre fica sempre à vista e não conta). */
export const advancedCount = (f: ListFilters) => activeChips(f, { category: (v) => v }).filter((c) => c.key[0] !== "q").length;

export const hasFilters = (f: ListFilters) => activeChips(f, { category: (v) => v }).length > 0;
