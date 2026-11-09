import { ArrowDown, Check, ChevronDown, Copy, Lock, MapPin, ShieldAlert, ThumbsDown, Undo2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Comparison, Assessment, RubricInfo, TicketDetail } from "../api";
import { brl, brl4, REC, SEVERITY, FINDING_LABELS, CONFIDENCE_LABEL, VALIDATIONS, VALIDATION_LABEL, VALIDATION_SHORT, explainFindings, pts } from "../format";
import { locate } from "../evidence";
import { Stamp } from "./Stamp";
import { DecisionPanel } from "./DecisionPanel";
import { ScoreBreakdown } from "./ScoreBreakdown";
import { FindingEvidence, whereLabel, type GoTo } from "./FindingEvidence";
import type { LightboxItem } from "./ui/Lightbox";
import { InfoBox } from "./ui/InfoBox";
import { InfoTip, Tooltip } from "./ui/Tooltip";
import { StepTitle } from "./ui/StepTitle";

interface Props {
  p: Assessment;
  comparison: Comparison | null;
  rubric: RubricInfo;
  ticket: TicketDetail | null;
  openPhoto: (items: LightboxItem[], index: number) => void;
  goTo: GoTo;
  openTicket?: (id: string) => void;
}

/**
 * Parecer na ordem do próprio fluxo: checklist mínimo → recomendação → conta do score → apontamentos →
 * mensagem ao fornecedor → decisão da pessoa analista (por último, depois de ler tudo).
 */
