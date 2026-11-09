import { ArrowLeft, ArrowRight, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

export interface TourStep {
  /** valor do atributo data-tour do elemento a destacar; sem alvo, o passo aparece centralizado */
  target?: string;
  title: string;
  body: ReactNode;
  /** roda antes de mostrar o passo (ex.: trocar de aba para o alvo existir) */
  before?: () => void;
}

const DONE_KEY = "atest.tour.done";
export const tourDone = () => { try { return localStorage.getItem(DONE_KEY) === "1"; } catch { return true; } };
const markDone = () => { try { localStorage.setItem(DONE_KEY, "1"); } catch { /* armazenamento indisponível */ } };

const PAD = 6;
const CARD_W = 360;
const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/**
 * Tour guiado em lightbox: escurece a tela, recorta um "holofote" no elemento do passo e mostra um balão
 * com a explicação. Passos cujo alvo não está na tela são pulados. Teclado: ← → navegam, Esc fecha.
 */
export function Tour({ steps, open, onClose }: { steps: TourStep[]; open: boolean; onClose: () => void }) {
  const [i, setI] = useState(0);
  const [dir, setDir] = useState<1 | -1>(1);
  const [target, setTarget] = useState<HTMLElement | null>(null);
  const [ready, setReady] = useState(false);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [card, setCard] = useState<{ w: number; h: number }>({ w: CARD_W, h: 200 });
  const cardRef = useRef<HTMLDivElement>(null);
  const stepsRef = useRef(steps);
  stepsRef.current = steps;

  const close = useCallback(() => { markDone(); setI(0); setDir(1); setTarget(null); onClose(); }, [onClose]);
  const go = useCallback((d: 1 | -1) => {
    setDir(d);
    if (i + d >= stepsRef.current.length) close();
    else setI(Math.max(0, i + d));
  }, [i, close]);

  // prepara o passo: roda o before(), espera o alvo aparecer e rola até ele; sem alvo, pula
  useEffect(() => {
    if (!open) return;
    const step = stepsRef.current[i];
    if (!step) return;
    setReady(false);
    step.before?.();
    let frame = 0, raf = 0;
    const find = () => {
      if (!step.target) { setTarget(null); setReady(true); return; }
      const el = document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`);
      if (el && el.getClientRects().length) {
        el.scrollIntoView({ block: el.offsetHeight > window.innerHeight * 0.6 ? "start" : "center", behavior: reducedMotion() ? "auto" : "smooth" });
        setTarget(el);
        setReady(true);
        return;
      }
      if (frame++ < 15) raf = requestAnimationFrame(find);
      else if (i + dir >= 0 && i + dir < stepsRef.current.length) setI(i + dir);
      else if (dir === 1) close();
      else setDir(1);
    };
    raf = requestAnimationFrame(find);
    return () => cancelAnimationFrame(raf);
  }, [open, i, dir, close]);

  // acompanha o alvo enquanto a página rola ou muda de tamanho
  useEffect(() => {
    if (!open || !target) { setRect(null); return; }
    let raf = 0;
    let last = "";
    const loop = () => {
      const r = target.getBoundingClientRect();
      const k = `${r.x}|${r.y}|${r.width}|${r.height}`;
      if (k !== last) { last = k; setRect(r); }
      raf = requestAnimationFrame(loop);
    };
    loop();
    return () => cancelAnimationFrame(raf);
  }, [open, target]);

  useLayoutEffect(() => {
    const el = cardRef.current;
    if (el && (el.offsetWidth !== card.w || el.offsetHeight !== card.h)) setCard({ w: el.offsetWidth, h: el.offsetHeight });
  });

  useEffect(() => { if (open && ready) cardRef.current?.focus({ preventScroll: true }); }, [open, ready, i]);

  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      else if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [open, go, close]);

  if (!open) return null;
  const step = steps[i];
  if (!step) return null;

  const vw = window.innerWidth, vh = window.innerHeight, m = 12;
  const hole = rect && step.target ? { x: rect.left - PAD, y: rect.top - PAD, w: rect.width + 2 * PAD, h: rect.height + 2 * PAD } : null;
  let left = (vw - card.w) / 2, top = (vh - card.h) / 2;
  if (hole) {
    const below = hole.y + hole.h + m, above = hole.y - m - card.h;
    if (below + card.h < vh - m) top = below;
    else if (above > m) top = above;
    else if (hole.x + hole.w + m + card.w < vw - m) { top = Math.max(m, Math.min(hole.y, vh - card.h - m)); left = hole.x + hole.w + m; }
    else if (hole.x - m - card.w > m) { top = Math.max(m, Math.min(hole.y, vh - card.h - m)); left = hole.x - m - card.w; }
    else top = vh - card.h - m;
    if (left === (vw - card.w) / 2) left = hole.x + hole.w / 2 - card.w / 2;
    left = Math.max(m, Math.min(left, vw - card.w - m));
  }

  return createPortal(
    <div className="fixed inset-0 z-[70]" aria-live="polite">
      {/* camada que bloqueia cliques fora do tour */}
      <div className="absolute inset-0" onClick={(e) => e.stopPropagation()} />
      <div className={`tour-spot ${hole ? "" : "tour-spot-full"}`} style={hole ? { left: hole.x, top: hole.y, width: hole.w, height: hole.h } : undefined} />
      <div ref={cardRef} role="dialog" aria-modal="true" aria-labelledby="tour-title" tabIndex={-1}
        className={`tour-card absolute w-[min(360px,calc(100vw-24px))] rounded-2xl bg-sheet p-5 shadow-2xl outline-none ${ready ? "opacity-100" : "opacity-0"}`}
        style={{ left, top }}>
        <div className="mb-1 flex items-center justify-between text-[12px] font-medium uppercase tracking-wide text-blueprint">
          <span>Passo {i + 1} de {steps.length}</span>
          <button onClick={close} aria-label="Fechar tour" className="-mr-2 rounded-md p-1 text-muted hover:bg-paper hover:text-ink"><X size={16} /></button>
        </div>
        <h2 id="tour-title" className="largo text-lg font-bold leading-snug">{step.title}</h2>
        <div className="mt-1.5 space-y-2 text-[14px] leading-relaxed text-ink/85">{step.body}</div>
        <div className="mt-4 flex items-center gap-1" aria-hidden>
          {steps.map((_, k) => <span key={k} className={`h-1.5 rounded-full transition-all ${k === i ? "w-5 bg-blueprint" : k < i ? "w-1.5 bg-blueprint/50" : "w-1.5 bg-line"}`} />)}
        </div>
        <div className="mt-4 flex items-center justify-between gap-2">
          <button onClick={close} className="text-sm text-muted hover:text-ink">Pular tour</button>
          <div className="flex gap-2">
            {i > 0 && (
              <button onClick={() => go(-1)} className="flex items-center gap-1 rounded-lg border border-line px-3 py-1.5 text-sm font-medium hover:bg-paper">
                <ArrowLeft size={15} /> Voltar
              </button>
            )}
            <button onClick={() => go(1)} className="flex items-center gap-1 rounded-lg bg-blueprint px-3.5 py-1.5 text-sm font-semibold text-white hover:bg-[#1d44a0]">
              {i === steps.length - 1 ? "Concluir" : <>Próximo <ArrowRight size={15} /></>}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
