import { Check, ChevronRight, Copy, FileText, FileWarning, Link2, Lock, MapPin, ThumbsDown, Undo2, X, Zap } from "lucide-react";
import type { Assessment, RelatedTicket, RubricInfo } from "../api";
import { REC, SEVERITY, CONFIDENCE_LABEL, CONFIDENCE_TEXT, brl } from "../format";
import { locate } from "../evidence";
import { whereLabel, type GoTo } from "./FindingEvidence";
import { tint, ScoreGauge } from "./ScoreBadge";
import type { ExplainKind } from "./ExplainDialog";
import { actions, highlight, SentenceList, splitLead, type TicketLinks } from "./ui/RichText";
import { Tooltip } from "./ui/Tooltip";
import { ValidatorsStrip } from "./Validators";
import { Fold, FoldBody, FoldTitle } from "./ui/Fold";

export type ParecerMode = "quick" | "full";
const MODE_KEY = "atest.parecer.mode";
/** Evento para trocar o modo de fora (ex.: o tour guiado abre o Completo, onde estão as seções que ele explica). */
export const PARECER_MODE_EVENT = "atest:parecer-mode";

export function loadParecerMode(): ParecerMode {
  try { return localStorage.getItem(MODE_KEY) === "full" ? "full" : "quick"; } catch { return "quick"; }
}
export function saveParecerMode(m: ParecerMode) {
  try { localStorage.setItem(MODE_KEY, m); } catch { /* armazenamento indisponível */ }
}

/** Resumo × Completo, no topo da aba Parecer: duas opções grandes, com ícone e o que cada uma mostra. */
export function ModeSwitch({ mode, setMode }: { mode: ParecerMode; setMode: (m: ParecerMode) => void }) {
  const opt = (m: ParecerMode, Icon: typeof Zap, label: string, sub: string, hint: string) => {
    const on = mode === m;
    return (
      <Tooltip content={hint} className="flex min-w-[220px] flex-1 sm:max-w-[340px]">
        <button role="tab" aria-selected={on} onClick={() => setMode(m)}
          className={`flex w-full items-center gap-3 rounded-lg border-2 px-4 py-2.5 text-left transition-colors ${
            on ? "border-blueprint bg-blueprint text-white shadow-md" : "border-line bg-sheet text-ink hover:border-blueprint/60 hover:bg-blueprint-soft"}`}>
          <span className={`flex size-9 shrink-0 items-center justify-center rounded-lg ${on ? "bg-white/20" : "bg-blueprint-soft text-blueprint"}`}>
            <Icon size={18} />
          </span>
          <span className="min-w-0">
            <span className="block text-[15px] font-bold leading-tight">{label}</span>
            <span className={`block text-[12px] leading-snug ${on ? "text-white/85" : "text-muted"}`}>{sub}</span>
          </span>
          {on && <Check size={18} strokeWidth={3} className="ml-auto shrink-0" />}
        </button>
      </Tooltip>
    );
  };
  return (
    <div role="tablist" aria-label="Como ver o parecer" className="flex flex-wrap gap-2.5">
      {opt("quick", Zap, "Resumo", "O essencial para decidir rápido", "O essencial para decidir: recomendação, pontos de atenção e a decisão")}
      {opt("full", FileText, "Completo", "Cada evidência, na ordem do fluxo", "Tudo: checklist, racional do engenheiro, conta do score e cada apontamento com a evidência")}
    </div>
  );
}

const SEV_ORDER = { critical: 0, high: 1, medium: 2, low: 3 } as const;

interface Props {
  p: Assessment;
  rubric: RubricInfo;
  flagged: RelatedTicket[];
  shown: RelatedTicket[];
  links?: TicketLinks;
  onCompare: (r: RelatedTicket) => void;
  onExplain: (k: ExplainKind) => void;
  goTo: GoTo;
  unfounded: Set<string>;
  toggleUnfounded: (kind: string) => void;
  /** abre o Completo com o apontamento em foco */
  openDetail: (index: number) => void;
  copy: () => void;
  copied: boolean;
  duplicateBanners: React.ReactNode;
}

/**
 * Parecer em modo Resumo: o que a pessoa analista precisa para decidir em um minuto. Recomendação e números que pesam,
 * o resumo frase a frase, os pontos de atenção em uma linha cada (do mais grave ao mais leve) e a mensagem ao
 * fornecedor. A decisão vem logo abaixo (mesmo painel do Completo).
 */