export function AssessmentTab({ p, comparison, rubric, ticket, openPhoto, goTo, openTicket }: Props) {
  const [copied, setCopied] = useState(false);
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [unfounded, setUnfounded] = useState<Set<string>>(new Set());
  const [registered, setRegistered] = useState(true);
  const [decisionVisible, setDecisionVisible] = useState(false);
  const decisionRef = useRef<HTMLDivElement>(null);

  const copy = async () => {
    await navigator.clipboard.writeText(p.supplier_message);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };
  const toggleOpen = (i: number) => setOpen((s) => { const n = new Set(s); if (n.has(i)) n.delete(i); else n.add(i); return n; });
  const toggleUnfounded = useCallback((k: string) => setUnfounded((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; }), []);
  const focusFinding = useCallback((i: number) => {
    setOpen((s) => new Set(s).add(i));
    requestAnimationFrame(() => {
      const el = document.getElementById(`finding-${i}`);
      el?.scrollIntoView({ block: "center", behavior: "smooth" });
      el?.classList.remove("piscar");
      void el?.offsetWidth;
      el?.classList.add("piscar");
    });
  }, []);

  // barra flutuante "decisão pendente" some quando a seção da decisão está na tela
  useEffect(() => {
    const el = decisionRef.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setDecisionVisible(e.isIntersecting), { threshold: 0.15 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const impacts = explainFindings(p.findings, rubric);
  const withImpact = p.findings.map((f, idx) => ({ f, imp: impacts[idx], idx }));
  const byValidation = VALIDATIONS.map((v) => ({ v, items: withImpact.filter((x) => x.f.validation === v) })).filter((g) => g.items.length);
  const totalScorePts = impacts.reduce((s, i) => s + i.scorePts, 0);
  const countByKind = p.findings.reduce<Record<string, number>>((a, f) => ({ ...a, [f.kind]: (a[f.kind] ?? 0) + 1 }), {});
  const missing = p.checklist.requirements.filter((r) => !r.met);
  let n = 0;

  return (
    <div className="space-y-5">
      {/* 1. checklist mínimo: é a primeira etapa do fluxo, então vem primeiro */}
      <section data-tour="checklist" className="rounded-xl border border-line bg-sheet p-5">
        <StepTitle n={++n}
          sub="Documentos obrigatórios para esta categoria. Sem eles, o chamado volta antes de qualquer análise."
          aside={
            <span className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold ${p.checklist.complete ? "bg-[#e3f2ea] text-ok" : "bg-[#f8e4e2] text-bad"}`}>
              {p.checklist.complete ? <Check size={15} /> : <X size={15} />}
              {p.checklist.complete ? "Completo" : `Falta${missing.length === 1 ? "" : "m"} ${missing.length}`} · {p.checklist.uploaded}/{p.checklist.total}
            </span>
          }>
          Checklist mínimo <InfoTip term="checklist" />
        </StepTitle>
        <div className="mt-3 h-1.5 rounded-full bg-paper">
          <div className={`h-1.5 rounded-full ${p.checklist.complete ? "bg-ok" : "bg-bad"}`} style={{ width: `${p.checklist.total ? (100 * p.checklist.uploaded) / p.checklist.total : 0}%` }} />
        </div>
        <ul className="mt-3 grid gap-1.5 text-sm md:grid-cols-2">
          {p.checklist.requirements.map((r) => (
            <li key={r.id} className={`flex items-start gap-2 rounded-md px-2 py-1 ${r.met ? "" : "bg-[#fbefed] text-bad"}`}>
              {r.met ? <Check size={16} className="mt-0.5 shrink-0 text-ok" /> : <X size={16} className="mt-0.5 shrink-0" />}
              <span>
                {r.description}
                {r.met && (
                  <Tooltip content={r.attachments.length ? `Atendido por: ${r.attachments.join(", ")}` : "Atendido"}>
                    <span className="cursor-help text-muted"> · {r.attachments.length} anexo{r.attachments.length === 1 ? "" : "s"}</span>
                  </Tooltip>
                )}
                {!r.met && <span className="font-medium"> · não enviado</span>}
              </span>
            </li>
          ))}
        </ul>
      </section>

      {/* 2. recomendação */}
      <section data-tour="verdict" className="rounded-xl border border-line bg-sheet p-5">
        <StepTitle n={++n}>Parecer do Atest.AI</StepTitle>
        <div className="mt-3 flex flex-col gap-6 md:flex-row md:items-center">
          <Tooltip className="inline-flex self-center" content={p.score !== null
            ? `Score ${p.score} de 100 → ${REC[p.recommendation].label}. Veja abaixo como cada ponto foi calculado.`
            : `${REC[p.recommendation].label}: sem score, porque o chamado parou antes das validações.`}>
            <Stamp recommendation={p.recommendation} score={p.score} ticketId={p.ticket_id} data={p.generated_at} size={190} />
          </Tooltip>
          <div className="min-w-0 flex-1 space-y-3">
            <h2 className="largo text-2xl font-bold" style={{ color: REC[p.recommendation].color }}>{REC[p.recommendation].label}</h2>
            <p className="text-sm font-medium text-muted">Por quê: <span className="text-ink">{p.recommendation_reason}</span></p>
            <p className="text-[15px] leading-relaxed">{p.summary}</p>
            <dl className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
              {p.score !== null && (
                <Fact label="Score" help={<InfoTip term="score" />}><b className="tabular-nums">{p.score}</b><span className="text-muted">/100</span></Fact>
              )}
              {p.confidence && (
                <Fact label="Confiança" help={<InfoTip term="confidence" text={p.confidence_reducers.length ? `Redutores neste chamado: ${p.confidence_reducers.map((r) => FINDING_LABELS[r] ?? r).join(", ")}.` : "Nenhum redutor neste chamado."} />}>
                  <b className={p.confidence === "high" ? "text-ok" : p.confidence === "medium" ? "text-warn" : "text-bad"}>{CONFIDENCE_LABEL[p.confidence] ?? p.confidence}</b>
                </Fact>
              )}
              {p.amount_at_issue > 0 && (
                <Fact label="Valor em questão" help={<InfoTip term="amount" />}><b className="tabular-nums text-bad">{brl(p.amount_at_issue)}</b><span className="text-muted"> ({p.amount_at_issue_pct.toFixed(0)}% do orçado)</span></Fact>
              )}
              <Fact label="Custo da análise"><b>{p.mode === "api" ? brl4(p.cost_brl) : "simulado"}</b></Fact>
            </dl>
            {comparison && (
              <p className={`inline-flex flex-wrap items-center gap-1.5 rounded-md px-2.5 py-1 text-sm ${comparison.recommendation_ok ? "bg-[#e3f2ea] text-ok" : "bg-[#f8e4e2] text-bad"}`}>
                {comparison.recommendation_ok ? <Check size={15} /> : <X size={15} />}
                Gabarito: {REC[comparison.expected].label}{comparison.expected_score !== null ? `, score ${comparison.expected_score}` : ""}
                {comparison.missed.length > 0 && ` · faltou ${comparison.missed.map((t) => FINDING_LABELS[t] ?? t).join(", ")}`}
                {comparison.extra.length > 0 && ` · a mais: ${comparison.extra.map((t) => FINDING_LABELS[t] ?? t).join(", ")}`}
                <InfoTip term="ground_truth" />
              </p>
            )}
          </div>
        </div>
      </section>

      {/* 3. a conta do score */}
      <section data-tour="score-breakdown" className="rounded-xl border border-line bg-sheet p-5">
        <StepTitle n={++n} sub={p.score !== null
          ? "Cada validação começa com 100 pontos e perde pontos a cada apontamento. O score é a média ponderada das três notas."
          : undefined}>
          Como o score foi calculado <InfoTip term="bands" />
        </StepTitle>
        <div className="mt-4">
          {p.score !== null ? <ScoreBreakdown p={p} rubric={rubric} /> : (
            <InfoBox tone="tip">Sem score: o chamado voltou no checklist mínimo, antes das validações de escopo, orçamento e fotos.</InfoBox>
          )}
        </div>
      </section>

      {/* 4. apontamentos: clicáveis, mostram onde está o erro; "não procede" alimenta a decisão */}
      {p.findings.length > 0 && (
        <section data-tour="findings" className="rounded-xl border border-line bg-sheet">
          <div className="border-b border-line px-5 py-4">
            <StepTitle n={++n}
              sub={<>Somados, tiram <b className="text-ink tabular-nums">{pts(totalScorePts)}</b> pontos do score. <b className="text-ink">Clique num apontamento</b> para ver a linha do orçamento ou a foto com o problema.</>}
              aside={
                <div className="flex flex-col items-end gap-1.5">
                  <SeverityLegend rubric={rubric} />
                  <button onClick={() => setOpen(open.size === p.findings.length ? new Set() : new Set(p.findings.map((_, i) => i)))} className="text-[13px] font-medium text-blueprint hover:underline">
                    {open.size === p.findings.length ? "Recolher todos" : "Abrir todos"}
                  </button>
                </div>
              }>
              Apontamentos ({p.findings.length})
            </StepTitle>
          </div>
          {byValidation.map((g) => (
            <div key={g.v} className="border-b border-line/70 px-5 py-4 last:border-0">
              <h4 className="mb-3 flex flex-wrap items-baseline gap-x-2 text-sm">
                <span className="font-semibold">{VALIDATION_LABEL[g.v]}</span>
                {p.grades && <span className="text-muted">nota {p.grades[g.v]}/100 · peso {rubric.weights[g.v]}%</span>}
              </h4>
              <ul className="space-y-2.5">
                {g.items.map(({ f, imp, idx }) => {
                  const isOpen = open.has(idx);
                  const off = unfounded.has(f.kind);
                  const where = whereLabel(locate(f, p), p);
                  const many = countByKind[f.kind] > 1;
                  return (
                    <li key={idx} id={`finding-${idx}`}
                      className={`scroll-mt-24 rounded-lg border border-l-4 bg-sheet transition-colors ${isOpen ? "border-line shadow-sm" : "border-line/80 hover:border-ink/25"} ${off ? "opacity-60" : ""}`}
                      style={{ borderLeftColor: off ? "var(--color-line)" : SEVERITY[f.severity].color }}>
                      <div className="grid gap-3 py-2.5 pl-3 pr-3 sm:grid-cols-[1fr_180px]">
                        <button type="button" onClick={() => toggleOpen(idx)} aria-expanded={isOpen} aria-controls={`finding-ev-${idx}`} className="min-w-0 text-left text-sm">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="rounded px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-white" style={{ background: off ? "var(--color-muted)" : SEVERITY[f.severity].color }}>
                              {SEVERITY[f.severity].label}
                            </span>
                            <span className={`font-medium ${off ? "line-through decoration-ink/40" : ""}`}>{f.description}</span>
                            {f.lock && <span className="flex items-center gap-1 rounded bg-[#ece6f6] px-1.5 py-0.5 text-[11px] font-semibold text-lock"><Lock size={11} /> Trava</span>}
                            {f.reduces_confidence && <span className="flex items-center gap-1 rounded bg-paper px-1.5 py-0.5 text-[11px] font-semibold text-muted"><ShieldAlert size={11} /> Reduz confiança</span>}
                            {off && <span className="rounded bg-[#fbefed] px-1.5 py-0.5 text-[11px] font-semibold text-bad">Não procede</span>}
                          </div>
                          <div className="mt-1 text-muted">{f.evidence}</div>
                          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]">
                            {where && <span className="flex items-center gap-1 font-medium text-blueprint"><MapPin size={12} /> {where}</span>}
                            {f.amount_at_issue > 0 && <span className="text-muted">Em questão: <b className="text-bad">{brl(f.amount_at_issue)}</b></span>}
                            <span className="ml-auto flex items-center gap-0.5 font-medium text-blueprint">
                              {isOpen ? "Ocultar" : "Ver onde está o erro"} <ChevronDown size={14} className={`transition ${isOpen ? "rotate-180" : ""}`} />
                            </span>
                          </div>
                        </button>
                        <div className="flex flex-col gap-1.5">
                          <Impact f={f} imp={imp} weight={rubric.weights[f.validation]} off={off} />
                          <Tooltip content={off
                            ? "Desfazer: o apontamento volta a contar"
                            : `Marque se este apontamento está errado. A régua é recalculada na seção da decisão.${many ? ` Vale para os ${countByKind[f.kind]} apontamentos deste tipo.` : ""}`}>
                            <button type="button" onClick={() => toggleUnfounded(f.kind)} aria-pressed={off}
                              className={`flex w-full items-center justify-center gap-1.5 rounded-md border px-2 py-1 text-[12px] font-medium transition-colors ${off ? "border-line bg-paper text-ink hover:bg-sheet" : "border-line text-muted hover:border-bad hover:bg-[#fbefed] hover:text-bad"}`}>
                              {off ? <><Undo2 size={13} /> Desfazer</> : <><ThumbsDown size={13} /> Não procede{many ? ` (${countByKind[f.kind]})` : ""}</>}
                            </button>
                          </Tooltip>
                        </div>
                      </div>
                      {isOpen && (
                        <div id={`finding-ev-${idx}`} className="px-3 pb-3">
                          <FindingEvidence f={f} p={p} ticket={ticket} openPhoto={openPhoto} goTo={goTo} openTicket={openTicket} />
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </section>
      )}

      {/* 5. mensagem ao fornecedor */}
      {p.supplier_message && (
        <section className="rounded-xl border border-line bg-sheet p-5">
          <StepTitle n={++n} sub="Texto pronto para devolver ao fornecedor. Revise antes de enviar."
            aside={
              <button onClick={copy} className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-sm transition-colors ${copied ? "border-ok bg-[#e3f2ea] text-ok" : "border-line hover:bg-paper"}`}>
                {copied ? <Check size={14} /> : <Copy size={14} />}{copied ? "Copiada" : "Copiar"}
              </button>
            }>
            Mensagem sugerida ao fornecedor
          </StepTitle>
          {unfounded.size > 0 && (
            <p className="mt-2 rounded-md bg-[#fdf6e4] px-3 py-1.5 text-[13px]">Você marcou apontamentos como não procedentes: retire-os da mensagem antes de enviar.</p>
          )}
          <p className="mt-3 whitespace-pre-line rounded-lg bg-paper/60 p-4 text-[15px] leading-relaxed">{p.supplier_message}</p>
        </section>
      )}

      {/* 6. decisão da pessoa analista: por último, depois de ler o parecer inteiro */}
      <div ref={decisionRef}>
        <DecisionPanel p={p} n={++n} rubric={rubric} unfounded={unfounded} toggleUnfounded={toggleUnfounded} focusFinding={focusFinding} onRegistered={setRegistered} />
      </div>

      {p.record_id && !registered && !decisionVisible && (
        <div className="pointer-events-none sticky bottom-4 z-20 flex justify-center">
          <button onClick={() => decisionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })}
            className="surgir pointer-events-auto flex items-center gap-2 rounded-full bg-ink px-4 py-2 text-sm font-medium text-white shadow-lg hover:bg-[#1c3359]">
            <span className="size-2 rounded-full bg-warn pulso" /> Decisão pendente
            {unfounded.size > 0 && <span className="text-white/70">· {unfounded.size} não procede{unfounded.size === 1 ? "" : "m"}</span>}
            <span className="flex items-center gap-1 text-white/90">· Ir para a decisão <ArrowDown size={14} /></span>
          </button>
        </div>
      )}
    </div>
  );
}

