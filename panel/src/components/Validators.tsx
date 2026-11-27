import { Check, ChevronRight, Minus, X } from "lucide-react";
import type { Assessment } from "../api";
import { SEVERITY, findingLabel } from "../format";
import { Tooltip } from "./ui/Tooltip";
import { StepTitle } from "./ui/StepTitle";
import { Fold, FoldBody, FoldTitle } from "./ui/Fold";

/**
 * Validadores do parecer: cada conferência que o Atest.AI faz, com OK / NOK.
 * NOK = ao menos um apontamento do validador (absorvido também conta: o problema existe, só não desconta de novo).
 * Não conferido = a etapa não rodou (checklist devolvido, leitura do modelo falhou, Fase 2 desligada) ou não se aplica.
 */
export type ValidatorStatus = "ok" | "nok" | "skip";

export interface ValidatorRow {
  id: string;
  area: Area;
  label: string;
  question: string;
  status: ValidatorStatus;
  /** por que ficou NOK (rótulos dos apontamentos) ou por que não foi conferido */
  detail: string;
  /** apontamentos do validador (posição em p.findings), do mais grave ao mais leve */
  findings: number[];
  /** apontamentos marcados como "não procede" pela pessoa analista */
  unfounded: number;
}

type Area = "entrada" | "escopo" | "orcamento" | "evidencias";
const AREA_LABEL: Record<Area, string> = {
  entrada: "Entrada",
  escopo: "Escopo e categoria",
  orcamento: "Orçamento e solução",
  evidencias: "Fotos e documentos",
};

interface Spec {
  id: string;
  area: Area;
  label: string;
  question: string;
  kinds: string[];
  /** motivo para não conferir (null = conferido) */
  skip?: (p: Assessment) => string | null;
}

const reducer = (p: Assessment, r: string) => p.confidence_reducers.includes(r);
const noQuote = (p: Assessment) => (reducer(p, "unreadable_quote") ? "orçamento não lido" : null);
const noPhotos = (p: Assessment) => (reducer(p, "photos_not_analyzed") ? "fotos não analisadas pelo modelo" : null);
const noCoherence = (p: Assessment) =>
  reducer(p, "coherence_not_checked") ? "não conferido pelo modelo" : p.coherence === undefined || p.coherence === null ? "parecer anterior a esta conferência" : null;

const SPECS: Spec[] = [
  { id: "scope_clear", area: "escopo", label: "Escopo claro", question: "O texto permite saber o que fazer, onde e em quê?", kinds: ["vague_scope"] },
  {
    id: "category", area: "escopo", label: "Categoria e sintoma", question: "Correspondem ao problema que o texto e as evidências mostram?",
    // inclui a causa (vandalismo / desastre natural) vista nas evidências × a do chamado
    kinds: ["inconsistent_scope", "miscategorized_ticket", "cause_miscategorized"],
  },
  {
    id: "duplicate", area: "escopo", label: "Chamado duplicado", question: "Não há outro chamado da agência para o mesmo problema?",
    kinds: ["possible_duplicate_ticket"],
    skip: (p) => (reducer(p, "related_not_checked") ? "chamados da agência não comparados" : null),
  },
  {
    id: "services", area: "orcamento", label: "Serviços pedidos orçados", question: "Cada serviço pedido tem item no orçamento?",
    kinds: ["scope_not_quoted"], skip: noQuote,
  },
  {
    id: "items", area: "orcamento", label: "Itens aderentes", question: "Os itens são do escopo, sem duplicidade e com troca justificada?",
    kinds: ["out_of_scope_item", "duplicate_item", "unjustified_replacement", "spreadsheet_mismatch"], skip: noQuote,
  },
  {
    id: "quantities", area: "orcamento", label: "Quantidades", question: "As quantidades batem com o escopo e com as fotos?",
    kinds: ["quantity_above_expected", "unverifiable_quantity", "quantity_above_photos"], skip: noQuote,
  },
  {
    id: "prices", area: "orcamento", label: "Preços × LPU", question: "Os preços batem com a LPU ou com o preço de mercado?",
    kinds: ["price_above_reference", "price_above_market", "price_not_comparable", "similar_lpu_item", "relevant_amount_at_issue"], skip: noQuote,
  },
  {
    id: "solution", area: "orcamento", label: "Solução × problema", question: "A solução resolve o problema relatado?",
    kinds: ["solution_incoherent", "solution_partially_coherent"],
    skip: (p) => noCoherence(p) ?? (p.coherence?.solution_coherent === "undetermined" ? "sem descrição da solução nem evidência do que foi feito" : null),
  },
  {
    id: "photos", area: "evidencias", label: "Fotos × escopo", question: "As fotos mostram o local e o serviço pedidos?",
    kinds: ["photo_mismatch", "missing_after_photo", "after_photo_unconfirmed_location", "item_without_photo", "missing_before_photo", "unreadable_photo"],
    skip: noPhotos,
  },
  {
    id: "report", area: "evidencias", label: "Relatório × fotos", question: "As respostas do relatório em PDF batem com as fotos ao lado?",
    kinds: ["report_answer_contradicted"],
    skip: (p) => noPhotos(p) ?? (p.photos.some((f) => f.source) ? null : "sem relatório em PDF com fotos"),
  },
  {
    id: "integrity", area: "evidencias", label: "Integridade das fotos", question: "As fotos são deste chamado (não reaproveitadas, sem data anterior)?",
    kinds: ["reused_photo", "photo_dated_before"],
    skip: (p) => (p.phase < 2 ? "Fase 2 da régua desligada" : null),
  },
  {
    id: "documents", area: "evidencias", label: "Documentos", question: "Os documentos são legíveis, do chamado e com data no período?",
    kinds: ["unreadable_document", "document_mismatch", "document_date_inconsistent"],
    skip: (p) => (reducer(p, "documents_not_analyzed") ? "documentos não lidos pelo modelo" : (p.documents?.length ?? 0) === 0 ? "nenhum documento enviado" : null),
  },
];

