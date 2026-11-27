import { ChevronDown } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useState, type ComponentProps, type ReactNode } from "react";

/**
 * Blocos recolhíveis do parecer. `FoldsProvider` guarda quais estão abertos (preferência de quem vê, no navegador);
 * `Fold` é a seção, `FoldBody` some quando ela está recolhida, e o título (`StepTitle` ou `FoldTitle`) vira o botão.
 */
type Folds = { isOpen: (id: string) => boolean; toggle: (id: string) => void; reveal: (id: string) => void };
const FoldsCtx = createContext<Folds | null>(null);
const SectionCtx = createContext<{ id: string; open: boolean; toggle: () => void } | null>(null);

const KEY = "atest.parecer.folds";
function load(): Record<string, boolean> {
  try { return JSON.parse(localStorage.getItem(KEY) ?? "{}") as Record<string, boolean>; } catch { return {}; }
}

/** Estado dos blocos: `defaults` diz quem começa recolhido (false); o que a pessoa abrir ou fechar fica lembrado. */
export function useFolds(defaults: Record<string, boolean>): Folds {
  const [state, setState] = useState<Record<string, boolean>>(load);
  const isOpen = useCallback((id: string) => state[id] ?? defaults[id] ?? true, [state, defaults]);
  const set = useCallback((id: string, open: boolean) => setState((s) => {
    const next = { ...s, [id]: open };
    try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* armazenamento indisponível */ }
    return next;
  }), []);
  return useMemo(() => ({
    isOpen,
    toggle: (id: string) => set(id, !isOpen(id)),
    reveal: (id: string) => { if (!isOpen(id)) set(id, true); },
  }), [isOpen, set]);
}

export const FoldsProvider = FoldsCtx.Provider;

/** Seção recolhível (fora de um `FoldsProvider`, fica sempre aberta). */
export function Fold({ id, children, ...rest }: { id: string } & ComponentProps<"section">) {
  const folds = useContext(FoldsCtx);
  const open = folds ? folds.isOpen(id) : true;
  const ctx = useMemo(() => ({ id, open, toggle: () => folds?.toggle(id) }), [id, open, folds]);
  return (
    <SectionCtx.Provider value={ctx}>
      <section {...rest} className={`group/fold ${rest.className ?? ""}`} data-fold={open ? "open" : "closed"}>{children}</section>
    </SectionCtx.Provider>
  );
}

/** Conteúdo do bloco: não renderiza com o bloco recolhido. */
export function FoldBody({ children }: { children: ReactNode }) {
  const s = useContext(SectionCtx);
  return s && !s.open ? null : <>{children}</>;
}

/** O bloco em que o componente está (null fora de um `Fold`). */
export function useFold() {
  return useContext(SectionCtx);
}

/** Botão do título: o nome do bloco e a seta; aria-expanded para leitor de tela. */
export function FoldToggle({ children, className = "" }: { children: ReactNode; className?: string }) {
  const s = useFold();
  if (!s) return <>{children}</>;
  return (
    <button type="button" onClick={s.toggle} aria-expanded={s.open}
      className={`group flex min-w-0 items-center gap-2 text-left ${className}`}>
      {children}
      <ChevronDown size={18} aria-hidden className={`shrink-0 text-muted transition-transform group-hover:text-ink ${s.open ? "" : "-rotate-90"}`} />
      {!s.open && <span className="text-[12px] font-normal text-muted group-hover:text-blueprint">mostrar</span>}
    </button>
  );
}

/** Título simples (sem número) que recolhe o bloco: usado no Resumo. */
export function FoldTitle({ children }: { children: ReactNode }) {
  return <h3 className="font-semibold"><FoldToggle>{children}</FoldToggle></h3>;
}
