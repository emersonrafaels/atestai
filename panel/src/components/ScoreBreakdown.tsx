import { Lock, ShieldAlert } from "lucide-react";
import type { Assessment, RubricInfo } from "../api";
import { findingLabel, GLOSSARY, REC, VALIDATIONS, VALIDATION_LABEL, explainFindings, pts } from "../format";
import { InfoTip, Tooltip } from "./ui/Tooltip";

const gradeColor = (g: number) => (g >= 85 ? "var(--color-ok)" : g >= 70 ? "var(--color-warn)" : "var(--color-bad)");

/**
 * Mostra a conta inteira do score: cada validação começa em 100, perde os descontos dos apontamentos,
 * e entra no score com o seu peso. Embaixo, a régua de faixas com o score posicionado.
 */
export function ScoreBreakdown({ p, rubric }: { p: Assessment; rubric: RubricInfo }) {
  if (p.score === null || !p.grades) return null;
  const totalWeight = VALIDATIONS.reduce((s, v) => s + rubric.weights[v], 0) || 100;
  const impacts = explainFindings(p.findings, rubric);
  const locked = p.findings.some((f) => f.lock);
  const lowConfidence = p.recommendation === "detailed_review";

  const rows = VALIDATIONS.map((v) => {
    const grade = p.grades![v];
    const weight = rubric.weights[v];
    const discounts = p.findings.map((f, k) => ({ f, imp: impacts[k] })).filter((x) => x.f.validation === v && x.imp.gradePts > 0);
    const absorbed = p.findings.map((f, k) => ({ f, imp: impacts[k] })).filter((x) => x.f.validation === v && x.imp.absorbedBy);
    return { v, grade, weight, discounts, absorbed, contribution: (grade * weight) / totalWeight, max: (100 * weight) / totalWeight };
  });

  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-3">
        {rows.map((r) => (
          <div key={r.v} className="rounded-xl border border-line bg-paper/40 p-4">
            <div className="flex items-baseline justify-between gap-2 text-sm">
              <span className="font-semibold">{VALIDATION_LABEL[r.v]}</span>
              <Tooltip content={`Esta validação vale ${r.weight}% do score. Nota ${r.grade} × ${r.weight}% = ${pts(r.contribution)} pontos.`}>
                <span className="cursor-help rounded-full bg-sheet px-2 py-0.5 text-[12px] text-muted ring-1 ring-line">peso {r.weight}%</span>
              </Tooltip>
            </div>

            {/* a conta da nota: 100 − descontos */}
            <div className="mt-2 flex flex-wrap items-baseline gap-x-1.5 gap-y-1 text-[13px] tabular-nums text-muted">
              <span>100</span>
              {r.discounts.map(({ f, imp }, k) => (
                <Tooltip key={k} content={<><b>{f.description}</b><br />Severidade {f.severity === "critical" ? "crítica" : f.severity === "high" ? "alta" : f.severity === "medium" ? "média" : "baixa"}: −{imp.gradePts} na nota{imp.capped ? " (limitado: a nota não fica abaixo de 0)" : ""}.</>}>
                  <span className="cursor-help rounded px-1 font-semibold text-bad underline decoration-dotted underline-offset-2">−{imp.gradePts}</span>
                </Tooltip>
              ))}
              <span>=</span>
            </div>
            <div className="flex items-baseline gap-1">
              <span className="largo text-3xl font-bold tabular-nums" style={{ color: gradeColor(r.grade) }}>{r.grade}</span>
              <span className="text-muted">/100</span>
            </div>
            <div className="mt-2 h-1.5 rounded-full bg-line/60"><div className="h-1.5 rounded-full" style={{ width: `${r.grade}%`, background: gradeColor(r.grade) }} /></div>
            <div className="mt-2 text-[13px] text-muted">
              Contribui <b className="tabular-nums text-ink">{pts(r.contribution)}</b> de {pts(r.max)} pontos do score
              {r.discounts.length === 0 && <span className="text-ok"> · sem descontos</span>}
            </div>
            {r.absorbed.length > 0 && (
              <Tooltip content={GLOSSARY.absorbed.text}>
                <div className="mt-1 cursor-help text-[12px] text-muted">
                  {r.absorbed.map(({ f, imp }) => `${findingLabel(f.kind)} absorvido por ${findingLabel(imp.absorbedBy!)}`).filter((x, i, a) => a.indexOf(x) === i).join(" · ")}
                </div>
              </Tooltip>
            )}
          </div>
        ))}
      </div>

      {/* a soma ponderada */}
      <div className="flex flex-wrap items-center gap-2 rounded-xl bg-paper/60 px-4 py-3 text-sm">
        <span className="text-muted">Score =</span>
        {rows.map((r, k) => (
          <span key={r.v} className="flex items-center gap-2">
            <Tooltip content={`${VALIDATION_LABEL[r.v]}: nota ${r.grade} × peso ${r.weight}%`}>
              <span className="cursor-help rounded-md bg-sheet px-2 py-0.5 font-semibold tabular-nums ring-1 ring-line">{pts(r.contribution)}</span>
            </Tooltip>
            <span className="text-[11px] text-muted">{r.v === "scope" ? "escopo" : r.v === "quote" ? "orçamento" : "fotos"}</span>
            {k < rows.length - 1 && <span className="text-muted">+</span>}
          </span>
        ))}
        <span className="text-muted">=</span>
        <span className="largo text-xl font-bold tabular-nums" style={{ color: REC[p.recommendation].color }}>{p.score}</span>
        <InfoTip term="once" />
      </div>

      <BandScale score={p.score} rubric={rubric} />

      {(locked || lowConfidence) && (
        <p className="flex items-start gap-2 rounded-lg bg-[#f1ecfa] px-3 py-2 text-sm text-lock">
          {locked ? <Lock size={16} className="mt-0.5 shrink-0" /> : <ShieldAlert size={16} className="mt-0.5 shrink-0" />}
          {locked
            ? "Há uma trava de integridade: o chamado é devolvido qualquer que seja o score. O score fica registrado apenas como referência."
            : "Confiança baixa: a entrada não basta para concluir, então o chamado vai para análise detalhada independente da faixa do score."}
        </p>
      )}
    </div>
  );
}