const SEV_ORDER = { critical: 0, high: 1, medium: 2, low: 3 } as const;

/** Os validadores do parecer, na ordem do fluxo, com o status de cada um. */
export function validators(p: Assessment, unfounded: Set<string> = new Set()): ValidatorRow[] {
  const halted = p.score === null;
  const missing = p.checklist.requirements.filter((r) => !r.met);
  const rows: ValidatorRow[] = [
    {
      id: "checklist", area: "entrada", label: "Checklist mínimo", question: "Os documentos obrigatórios foram enviados?",
      status: p.checklist.complete ? "ok" : "nok",
      detail: p.checklist.complete ? "" : `Falta${missing.length === 1 ? "" : "m"}: ${missing.map((r) => r.description).join("; ")}`,
      findings: [], unfounded: 0,
    },
  ];
  const mapped = new Set(SPECS.flatMap((s) => s.kinds));
  const extra = [...new Set(p.findings.map((f) => f.kind).filter((k) => !mapped.has(k)))];
  const specs = extra.length
    ? [...SPECS, { id: "other", area: "evidencias" as Area, label: "Outras conferências", question: "Demais apontamentos da régua", kinds: extra }]
    : SPECS;
  for (const s of specs) {
    const idx = p.findings
      .map((f, i) => ({ f, i }))
      .filter(({ f }) => s.kinds.includes(f.kind))
      .sort((a, b) => Number(b.f.lock) - Number(a.f.lock) || SEV_ORDER[a.f.severity] - SEV_ORDER[b.f.severity])
      .map(({ i }) => i);
    const valid = idx.filter((i) => !unfounded.has(p.findings[i].kind));
    const why = halted ? "o chamado voltou no checklist, antes desta conferência" : s.skip?.(p) ?? null;
    const status: ValidatorStatus = valid.length ? "nok" : why && !idx.length ? "skip" : "ok";
    rows.push({
      id: s.id, area: s.area, label: s.label, question: s.question, status,
      detail: status === "nok" ? [...new Set(valid.map((i) => findingLabel(p.findings[i].kind)))].join("; ") : status === "skip" ? why ?? "" : idx.length ? "apontamento marcado como não procede" : "",
      findings: idx, unfounded: idx.length - valid.length,
    });
  }
  return rows;
}

const STATUS = {
  ok: { label: "OK", Icon: Check, chip: "bg-[#e3f2ea] text-ok", dot: "bg-ok" },
  nok: { label: "NOK", Icon: X, chip: "bg-[#f8e4e2] text-bad", dot: "bg-bad" },
  skip: { label: "N/C", Icon: Minus, chip: "bg-paper text-muted", dot: "bg-line" },
} as const;

function Counts({ rows }: { rows: ValidatorRow[] }) {
  const c = (s: ValidatorStatus) => rows.filter((r) => r.status === s).length;
  return (
    <span className="flex flex-wrap items-center gap-1.5 text-[13px]">
      <span className="rounded-full bg-[#e3f2ea] px-2 py-0.5 font-semibold text-ok tabular-nums">{c("ok")} OK</span>
      <span className={`rounded-full px-2 py-0.5 font-semibold tabular-nums ${c("nok") ? "bg-[#f8e4e2] text-bad" : "bg-paper text-muted"}`}>{c("nok")} NOK</span>
      {c("skip") > 0 && (
        <Tooltip content="Não conferido: a etapa não rodou ou não se aplica a este chamado.">
          <span className="cursor-help rounded-full bg-paper px-2 py-0.5 text-muted tabular-nums">{c("skip")} não conferido{c("skip") === 1 ? "" : "s"}</span>
        </Tooltip>
      )}
    </span>
  );
}

function Badge({ status }: { status: ValidatorStatus }) {
  const s = STATUS[status];
  return (
    <span className={`inline-flex w-14 shrink-0 items-center justify-center gap-1 rounded-md px-1.5 py-0.5 text-[12px] font-bold ${s.chip}`}>
      <s.Icon size={13} strokeWidth={3} /> {s.label}
    </span>
  );
}

