import { Info } from "lucide-react";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { GLOSSARY } from "../../format";

interface Props {
  content: ReactNode;
  children: ReactNode;
  side?: "top" | "bottom";
  className?: string;
  /** atraso para abrir no hover (ms); no foco abre na hora */
  delay?: number;
}

/**
 * Tooltip acessível: abre no hover e no foco do teclado, fecha com Esc, rolagem ou ao sair.
 * Renderiza num portal com posição fixa, então não é cortado por tabelas e painéis com overflow.
 */
export function Tooltip({ content, children, side = "top", className = "inline-flex", delay = 120 }: Props) {
  const anchor = useRef<HTMLSpanElement>(null);
  const tip = useRef<HTMLDivElement>(null);
  const timer = useRef<number | null>(null);
  const [pos, setPos] = useState<{ x: number; top: number; bottom: number } | null>(null);
  const id = useId();

  const show = useCallback((wait: number) => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const r = anchor.current?.getBoundingClientRect();
      if (r) setPos({ x: r.left + r.width / 2, top: r.top, bottom: r.bottom });
    }, wait);
  }, []);
  const hide = useCallback(() => {
    if (timer.current) window.clearTimeout(timer.current);
    setPos(null);
  }, []);

  useEffect(() => {
    if (!pos) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && hide();
    window.addEventListener("keydown", esc);
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    return () => {
      window.removeEventListener("keydown", esc);
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("resize", hide);
    };
  }, [pos, hide]);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);

  // depois de renderizar, mede o balão e o mantém dentro da tela (vira para baixo se faltar espaço em cima)
  useLayoutEffect(() => {
    const el = tip.current;
    if (!pos || !el) return;
    const w = el.offsetWidth, h = el.offsetHeight, gap = 8, margin = 8;
    const below = side === "bottom" ? pos.bottom + gap + h < window.innerHeight : pos.top - gap - h < margin;
    el.style.left = `${Math.min(Math.max(pos.x - w / 2, margin), window.innerWidth - w - margin)}px`;
    el.style.top = `${below ? pos.bottom + gap : pos.top - gap - h}px`;
    el.dataset.side = below ? "bottom" : "top";
    el.style.opacity = "1";
  }, [pos, side]);

  if (content === null || content === undefined || content === "") return <>{children}</>;
  return (
    <span ref={anchor} className={className} aria-describedby={pos ? id : undefined}
      onMouseEnter={() => show(delay)} onMouseLeave={hide} onFocus={() => show(0)} onBlur={hide}>
      {children}
      {pos && createPortal(
        <div ref={tip} id={id} role="tooltip" className="tooltip" style={{ left: -9999, top: -9999, opacity: 0 }}>
          {content}
        </div>,
        document.body,
      )}
    </span>
  );
}

/** Ícone (i) com explicação. Use `term` para puxar do glossário ou `text` para um texto livre. */
export function InfoTip({ term, text, size = 14, label }: { term?: keyof typeof GLOSSARY; text?: ReactNode; size?: number; label?: string }) {
  const g = term ? GLOSSARY[term] : undefined;
  const content = g ? <><b className="mb-0.5 block">{g.term}</b>{g.text}{text && <span className="mt-1 block">{text}</span>}</> : text;
  return (
    <Tooltip content={content}>
      <span role="button" tabIndex={0} aria-label={label ?? `O que é ${g?.term ?? "isto"}?`}
        className="inline-flex cursor-help items-center text-muted/80 transition-colors hover:text-blueprint focus-visible:text-blueprint">
        <Info size={size} />
      </span>
    </Tooltip>
  );
}
