import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Tooltip } from "./Tooltip";

/** Cartão de seção com título, ajuda opcional, subtítulo e ação à direita. */
export function Card({ title, sub, help, aside, tour, id, children, className = "" }: {
  title: ReactNode; sub?: ReactNode; help?: ReactNode; aside?: ReactNode; tour?: string; id?: string; children: ReactNode; className?: string;
}) {
  return (
    <section id={id} data-tour={tour} className={`scroll-mt-16 rounded-xl border border-line bg-sheet p-5 ${className}`}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
        <div className="min-w-0">
          <h3 className="flex items-center gap-1.5 font-semibold">{title}{help}</h3>
          {sub && <p className="text-[13px] text-muted">{sub}</p>}
        </div>
        {aside}
      </div>
      {children}
    </section>
  );
}

export interface DeltaInfo {
  /** diferença atual − anterior, já na unidade exibida */
  value: number;
  unit: "pp" | "pts" | "" | "R$";
  /** "up": subir é bom; "down": descer é bom */
  better: "up" | "down";
  /** de onde vem a comparação (tooltip) */
  vs: string;
}

/** Variação contra a referência anterior, colorida pelo que é melhor para a métrica. */
export function Delta({ d }: { d: DeltaInfo }) {
  const flat = Math.abs(d.value) < 0.05;
  const good = flat ? null : (d.value > 0) === (d.better === "up");
  const Icon = flat ? Minus : d.value > 0 ? ArrowUpRight : ArrowDownRight;
  const n = Math.abs(d.value).toLocaleString("pt-BR", { maximumFractionDigits: d.unit === "" ? 2 : 1 });
  return (
    <Tooltip content={`${flat ? "Igual" : d.value > 0 ? "Subiu" : "Caiu"} em relação a ${d.vs}`}>
      <span className={`inline-flex cursor-help items-center gap-0.5 rounded px-1 text-[12px] font-semibold tabular-nums ${good === null ? "bg-paper text-muted" : good ? "bg-[#e3f2ea] text-ok" : "bg-[#f8e4e2] text-bad"}`}>
        <Icon size={13} />{flat ? "0" : `${d.unit === "R$" ? "R$ " : ""}${n}${d.unit && d.unit !== "R$" ? ` ${d.unit}` : ""}`}
      </span>
    </Tooltip>
  );
}

/** Número de destaque com rótulo, ajuda, contexto e variação. */
export function Kpi({ label, value, sub, help, delta, tone, badge }: {
  label: ReactNode; value: ReactNode; sub?: ReactNode; help?: ReactNode; delta?: DeltaInfo | null; tone?: "ok" | "bad" | "warn"; badge?: ReactNode;
}) {
  const color = tone === "ok" ? "text-ok" : tone === "bad" ? "text-bad" : tone === "warn" ? "text-warn" : "";
  return (
    <div className="flex flex-col rounded-xl border border-line bg-sheet p-4">
      <div className="flex items-start justify-between gap-1 text-[13px] text-muted"><span>{label}</span>{help}</div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className={`largo text-[26px] font-bold leading-tight tabular-nums ${color}`}>{value}</span>
        {badge}
        {delta && <Delta d={delta} />}
      </div>
      {sub && <div className="mt-1 text-[12px] leading-snug text-muted">{sub}</div>}
    </div>
  );
}

/** Barra de navegação fixa entre as seções de uma página longa, com a seção visível destacada. */
export function SectionNav({ sections }: { sections: { id: string; label: string }[] }) {
  const [active, setActive] = useState(sections[0]?.id);
  const key = sections.map((s) => s.id).join("|");
  useEffect(() => {
    const els = key.split("|").map((id) => document.getElementById(id)).filter(Boolean) as HTMLElement[];
    if (!els.length) return;
    const io = new IntersectionObserver((entries) => {
      const vis = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (vis[0]) setActive(vis[0].target.id);
    }, { rootMargin: "-80px 0px -60% 0px" });
    els.forEach((e) => io.observe(e));
    return () => io.disconnect();
  }, [key]);
  return (
    <nav aria-label="Seções do relatório" className="sticky top-0 z-20 -mx-6 border-b border-line bg-paper/90 px-6 py-2 backdrop-blur">
      <ul className="flex gap-1 overflow-x-auto text-sm">
        {sections.map((s) => (
          <li key={s.id}>
            <button onClick={() => document.getElementById(s.id)?.scrollIntoView({ behavior: "smooth", block: "start" })}
              aria-current={active === s.id ? "location" : undefined}
              className={`whitespace-nowrap rounded-md px-3 py-1 transition-colors ${active === s.id ? "bg-sheet font-semibold text-blueprint shadow-sm" : "text-muted hover:text-ink"}`}>
              {s.label}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** Barra horizontal simples com rótulo e valor; `limit` desenha a linha de referência. */
export function Meter({ value, max = 1, color = "#2a78d6", limit, height = 8 }: { value: number | null; max?: number; color?: string; limit?: number; height?: number }) {
  const w = value === null ? 0 : Math.max(0, Math.min(100, (100 * value) / max));
  return (
    <div className="relative w-full rounded-full bg-paper" style={{ height }}>
      <div className="rounded-full transition-[width] duration-500" style={{ width: `${w}%`, height, background: color }} />
      {limit !== undefined && <div className="absolute -top-1 w-0.5 rounded bg-ink/70" style={{ left: `${(100 * limit) / max}%`, height: height + 8 }} />}
    </div>
  );
}

/** Tempo relativo curto: "agora", "há 3 min", "há 2 h". */
export function ago(d: Date): string {
  const s = Math.round((Date.now() - d.getTime()) / 1000);
  if (s < 45) return "agora";
  if (s < 3600) return `há ${Math.round(s / 60)} min`;
  if (s < 86400) return `há ${Math.round(s / 3600)} h`;
  return d.toLocaleDateString("pt-BR");
}
