import { BookOpen, Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { GLOSSARY } from "../../format";

/** Glossário de todos os termos do painel, com busca. */
export function GlossaryDialog({ onClose }: { onClose: () => void }) {
  const [q, setQ] = useState("");
  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);
  const norm = (s: string) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
  const items = Object.values(GLOSSARY)
    .filter((g) => !q || norm(`${g.term} ${g.text}`).includes(norm(q)))
    .sort((a, b) => a.term.localeCompare(b.term, "pt-BR"));
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="glossario" className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/60 p-6" onClick={onClose}>
      <div className="w-full max-w-2xl rounded-2xl bg-sheet shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-line px-6 py-4">
          <h2 id="glossario" className="largo flex items-center gap-2 text-xl font-bold"><BookOpen size={20} className="text-blueprint" /> Glossário</h2>
          <button aria-label="Fechar" onClick={onClose} className="rounded-full p-1.5 hover:bg-paper"><X size={18} /></button>
        </header>
        <div className="px-6 pt-4">
          <label className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 focus-within:border-blueprint">
            <Search size={16} className="text-muted" />
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar termo (ex.: kappa, trava, peso)" className="w-full bg-transparent text-sm outline-none" />
          </label>
        </div>
        <dl className="max-h-[65vh] divide-y divide-line/70 overflow-y-auto px-6 py-2">
          {items.map((g) => (
            <div key={g.term} className="py-3">
              <dt className="font-semibold">{g.term}</dt>
              <dd className="text-sm leading-relaxed text-muted">{g.text}</dd>
            </div>
          ))}
          {!items.length && <p className="py-6 text-center text-sm text-muted">Nenhum termo encontrado.</p>}
        </dl>
      </div>
    </div>
  );
}