export function QuickView({ p, rubric, flagged, shown, links, onCompare, onExplain, goTo, unfounded, toggleUnfounded, openDetail, copy, copied, duplicateBanners }: Props) {
  const rec = REC[p.recommendation];
  const missing = p.checklist.requirements.filter((r) => !r.met);
  const { lead, body } = splitLead(p.summary);
  const norm = (s: string) => s.toLowerCase().replace(/^recomendo\s+/, "").replace(/[.:!]+$/, "").trim();
  const showLead = lead && norm(lead) !== norm(rec.label);
  // pontos de atenção: trava primeiro, depois por severidade; apontamentos absorvidos ficam no Completo
  const points = p.findings
    .map((f, idx) => ({ f, idx }))
    .filter(({ f }) => !f.absorbed_by)
    .sort((a, b) => Number(b.f.lock) - Number(a.f.lock) || SEV_ORDER[a.f.severity] - SEV_ORDER[b.f.severity]);
  const hidden = p.findings.length - points.length;
  const steps = p.supplier_message ? actions(p.supplier_message) : [];

  return (
    <>
      {/* 1. a recomendação e os números que pesam */}
      <section data-tour="verdict" className="rounded-xl border border-line border-l-4 bg-sheet p-5" style={{ borderLeftColor: rec.mark }}>
        {flagged.length > 0 && <div className="mb-3 space-y-2">{duplicateBanners}</div>}
        <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
          <div className="self-center sm:self-start">
            <ScoreGauge score={p.score} recommendation={p.recommendation} rubric={rubric} size={132} locked={p.findings.some((f) => f.lock)} />
          </div>
          <div className="min-w-0 flex-1 space-y-2.5">
            <h2 className="largo text-2xl font-bold" style={{ color: rec.color }}>
              <button type="button" onClick={() => onExplain("recommendation")} aria-haspopup="dialog" className="group inline-flex flex-wrap items-center gap-x-2.5 gap-y-1 text-left">
                <span className="decoration-2 decoration-dotted underline-offset-4 group-hover:underline">{rec.label}</span>
                <span className="inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-[12px] font-semibold ring-1 ring-current/20" style={{ background: tint(p.recommendation, 12) }}>
                  Por quê? <ChevronRight size={13} />
                </span>
              </button>
            </h2>
            <p className="text-sm text-muted">{p.recommendation_reason}</p>
            <ul className="flex flex-wrap gap-2 text-[13px]">
              <li className={`flex items-center gap-1 rounded-full px-2.5 py-0.5 font-semibold ${p.checklist.complete ? "bg-[#e3f2ea] text-ok" : "bg-[#f8e4e2] text-bad"}`}>
                {p.checklist.complete ? <Check size={13} /> : <X size={13} />} Checklist {p.checklist.complete ? "completo" : `faltam ${missing.length}`}
              </li>
              {p.confidence && (
                <li>
                  <button type="button" onClick={() => onExplain("confidence")} className="flex items-center gap-1 rounded-full bg-paper px-2.5 py-0.5 hover:ring-1 hover:ring-line">
                    Confiança <b className={CONFIDENCE_TEXT[p.confidence]}>{CONFIDENCE_LABEL[p.confidence]}</b>
                  </button>
                </li>
              )}
              <li className="rounded-full bg-paper px-2.5 py-0.5">
                {p.findings.length ? <><b>{p.findings.length}</b> apontamento{p.findings.length === 1 ? "" : "s"}</> : "Sem apontamentos"}
              </li>
              {p.amount_at_issue > 0 && (
                <li className="rounded-full bg-[#fbefed] px-2.5 py-0.5 text-bad">
                  Divergente <b className="tabular-nums">{brl(p.amount_at_issue)}</b> ({p.amount_at_issue_pct.toFixed(0)}%)
                </li>
              )}
            </ul>
            {missing.length > 0 && (
              <p className="flex items-start gap-1.5 rounded-md bg-[#fbefed] px-2.5 py-1.5 text-[13px] text-bad">
                <FileWarning size={14} className="mt-0.5 shrink-0" /> Não enviado: {missing.map((r) => r.description).join("; ")}
              </p>
            )}
          </div>
        </div>
        {(showLead || body) && (
          <div className="mt-4 border-t border-line pt-3">
            {showLead && <p className="mb-1.5 font-semibold" style={{ color: rec.color }}>{lead}</p>}
            <SentenceList text={body} onItems={(items) => goTo("quote", { items })} tickets={links} className="max-w-[80ch] text-[15px]" />
          </div>
        )}
        {shown.length > 0 && (
          <p className="mt-3 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[13px] text-muted">
            <Link2 size={14} className="text-warn" /> Relacionado{shown.length === 1 ? "" : "s"} na agência:
            {shown.map((r) => (
              <button key={r.ticket_id} type="button" onClick={() => onCompare(r)} className="rounded-full border border-warn/40 bg-[#fdf6e4] px-2 py-0.5 font-medium text-ink hover:border-warn">
                {r.ticket_id} · {r.probability}%
              </button>
            ))}
          </p>
        )}
      </section>

      {/* 2. validadores: cada conferência com OK / NOK (o NOK abre a evidência no Completo) */}
      <ValidatorsStrip p={p} unfounded={unfounded} openDetail={openDetail} />

      {/* 3. pontos de atenção: uma linha por apontamento */}
      {points.length > 0 && (
        <Fold id="points" data-tour="findings" className="rounded-xl border border-line bg-sheet">
          <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-5 py-3 group-data-[fold=closed]/fold:border-0">
            <FoldTitle>Pontos de atenção ({points.length})</FoldTitle>
            <span className="text-[13px] text-muted">Do mais grave ao mais leve. Marque “Não procede” se algum estiver errado.{hidden > 0 && ` ${hidden} absorvido${hidden === 1 ? "" : "s"} só no Completo.`}</span>
          </div>
          <FoldBody>
          <ul className="divide-y divide-line/70">
            {points.map(({ f, idx }) => {
              const off = unfounded.has(f.kind);
              const where = whereLabel(locate(f, p), p);
              return (
                <li key={idx} className={`flex flex-wrap items-start gap-x-3 gap-y-1.5 px-5 py-2.5 ${off ? "opacity-55" : ""}`}>
                  <span className="mt-0.5 w-16 shrink-0 rounded px-1.5 py-0.5 text-center text-[11px] font-semibold text-white" style={{ background: off ? "var(--color-muted)" : SEVERITY[f.severity].color }}>
                    {SEVERITY[f.severity].label}
                  </span>
                  <div className="min-w-0 flex-1 text-sm">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                      <span className={`font-medium ${off ? "line-through decoration-ink/40" : ""}`}>{f.description}</span>
                      {f.lock && <span className="flex items-center gap-1 rounded bg-[#ece6f6] px-1.5 text-[11px] font-semibold text-lock"><Lock size={11} /> Trava</span>}
                      {f.amount_at_issue > 0 && <span className="text-[12px] text-bad">{brl(f.amount_at_issue)}</span>}
                    </div>
                    <p className="line-clamp-2 text-[13px] leading-snug text-muted">{highlight(f.evidence, (items) => goTo("quote", { items }))}</p>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-3 text-[12px]">
                      {where && <span className="flex items-center gap-1 text-blueprint"><MapPin size={12} /> {where}</span>}
                      <button type="button" onClick={() => openDetail(idx)} className="flex items-center gap-0.5 font-medium text-blueprint hover:underline">
                        Ver evidência <ChevronRight size={12} />
                      </button>
                    </div>
                  </div>
                  <button type="button" onClick={() => toggleUnfounded(f.kind)} aria-pressed={off}
                    className={`flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-[12px] font-medium transition-colors ${off ? "border-line bg-paper text-ink" : "border-line text-muted hover:border-bad hover:bg-[#fbefed] hover:text-bad"}`}>
                    {off ? <><Undo2 size={12} /> Desfazer</> : <><ThumbsDown size={12} /> Não procede</>}
                  </button>
                </li>
              );
            })}
          </ul>
          </FoldBody>
        </Fold>
      )}

      {/* 4. mensagem ao fornecedor, compacta */}
      {steps.length > 0 && (
        <Fold id="quick-message" className="rounded-xl border border-line bg-sheet p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <FoldTitle>Mensagem sugerida ao fornecedor</FoldTitle>
            <button onClick={copy} className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-sm transition-colors ${copied ? "border-ok bg-[#e3f2ea] text-ok" : "border-line hover:bg-paper"}`}>
              {copied ? <Check size={14} /> : <Copy size={14} />}{copied ? "Copiada" : "Copiar"}
            </button>
          </div>
          <FoldBody>
          {unfounded.size > 0 && <p className="mt-2 rounded-md bg-[#fdf6e4] px-3 py-1.5 text-[13px]">Você marcou apontamentos como não procedentes: retire-os da mensagem antes de enviar.</p>}
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
            {steps.map((a, i) => <li key={i}>{highlight(a, (items) => goTo("quote", { items }))}</li>)}
          </ol>
          </FoldBody>
        </Fold>
      )}
    </>
  );
}
