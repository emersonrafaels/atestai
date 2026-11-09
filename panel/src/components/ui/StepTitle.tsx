import type { ReactNode } from "react";

/** Título de seção numerado: deixa explícita a ordem de leitura do parecer. */
export function StepTitle({ n, children, aside, sub }: { n?: number; children: ReactNode; aside?: ReactNode; sub?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div className="flex min-w-0 items-start gap-3">
        {n !== undefined && (
          <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-blueprint-soft text-[12px] font-bold tabular-nums text-blueprint">{n}</span>
        )}
        <div className="min-w-0">
          <h3 className="flex flex-wrap items-center gap-2 font-semibold">{children}</h3>
          {sub && <p className="text-sm text-muted">{sub}</p>}
        </div>
      </div>
      {aside}
    </div>
  );
}