/** Resumo: uma faixa com todos os validadores em pílulas OK / NOK; o NOK abre o apontamento no Completo. */
export function ValidatorsStrip({ p, unfounded, openDetail }: { p: Assessment; unfounded: Set<string>; openDetail: (i: number) => void }) {
  const rows = validators(p, unfounded);
  return (
    <Fold id="validators" data-tour="validators" className="rounded-xl border border-line bg-sheet p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <FoldTitle>Validadores</FoldTitle>
        <Counts rows={rows} />
      </div>
      <FoldBody>
      <ul className="mt-3 flex flex-wrap gap-2">
        {rows.map((r) => {
          const s = STATUS[r.status];
          const first = r.status === "nok" ? r.findings.find((i) => !unfounded.has(p.findings[i].kind)) : undefined;
          const tip = <><b>{r.label}</b> · {r.question}{r.detail && <><br />{r.detail}</>}{first !== undefined && <><br /><i>Clique para ver a evidência.</i></>}</>;
          const body = (
            <>
              <s.Icon size={14} strokeWidth={3} />
              <span>{r.label}</span>
              <span className="text-[11px] font-bold opacity-80">{s.label}</span>
            </>
          );
          return (
            <li key={r.id}>
              <Tooltip content={tip}>
                {first !== undefined ? (
                  <button type="button" onClick={() => openDetail(first)}
                    className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-[13px] font-medium ring-1 ring-bad/20 transition-shadow hover:ring-bad/60 ${s.chip}`}>
                    {body}
                  </button>
                ) : (
                  <span className={`flex cursor-help items-center gap-1.5 rounded-full px-3 py-1 text-[13px] font-medium ${s.chip}`}>{body}</span>
                )}
              </Tooltip>
            </li>
          );
        })}
      </ul>
      </FoldBody>
    </Fold>
  );
}

/** Completo: tabela por área, com a pergunta de cada validador, o motivo do NOK e o link para cada apontamento. */
export function ValidatorsTable({ p, n, unfounded, focusFinding }: { p: Assessment; n?: number; unfounded: Set<string>; focusFinding: (i: number) => void }) {
  const rows = validators(p, unfounded);
  const areas = (Object.keys(AREA_LABEL) as Area[]).map((a) => ({ a, rows: rows.filter((r) => r.area === a) })).filter((g) => g.rows.length);
  return (
    <Fold id="validators" data-tour="validators" className="rounded-xl border border-line bg-sheet">
      <div className="border-b border-line px-5 py-4 group-data-[fold=closed]/fold:border-0">
        <StepTitle n={n} sub="Cada conferência que o Atest.AI fez neste chamado. NOK = ao menos um apontamento; clique nele para ver a evidência." aside={<Counts rows={rows} />}>
          Validadores
        </StepTitle>
      </div>
      <FoldBody>
      <div className="divide-y divide-line">
        {areas.map(({ a, rows }) => (
          <div key={a}>
            <div className="bg-paper/50 px-5 py-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted">{AREA_LABEL[a]}</div>
            <ul className="divide-y divide-line/60">
              {rows.map((r) => (
                <li key={r.id} className={`grid gap-x-4 gap-y-1 px-5 py-2.5 sm:grid-cols-[auto_minmax(0,14rem)_1fr] sm:items-start ${r.status === "nok" ? "bg-[#fdf6f5]" : ""}`}>
                  <Badge status={r.status} />
                  <div className="min-w-0 text-sm">
                    <div className="font-medium">{r.label}</div>
                    <div className="text-[12px] leading-snug text-muted">{r.question}</div>
                  </div>
                  <div className="min-w-0 text-[13px]">
                    {r.status === "nok" && !r.findings.length ? (
                      <span className="text-bad">{r.detail}</span>
                    ) : r.status === "nok" ? (
                      <ul className="flex flex-wrap gap-1.5">
                        {r.findings.map((i) => {
                          const f = p.findings[i];
                          const off = unfounded.has(f.kind);
                          return (
                            <li key={i}>
                              <button type="button" onClick={() => focusFinding(i)}
                                className={`flex items-center gap-1 rounded-md border px-2 py-0.5 text-left transition-colors hover:border-blueprint hover:text-blueprint ${off ? "border-line text-muted line-through" : "border-line"}`}>
                                <span className="size-2 shrink-0 rounded-full" style={{ background: off ? "var(--color-muted)" : SEVERITY[f.severity].color }} />
                                {f.description}{f.absorbed_by && <span className="text-muted"> (absorvido)</span>}
                                <ChevronRight size={12} />
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                    ) : (
                      <span className="text-muted">
                        {r.status === "ok" ? (r.detail ? `OK: ${r.detail}` : "Sem apontamentos") : `Não conferido: ${r.detail}`}
                      </span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      </FoldBody>
    </Fold>
  );
}
