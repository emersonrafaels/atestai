import { Check, Lock, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { Recommendation, RubricInfo } from "../api";
import { DEFAULT_RUBRIC, REC } from "../format";

// arco de 270° (abertura embaixo), de 135° a 405° no sentido horário
const START = 135, SWEEP = 270, C = 100;
const angle = (v: number) => START + (SWEEP * Math.max(0, Math.min(100, v))) / 100;
const point = (deg: number, r: number) => [C + r * Math.cos((deg * Math.PI) / 180), C + r * Math.sin((deg * Math.PI) / 180)];
function arc(a: number, b: number, r: number) {
  const [x1, y1] = point(angle(a), r), [x2, y2] = point(angle(b), r);
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${angle(b) - angle(a) > 180 ? 1 : 0} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
}

/** Fundo suave da cor da recomendação (para pílulas e selos). */
export const tint = (rec: Recommendation, pct = 14) => `color-mix(in srgb, ${REC[rec].mark} ${pct}%, white)`;

/**
 * Medidor do score: o arco enche até a nota, as faixas da régua aparecem no trilho e a recomendação fica na abertura.
 * Sem score (devolvido no checklist), mostra o motivo no lugar do número.
 */
export function ScoreGauge({ score, recommendation, rubric = DEFAULT_RUBRIC, size = 200, locked = false }: {
  score: number | null; recommendation: Recommendation; rubric?: RubricInfo; size?: number; locked?: boolean;
}) {
  const r = REC[recommendation];
  const [shown, setShown] = useState(0);
  useEffect(() => {
    // anima de 0 até a nota (sem animação para quem prefere menos movimento)
    if (score === null) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) { setShown(score); return; }
    setShown(0);
    const id = requestAnimationFrame(() => setShown(score));
    return () => cancelAnimationFrame(id);
  }, [score]);

  const bands = [...rubric.bands].sort((a, b) => a.score_min - b.score_min).map((b, i, all) => ({ ...b, end: all[i + 1]?.score_min ?? 100 }));
  const ticks = bands.map((b) => b.score_min).filter((m) => m > 0);

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg viewBox="0 0 200 200" width={size} height={size} role="img" overflow="visible"
        aria-label={score !== null ? `Score ${score} de 100: ${r.label}` : `${r.label}: sem score`}>
        {/* trilho com as faixas da régua */}
        {bands.map((b) => (
          <path key={b.score_min} d={arc(b.score_min + (b.score_min ? 0.6 : 0), b.end - (b.end < 100 ? 0.6 : 0), 80)} fill="none"
            stroke={REC[b.recommendation].mark} strokeOpacity={score === null ? 0.12 : 0.2} strokeWidth={14} strokeLinecap="butt" />
        ))}
        {/* arco do score */}
        {score !== null && (
          <path d={arc(0, 100, 80)} fill="none" stroke={r.mark} strokeWidth={14} strokeLinecap="round" pathLength={100}
            strokeDasharray={`${Math.max(0.01, shown)} 100`} className="gauge-arc" />
        )}
        {/* marcas das faixas */}
        {ticks.map((t) => {
          const [x1, y1] = point(angle(t), 92), [x2, y2] = point(angle(t), 98), [lx, ly] = point(angle(t), 108);
          return (
            <g key={t}>
              <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#5e6b7e" strokeWidth={1.5} strokeLinecap="round" />
              <text x={lx} y={ly + 3.5} textAnchor="middle" fontSize="10" fill="#5e6b7e" className="tabular-nums">{t}</text>
            </g>
          );
        })}
      </svg>

      {/* centro: número e escala */}
      <div className="absolute inset-0 flex flex-col items-center justify-center pb-3">
        {score !== null ? (
          <>
            <span className="largo font-extrabold leading-none tabular-nums" style={{ color: r.color, fontSize: size * 0.27 }}>{score}</span>
            <span className="mt-0.5 text-[12px] font-medium text-muted">de 100</span>
          </>
        ) : (
          <>
            <Undo2 size={size * 0.17} style={{ color: r.color }} />
            <span className="mt-1 text-[12px] font-medium text-muted">sem score</span>
          </>
        )}
      </div>

      {/* abertura embaixo: a recomendação */}
      <div className="absolute inset-x-0 flex justify-center" style={{ bottom: size * 0.04 }}>
        <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[12px] font-bold shadow-sm ring-1 ring-white"
          style={{ background: tint(recommendation, 18), color: r.color }}>
          {locked && <Lock size={11} />}{r.short}
        </span>
      </div>
    </div>
  );
}

/** Pílula compacta para listas: nota em destaque + recomendação, na cor da recomendação. */
export function ScorePill({ score, recommendation, decided = false, muted = false }: {
  score: number | null; recommendation: Recommendation; decided?: boolean; muted?: boolean;
}) {
  const r = REC[recommendation];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full py-0.5 pl-0.5 pr-2 text-[12px] font-semibold ${muted ? "opacity-80" : ""}`}
      style={{ background: tint(recommendation, 13), color: r.color }}>
      <span className="flex h-[18px] min-w-[26px] items-center justify-center rounded-full bg-white px-1 text-[11px] font-bold tabular-nums shadow-sm">
        {score !== null ? score : <Undo2 size={11} />}
      </span>
      {r.short}
      {decided && <Check size={12} strokeWidth={3} aria-label="com decisão registrada" />}
    </span>
  );
}
