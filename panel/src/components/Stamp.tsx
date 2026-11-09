import type { Recommendation } from "../api";
import { REC } from "../format";

interface Props {
  recommendation: Recommendation;
  score: number | null;
  ticketId: string;
  data: string;
  size?: number;
}

/** O resultado como um carimbo de atestação: score no centro, recomendação e chamado na borda. */
export function Stamp({ recommendation, score, ticketId, data, size = 220 }: Props) {
  const r = REC[recommendation];
  const when = new Date(data).toLocaleDateString("pt-BR");
  const borderText = `ATEST.AI  ✦  CHAMADO ${ticketId}  ✦  ${when}  ✦  `;
  const streamFilter = `tinta-${ticketId}`;
  return (
    <div className="carimbo shrink-0" style={{ width: size, height: size, color: r.color }} key={`${ticketId}-${recommendation}-${score}`}>
      <svg viewBox="0 0 200 200" width={size} height={size} role="img" aria-label={`${r.label}${score !== null ? `, score ${score}` : ""}`}>
        <defs>
          <filter id={streamFilter}>
            <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="7" result="noise" />
            <feColorMatrix in="noise" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -1.8 1.55" result="failures" />
            <feComposite in="SourceGraphic" in2="failures" operator="in" />
          </filter>
          <path id={`borda-${ticketId}`} d="M100,100 m-78,0 a78,78 0 1,1 156,0 a78,78 0 1,1 -156,0" />
        </defs>
        <g filter={`url(#${streamFilter})`} fill="currentColor" stroke="currentColor">
          <circle cx="100" cy="100" r="95" fill="none" strokeWidth="5" />
          <circle cx="100" cy="100" r="64" fill="none" strokeWidth="2" />
          <text fontSize="12.5" fontWeight="700" letterSpacing="1.6" stroke="none" style={{ fontStretch: "112%" }}>
            <textPath href={`#borda-${ticketId}`}>{borderText.repeat(2)}</textPath>
          </text>
          <text x="100" y={score !== null ? 112 : 116} textAnchor="middle" stroke="none" fontWeight="800"
            fontSize={score !== null ? 54 : 46} style={{ fontStretch: "125%" }}>
            {score !== null ? score : "↩"}
          </text>
          <text x="100" y="138" textAnchor="middle" stroke="none" fontWeight="700" fontSize="13" style={{ fontStretch: "100%" }}>
            {r.short}
          </text>
        </g>
      </svg>
    </div>
  );
}
