import { AlertTriangle, ArrowLeft, Check, ChevronDown, PencilLine } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { ModelOption } from "../../api";
import { providerLabel } from "../../format";
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
const VALID = /^([a-z0-9_-]+:)?[\w.\-/@]+$/i;

/**
 * Seleção de modelo: um botão abre a lista dos modelos conhecidos (com preço). A última opção,
 * "Outro modelo…", troca a lista por um campo para digitar o id. Teclado: ↑ ↓ navegam, Enter escolhe, Esc fecha.
 */
export function ModelCombobox({ label, value, onChange, options, defaultId, defaultProvider = "anthropic", availableProviders, hint }: Props) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const field = useRef<HTMLInputElement>(null);
  const id = useId();

  const known = options.find((o) => o.id === value || o.name === value);
  const custom = !!value && !known;
  // linhas da lista: modelos conhecidos e, por último, "Outro modelo…"
  const rows = [...options.map((o) => ({ kind: "option" as const, o })), { kind: "other" as const }];
  const providerOf = (v: string) => (v.includes(":") ? v.split(":")[0].toLowerCase() : defaultProvider);
  const keyless = (v: string) => !!availableProviders && !availableProviders.includes(providerOf(v));

  const close = (refocus = true) => {
    setOpen(false);
    setEditing(false);
    if (refocus) trigger.current?.focus();
  };
  const openList = () => {
    setEditing(false);
    setActive(known ? options.indexOf(known) : custom ? rows.length - 1 : 0);
    setOpen(true);
  };
  const startEdit = () => {
    setDraft(custom ? value : "");
    setEditing(true);
  };
  const choose = (v: string) => {
    onChange(v);
    close();
  };

  useEffect(() => {
    if (!open) return;
    const out = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) close(false); };
    document.addEventListener("mousedown", out);
    return () => document.removeEventListener("mousedown", out);
  });
  useEffect(() => {
    if (open && !editing) list.current?.focus();
    if (open && editing) field.current?.focus();
  }, [open, editing]);
  useEffect(() => {
    list.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const onListKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(rows.length - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === "Home") { e.preventDefault(); setActive(0); }
    else if (e.key === "End") { e.preventDefault(); setActive(rows.length - 1); }
    else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      const r = rows[active];
      if (r.kind === "option") choose(r.o.id);
      else startEdit();
    } else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === "Tab") close(false);
  };

  const draftOk = VALID.test(draft.trim());
  const draftKnown = options.find((o) => o.id.toLowerCase() === draft.trim().toLowerCase() || o.name.toLowerCase() === draft.trim().toLowerCase());
  const saveDraft = () => { if (draftOk) choose(draftKnown ? draftKnown.id : draft.trim()); };

  return (
    <div ref={root} className="relative">
      <button ref={trigger} type="button" aria-haspopup="listbox" aria-expanded={open} aria-controls={`${id}-pop`}
        aria-label={`Modelo ${label.toLowerCase()}: ${value || "nenhum"}`}
        onClick={() => (open ? close() : openList())}
        onKeyDown={(e) => { if (!open && (e.key === "ArrowDown" || e.key === "ArrowUp")) { e.preventDefault(); openList(); } }}
        className={`flex items-center gap-2 rounded-md border bg-sheet py-1 pl-2 pr-1.5 text-left text-[13px] transition-colors ${open ? "border-blueprint ring-2 ring-blueprint/15" : "border-line hover:border-ink/25"}`}>
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">{label}</span>
        <span className="min-w-0 max-w-52 truncate font-medium">{known ? known.name : value || "escolher…"}</span>
        {known && <span className="hidden text-[11px] text-muted xl:inline">{providerLabel(known.provider)}</span>}
        {custom && (
          <Tooltip content={keyless(value) ? `O provedor "${providerOf(value)}" não tem credencial configurada: a execução vai falhar.` : "Modelo personalizado, fora da tabela de preços: a análise roda, mas o custo não é calculado."}>
            <span className={`flex items-center gap-1 rounded px-1 text-[10px] font-semibold uppercase ${keyless(value) ? "bg-[#f8e4e2] text-bad" : "bg-[#fdf1dc] text-warn"}`}>
              <AlertTriangle size={11} /> personalizado
            </span>
          </Tooltip>
        )}
        <ChevronDown size={15} className={`shrink-0 text-muted transition ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div id={`${id}-pop`} className="surgir absolute right-0 z-40 mt-1.5 w-[22rem] overflow-hidden rounded-xl border border-line bg-sheet shadow-xl">
          {!editing ? (
            <>
              {hint && <div className="border-b border-line bg-paper/60 px-3 py-1.5 text-[12px] text-muted">{hint}</div>}
              <ul ref={list} role="listbox" tabIndex={-1} aria-label={`Modelos para ${label.toLowerCase()}`}
                aria-activedescendant={`${id}-opt-${active}`} onKeyDown={onListKey} className="max-h-72 overflow-y-auto p-1 outline-none">
                {rows.map((r, i) => {
                  const isActive = i === active;
                  if (r.kind === "other") {
                    return (
                      <li key="other" id={`${id}-opt-${i}`} data-index={i} role="option" aria-selected={custom}
                        onMouseEnter={() => setActive(i)} onClick={startEdit}
                        className={`mt-1 flex cursor-pointer items-center gap-2 rounded-lg border-t border-line px-2.5 py-2 text-sm ${isActive ? "bg-blueprint-soft" : ""}`}>
                        <span className="flex w-4 shrink-0 justify-center">{custom ? <Check size={15} className="text-blueprint" /> : <PencilLine size={14} className="text-blueprint" />}</span>
                        <span className="min-w-0 flex-1">
                          <span className="block font-medium">Outro modelo…</span>
                          <span className="block truncate text-[12px] text-muted">{custom ? `Atual: ${value}. Clique para editar.` : "Digitar o id de um modelo fora da lista"}</span>
                        </span>
                      </li>
                    );
                  }
                  const o = r.o;
                  const selected = o.id === value || o.name === value;
                  return (
                    <li key={o.id} id={`${id}-opt-${i}`} data-index={i} role="option" aria-selected={selected}
                      onMouseEnter={() => setActive(i)} onClick={() => choose(o.id)}
                      className={`flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm ${isActive ? "bg-blueprint-soft" : ""}`}>
                      <span className="flex w-4 shrink-0 justify-center">{selected && <Check size={15} className="text-blueprint" />}</span>
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-1.5">
                          <b className="font-medium">{o.name}</b>
                          {o.id === defaultId && <span className="rounded bg-paper px-1 text-[10px] font-semibold uppercase text-muted">padrão</span>}
                        </span>
                        <span className="block text-[12px] text-muted">{providerLabel(o.provider)}</span>
                      </span>
                      {o.input_price !== null && o.output_price !== null && (
                        <span title="US$ por milhão de tokens: entrada / saída" className="whitespace-nowrap text-right text-[12px] tabular-nums text-muted">US$ {usd(o.input_price)} / {usd(o.output_price)}</span>
                      )}
                    </li>
                  );
                })}
              </ul>
              <div className="border-t border-line px-3 py-1.5 text-[11px] text-muted">↑ ↓ navegar · Enter escolher · Esc fechar · preço em US$ por milhão de tokens</div>
            </>
          ) : (
            <form onSubmit={(e) => { e.preventDefault(); saveDraft(); }} className="space-y-3 p-3"
              onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setEditing(false); } }}>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => setEditing(false)} aria-label="Voltar para a lista" className="rounded-md p-1 text-muted hover:bg-paper hover:text-ink"><ArrowLeft size={16} /></button>
                <span className="text-sm font-semibold">Outro modelo · {label.toLowerCase()}</span>
              </div>
              <label className="block">
                <span className="mb-1 block text-[12px] text-muted">Id do modelo, no formato <code className="rounded bg-paper px-1">provedor:modelo</code></span>
                <input ref={field} value={draft} onChange={(e) => setDraft(e.target.value)} spellCheck={false} placeholder="ex.: anthropic:nome-do-modelo"
                  aria-invalid={!!draft && !draftOk}
                  className={`w-full rounded-md border px-2.5 py-1.5 text-sm outline-none focus:ring-2 ${draft && !draftOk ? "border-bad focus:ring-bad/15" : "border-line focus:border-blueprint focus:ring-blueprint/15"}`} />
              </label>
              <div className="space-y-1 text-[12px]">
                {draft && !draftOk && <p className="text-bad">Use só letras, números, ponto, hífen e barra, sem espaços.</p>}
                {draftOk && draftKnown && <p className="text-ok">Este modelo já está na lista: {draftKnown.name}.</p>}
                {draftOk && !draftKnown && (
                  <>
                    {!draft.includes(":") && <p className="text-muted">Sem “provedor:”, será usado {providerLabel(defaultProvider)}.</p>}
                    {keyless(draft.trim())
                      ? <p className="flex items-center gap-1 text-bad"><AlertTriangle size={12} /> O provedor “{providerOf(draft.trim())}” não tem credencial configurada: a execução vai falhar.</p>
                      : <p className="text-warn">Fora da tabela de preços: a análise roda, mas o custo não é calculado.</p>}
                  </>
                )}
                {availableProviders && (
                  <p className="text-muted">Provedores com credencial: {availableProviders.length ? availableProviders.map(providerLabel).join(", ") : "nenhum"}.</p>
                )}
              </div>
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setEditing(false)} className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-paper">Voltar</button>
                <button type="submit" disabled={!draftOk} className="rounded-lg bg-blueprint px-3 py-1.5 text-sm font-semibold text-white hover:bg-[#1d44a0] disabled:opacity-50">Usar este modelo</button>
              </div>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
