import { Lock } from "lucide-react";
import { useEffect } from "react";
import type { Assessment } from "../api";
import { MOMENT_LABEL } from "../format";
import type { LightboxItem } from "./ui/Lightbox";
import { Tooltip } from "./ui/Tooltip";

const MATCH = {
  yes: { label: "Corresponde ao escopo", cls: "text-ok" },
  partial: { label: "Corresponde em parte", cls: "text-warn" },
  no: { label: "Não corresponde ao escopo", cls: "text-bad" },
  undetermined: { label: "Não dá para avaliar", cls: "text-muted" },
} as const;

export function PhotosTab({ p, base, openPhoto, highlight = [] }: { p: Assessment; base: string; openPhoto: (items: LightboxItem[], index: number) => void; highlight?: string[] }) {
  useScrollToHighlight(highlight.map((f) => `photo-${f}`));
  if (!p.photos.length) return <p className="text-muted">Nenhuma foto analisada neste chamado.</p>;
  const summary = p.photo_summary as { has_before_photo: boolean; has_done_service_photo: boolean; done_justification: string } | null;
  const gallery = p.photos.map((f) => ({ url: `${base}/${encodeURIComponent(f.file)}`, caption: f.what_it_shows }));
  return (
    <div className="space-y-4">
      {summary && (
        <div className="flex flex-wrap gap-2 text-sm">
          <Seal ok={summary.has_before_photo} text="Foto do antes" />
          {p.moment === "execution" && <Seal ok={summary.has_done_service_photo} text="Prova do serviço concluído" />}
          {!summary.has_done_service_photo && p.moment === "execution" && <span className="text-muted">{summary.done_justification}</span>}
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {p.photos.map((f, idx) => {
          const url = `${base}/${encodeURIComponent(f.file)}`;
          const problem = !f.readable || f.matches_scope === "no" || !!f.reused_from;
          const c = MATCH[f.matches_scope];
          return (
            <figure key={f.file} id={`photo-${f.file}`} className={`overflow-hidden rounded-xl border-2 bg-sheet ${highlight.includes(f.file) ? "destaque " : ""}${f.reused_from ? "border-lock" : problem ? "border-bad" : "border-line"}`}>
              <button onClick={() => openPhoto(gallery, idx)} aria-label={`Ampliar: ${f.what_it_shows}`} className="group relative block w-full overflow-hidden">
                <img src={url} alt={f.what_it_shows} loading="lazy" className="aspect-[4/3] w-full object-cover transition duration-300 group-hover:scale-[1.03]" />
                <span className="absolute left-2 top-2 rounded bg-ink/80 px-2 py-0.5 text-[12px] font-semibold capitalize text-white">{MOMENT_LABEL[f.moment] ?? f.moment}</span>
                {f.reused_from && (
                  <Tooltip className="absolute right-2 top-2 inline-flex" content={`Foto muito parecida com uma de outro chamado (${f.reused_from}). Isso aciona a trava de integridade.`}>
                    <span className="flex items-center gap-1 rounded bg-lock px-2 py-0.5 text-[12px] font-semibold text-white">
                      <Lock size={12} /> Reaproveitada
                    </span>
                  </Tooltip>
                )}
              </button>
              <figcaption className="space-y-1 p-3 text-sm">
                <div className="font-medium">{f.what_it_shows}</div>
                {f.environment && <div className="text-[13px] text-muted">Ambiente: {f.environment}</div>}
                <div className={`text-[13px] font-medium ${f.readable ? c.cls : "text-bad"}`}>{f.readable ? c.label : "Ilegível"}</div>
                {f.reason && f.reason !== "(simulado)" && <div className="text-[13px] text-muted">{f.reason}</div>}
                {f.integrity_signals.map((s, k) => <div key={k} className="text-[13px] text-lock">{s}</div>)}
                <div className="truncate pt-1 text-[11px] text-muted/80">{f.file}</div>
              </figcaption>
            </figure>
          );
        })}
      </div>
    </div>
  );
}

function Seal({ ok, text }: { ok: boolean; text: string }) {
  return (
    <span className={`rounded-full px-3 py-1 font-medium ${ok ? "bg-[#e3f2ea] text-ok" : "bg-[#f8e4e2] text-bad"}`}>
      {ok ? "Tem" : "Falta"}: {text.toLowerCase()}
    </span>
  );
}

/** rola até o primeiro elemento destacado (vindo do clique num apontamento) */
function useScrollToHighlight(ids: string[]) {
  const key = ids.join("|");
  useEffect(() => {
    if (!key) return;
    const t = window.setTimeout(() => document.getElementById(key.split("|")[0])?.scrollIntoView({ block: "center", behavior: "smooth" }), 80);
    return () => window.clearTimeout(t);
  }, [key]);
}