function Fact({ label, help, children }: { label: string; help?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <dt className="flex items-center gap-1 text-[12px] text-muted">{label}{help}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** Quanto o apontamento pesou: pontos no score (destaque) e na nota da validação. */
function Impact({ f, imp, weight, off }: { f: Assessment["findings"][number]; imp: ReturnType<typeof explainFindings>[number]; weight: number; off: boolean }) {
  if (imp.repeated) {
    return (
      <Tooltip className="flex" content="Este tipo de apontamento já descontou nesta validação. Ele continua listado como evidência, mas não desconta de novo.">
        <div className="flex w-full cursor-help flex-col justify-center rounded-md bg-paper px-3 py-2 text-[12px] text-muted sm:text-right">
          <span className="font-semibold text-ink">0 pontos</span>
          <span>mesmo tipo já descontado</span>
        </div>
      </Tooltip>
    );
  }
  return (
    <Tooltip className="flex" content={off
      ? "Marcado como não procede: na revisão, estes pontos voltam para o score."
      : <>Tira <b>{imp.gradePts}</b> da nota de {VALIDATION_SHORT[f.validation]} (de 100).<br />Como {VALIDATION_SHORT[f.validation]} vale {weight}% do score: {imp.gradePts} × {weight}% = <b>{pts(imp.scorePts)}</b> pontos a menos no score.{imp.capped ? " A nota já estava perto de 0, então o desconto foi limitado." : ""}</>}>
      <div className={`flex w-full cursor-help items-center gap-3 rounded-md px-3 py-2 sm:flex-col sm:items-end sm:justify-center sm:gap-0 sm:text-right ${off ? "bg-paper" : "bg-[#fbefed]"}`}>
        <span className={`largo text-xl font-bold leading-none tabular-nums ${off ? "text-muted line-through" : "text-bad"}`}>−{pts(imp.scorePts)}</span>
        <span className="text-[12px] text-ink/80">ponto{imp.scorePts === 1 ? "" : "s"} no score</span>
        <span className="text-[11px] text-muted">−{imp.gradePts} na nota de {VALIDATION_SHORT[f.validation]}</span>
      </div>
    </Tooltip>
  );
}

function SeverityLegend({ rubric }: { rubric: RubricInfo }) {
  return (
    <Tooltip content="Quanto cada severidade tira da nota da validação (0–100). O efeito no score depende do peso da validação.">
      <div className="flex cursor-help flex-wrap items-center gap-2 text-[12px] text-muted">
        {(["critical", "high", "medium", "low"] as const).map((s) => (
          <span key={s} className="flex items-center gap-1"><i className="size-2.5 rounded-sm" style={{ background: SEVERITY[s].color }} />{SEVERITY[s].label} −{rubric.discount_by_severity[s]}</span>
        ))}
      </div>
    </Tooltip>
  );
}
