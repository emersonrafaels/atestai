import { AlertTriangle, Check, ChevronDown, PencilLine } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { ModelOption } from "../../api";
import { Tooltip } from "./Tooltip";

interface Props {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: ModelOption[];
  /** modelo da configuração para este papel (ganha o selo "padrão") */
  defaultId?: string;
  /** provedor usado quando o texto vem sem "provedor:" */
  defaultProvider?: string;
  /** provedores com chave configurada; outro provedor ganha um aviso */
  availableProviders?: string[];
  hint?: string;
}

const usd = (v: number) => v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 3 });
const PROVIDER: Record<string, string> = { anthropic: "Anthropic", openai: "OpenAI", google: "Google" };

/**
 * Caixa de seleção de modelo que também aceita texto livre: lista os modelos conhecidos (com preço) e, se o
 * digitado não estiver na lista, oferece "Usar …". Teclado: ↑ ↓ navegam, Enter escolhe, Esc cancela.
 */
export function ModelCombobox({ label, value, onChange, options, defaultId, defaultProvider = "anthropic", availableProviders, hint }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState<string | null>(null); // null = não está digitando, mostra o valor atual
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const id = useId();

  const q = (query ?? "").trim().toLowerCase();
  const filtered = useMemo(() => (q ? options.filter((o) => `${o.id} ${o.name}`.toLowerCase().includes(q)) : options), [options, q]);
  const typed = (query ?? "").trim();
  const exact = options.some((o) => o.id.toLowerCase() === typed.toLowerCase() || o.name.toLowerCase() === typed.toLowerCase());
  // "Usar …" só quando o texto não é um pedaço de um modelo da lista (ex.: "opus") ou já vem como provedor:modelo
  const showCustom = !!typed && !exact && (!filtered.length || typed.includes(":"));
  const rows = [...filtered.map((o) => ({ kind: "option" as const, o })), ...(showCustom ? [{ kind: "custom" as const, text: typed }] : [])];

  const known = options.find((o) => o.id === value || o.name === value);
  const provider = value.includes(":") ? value.split(":")[0] : defaultProvider;
  const providerMissing = availableProviders && !availableProviders.includes(provider);

  useEffect(() => {
    if (!open) return;
    const out = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) commit(); };
    document.addEventListener("mousedown", out);
    return () => document.removeEventListener("mousedown", out);
  });

  useEffect(() => {
    // ao abrir sem digitar, destaca o valor atual
    if (open && query === null) setActive(Math.max(0, options.findIndex((o) => o.id === value)));
  }, [open, query, options, value]);

  useEffect(() => {
    list.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const choose = (v: string) => {
    onChange(v);
    setQuery(null);
    setOpen(false);
  };
  // sair do campo com texto digitado mantém o texto (é o modo "escrever outro modelo")
  const commit = () => {
    if (typed) {
      const match = options.find((o) => o.id.toLowerCase() === typed.toLowerCase() || o.name.toLowerCase() === typed.toLowerCase());
      onChange(match ? match.id : typed);
    }
    setQuery(null);
    setOpen(false);
  };

  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(rows.length - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === "Enter") {
      e.preventDefault();
      const r = rows[active];
      if (open && r) choose(r.kind === "option" ? r.o.id : r.text);
      else commit();
    } else if (e.key === "Escape") {
      if (open) { e.stopPropagation(); setQuery(null); setOpen(false); }
    } else if (e.key === "Tab") commit();
  };

  return (
    <div ref={root} className="relative">
      <div className={`flex items-center rounded-md border bg-sheet transition-colors focus-within:border-blueprint focus-within:ring-2 focus-within:ring-blueprint/15 ${open ? "border-blueprint" : "border-line hover:border-ink/25"}`}>
        <span className="pl-2 text-[11px] font-semibold uppercase tracking-wide text-muted">{label}</span>
        <input
          ref={input}
          id={`${id}-input`}
          role="combobox"
          aria-label={`Modelo ${label.toLowerCase()}`}
          aria-expanded={open}
          aria-controls={`${id}-list`}
          aria-autocomplete="list"
          aria-activedescendant={open && rows[active] ? `${id}-opt-${active}` : undefined}
          value={query ?? value}
          placeholder="provedor:modelo"
          spellCheck={false}
          onFocus={() => setOpen(true)}
          onClick={() => setOpen(true)}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); setActive(0); }}
          onKeyDown={onKey}
          className="w-48 min-w-0 bg-transparent px-2 py-1 text-[13px] outline-none"
        />
        {!known && value && (
          <Tooltip content={providerMissing ? `O provedor "${provider}" não tem chave configurada: a execução vai falhar.` : "Modelo fora da tabela de preços: a análise roda, mas o custo não é calculado."}>
            <span className={`cursor-help ${providerMissing ? "text-bad" : "text-warn"}`}><AlertTriangle size={14} /></span>
          </Tooltip>
        )}
        <button type="button" tabIndex={-1} aria-label={open ? "Fechar lista de modelos" : "Abrir lista de modelos"}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => { if (open) { setQuery(null); setOpen(false); } else { setOpen(true); input.current?.focus(); } }}
          className="px-1.5 py-1 text-muted hover:text-ink">
          <ChevronDown size={15} className={`transition ${open ? "rotate-180" : ""}`} />
        </button>
      </div>

      {open && (
        <div className="surgir absolute right-0 z-40 mt-1.5 w-[22rem] overflow-hidden rounded-xl border border-line bg-sheet shadow-xl">
          {hint && <div className="border-b border-line bg-paper/60 px-3 py-1.5 text-[12px] text-muted">{hint}</div>}
          <ul ref={list} id={`${id}-list`} role="listbox" aria-label={`Modelos para ${label.toLowerCase()}`} className="max-h-72 overflow-y-auto p-1">
            {rows.map((r, i) => {
              const isActive = i === active;
              if (r.kind === "custom") {
                const noPrefix = !r.text.includes(":");
                return (
                  <li key="custom" id={`${id}-opt-${i}`} data-index={i} role="option" aria-selected={false}
                    onMouseDown={(e) => e.preventDefault()} onMouseEnter={() => setActive(i)} onClick={() => choose(r.text)}
                    className={`mt-1 flex cursor-pointer items-start gap-2 rounded-lg border-t border-line px-2.5 py-2 text-sm ${isActive ? "bg-blueprint-soft" : ""}`}>
                    <PencilLine size={15} className="mt-0.5 shrink-0 text-blueprint" />
                    <span className="min-w-0">
                      <span className="block">Usar <b className="break-all">“{r.text}”</b></span>
                      <span className="block text-[12px] text-muted">
                        Fora da lista: o custo não será calculado.{noPrefix ? ` Sem "provedor:", usa ${PROVIDER[defaultProvider] ?? defaultProvider}.` : ""}
                      </span>
                    </span>
                  </li>
                );
              }
              const o = r.o;
              const selected = o.id === value;
              return (
                <li key={o.id} id={`${id}-opt-${i}`} data-index={i} role="option" aria-selected={selected}
                  onMouseDown={(e) => e.preventDefault()} onMouseEnter={() => setActive(i)} onClick={() => choose(o.id)}
                  className={`flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm ${isActive ? "bg-blueprint-soft" : ""}`}>
                  <span className="flex w-4 shrink-0 justify-center">{selected && <Check size={15} className="text-blueprint" />}</span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-1.5">
                      <b className="font-medium">{o.name}</b>
                      {o.id === defaultId && <span className="rounded bg-paper px-1 text-[10px] font-semibold uppercase text-muted">padrão</span>}
                    </span>
                    <span className="block text-[12px] text-muted">{PROVIDER[o.provider] ?? o.provider}</span>
                  </span>
                  {o.input_price !== null && o.output_price !== null && (
                    <Tooltip content="Preço em US$ por milhão de tokens: entrada / saída">
                      <span className="cursor-help whitespace-nowrap text-right text-[12px] tabular-nums text-muted">US$ {usd(o.input_price)} / {usd(o.output_price)}</span>
                    </Tooltip>
                  )}
                </li>
              );
            })}
            {!rows.length && <li className="px-3 py-4 text-center text-sm text-muted">Digite o id do modelo (ex.: anthropic:nome-do-modelo).</li>}
          </ul>
          <div className="border-t border-line px-3 py-1.5 text-[11px] text-muted">↑ ↓ navegar · Enter escolher · Esc cancelar · ou digite outro modelo</div>
        </div>
      )}
    </div>
  );
}