/** Régua horizontal 0–100 com as faixas de recomendação e um marcador no score. */
export function BandScale({ score, rubric, compact = false }: { score: number; rubric: RubricInfo; compact?: boolean }) {
  const bands = [...rubric.bands].sort((a, b) => a.score_min - b.score_min);
  const segs = bands.map((b, k) => ({ ...b, end: bands[k + 1]?.score_min ?? 100 }));
  const current = [...segs].reverse().find((s) => score >= s.score_min);
  return (
    <div className={compact ? "" : "pt-1"} aria-label={`Score ${score} na faixa ${current ? REC[current.recommendation].label : ""}`}>
      <div className="relative">
        <div className="flex h-2.5 overflow-hidden rounded-full">
          {segs.map((s) => (
            <div key={s.score_min} style={{ width: `${s.end - s.score_min}%`, background: REC[s.recommendation].mark, opacity: current === s ? 1 : 0.28 }} />
          ))}
        </div>
        <div className="absolute -top-1.5 h-[22px] w-1 -translate-x-1/2 rounded-full bg-ink ring-2 ring-sheet" style={{ left: `${Math.min(100, Math.max(0, score))}%` }} />
      </div>
      {!compact && (
        <div className="relative mt-1.5 h-9 text-[12px] text-muted">
          {segs.map((s) => (
            <div key={s.score_min} className="absolute top-0 text-center" style={{ left: `${s.score_min}%`, width: `${s.end - s.score_min}%` }}>
              <div className={current === s ? "font-semibold text-ink" : ""}>{REC[s.recommendation].short}</div>
              <div className="tabular-nums">{s.score_min}–{s.end === 100 ? 100 : s.end - 1}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
