import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { useEffect, useState } from "react";

export interface LightboxItem {
  url: string;
  caption?: string;
}

/** Visualizador de fotos em tela cheia: setas (tela ou teclado) passam as fotos, Esc fecha. */
export function Lightbox({ items, start, onClose }: { items: LightboxItem[]; start: number; onClose: () => void }) {
  const [i, setI] = useState(start);
  const n = items.length;
  useEffect(() => setI(start), [start, items]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight") setI((k) => (k + 1) % n);
      else if (e.key === "ArrowLeft") setI((k) => (k - 1 + n) % n);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [n, onClose]);
  const item = items[i];
  if (!item) return null;
  const nav = "absolute top-1/2 -translate-y-1/2 rounded-full bg-sheet/90 p-2.5 text-ink shadow-lg hover:bg-sheet";
  return (
    <div role="dialog" aria-modal="true" aria-label="Visualizar foto" className="fixed inset-0 z-[60] flex flex-col items-center justify-center gap-3 bg-ink/85 p-6 backdrop-blur-sm" onClick={onClose}>
      <img src={item.url} alt={item.caption ?? ""} className="max-h-[calc(100%-4rem)] max-w-full rounded-lg shadow-2xl" onClick={(e) => e.stopPropagation()} />
      <div className="max-w-3xl text-center text-sm text-white/90" onClick={(e) => e.stopPropagation()}>
        {item.caption && <span>{item.caption}</span>}
        {n > 1 && <span className="ml-2 tabular-nums text-white/60">{i + 1} / {n}</span>}
      </div>
      {n > 1 && (
        <>
          <button aria-label="Foto anterior" className={`${nav} left-4`} onClick={(e) => { e.stopPropagation(); setI((k) => (k - 1 + n) % n); }}><ChevronLeft size={20} /></button>
          <button aria-label="Próxima foto" className={`${nav} right-4`} onClick={(e) => { e.stopPropagation(); setI((k) => (k + 1) % n); }}><ChevronRight size={20} /></button>
        </>
      )}
      <button aria-label="Fechar" className="absolute right-5 top-5 rounded-full bg-sheet p-2" onClick={onClose}><X size={18} /></button>
    </div>
  );
}
