import { Camera, ClipboardList, FileText, Ruler, Tag } from "lucide-react";
import { createContext, useContext, type ReactNode } from "react";
import type { EvaluatedItem, LpuItem, QuoteItem } from "../../api";
import { brl, num, LPU, lpuName } from "../../format";
import { Tooltip } from "./Tooltip";

/**
 * Textos longos do modelo (parecer, mensagem ao fornecedor, leitura das fotos) em pedaços legíveis:
 * uma frase por linha e os números que importam em destaque (R$, %, quantidades, itens e anexos).
 */

const TOKEN = new RegExp(
  [
    String.raw`(?<money>R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})?)`,
    String.raw`(?<pct>\d+(?:,\d+)?\s?%)`,
    // "itens 1, 2 e 4", mas não engole a quantidade em "item 1, 1 un"
    String.raw`(?<item>\bite(?:m|ns)\s\d+(?:(?:,\s?|\se\s)\d+(?![.,]?\d)(?!\s?(?:m²|m2|m³|m\b|ml|un|unid|peç|pç|R\$)))*)`,
    String.raw`(?<annex>\bAnexos?\s\d+(?:(?:,\s?|\se\s)\d+)*)`,
    // código da LPU (ex.: DRY-001): vira o nome do item, com código, descrição e preço no hover
    String.raw`(?<lpu>\b[A-Z]{2,5}-\d{3}\b)`,
    // número de chamado (8 dígitos): vira link quando é um chamado da mesma agência comparado com este
    String.raw`(?<ticket>\b\d{8}\b)`,
    String.raw`(?<qty>\b\d+(?:[.,]\d+)?\s?(?:m²|m2|m³|m3|ml|un|unid\.?|peças?|pontos?|chapas?|quadros?)(?![\p{L}\d]))`,
  ].join("|"),
  "giu",
);

type OnItems = (items: number[]) => void;

/** Item do orçamento como aparece no balão; `classification` vem do parecer (itens avaliados). */
export type ItemInfo = QuoteItem & { classification?: "compliant" | "out_of_scope" | "to_justify" };

/**
 * Itens do orçamento do chamado aberto, pelo número. Quem mostra um parecer fornece a lista, e cada "item 3" ou
 * "itens 1, 2 e 4" citado no texto ganha um balão com o nome do item ao passar o mouse.
 */
export const QuoteItemsContext = createContext<Map<number, ItemInfo> | null>(null);

export function itemMap(...lists: (ItemInfo[] | null | undefined)[]): Map<number, ItemInfo> {
  const m = new Map<number, ItemInfo>();
  for (const list of lists) for (const it of list ?? []) if (!m.has(it.n)) m.set(it.n, it);
  return m;
}

const CLASSIFICATION_TAG: Record<string, string> = { out_of_scope: "fora do escopo", to_justify: "a justificar" };

/** Balão: número, nome, quantidade e valor de cada item citado, com as marcas que importam para o parecer. */
function ItemTip({ nums, items, clickable }: { nums: number[]; items: Map<number, ItemInfo>; clickable: boolean }) {
  return (
    <span className="block space-y-1.5 text-left">
      {nums.map((n) => {
        const it = items.get(n);
        const tags = it ? [it.classification && CLASSIFICATION_TAG[it.classification], it.lpu === false && "fora da LPU"].filter(Boolean) : [];
        return (
          <span key={n} className="block">
            <b className="tabular-nums">Item {n}</b>
            {it ? (
              <>
                {" — "}{it.description}
                <span className="block tabular-nums opacity-75">
                  {num(it.quantity)} {it.unit} × {brl(it.unit_value)} = {brl(it.total_value)}
                  {tags.length > 0 && <> · <span className="font-semibold text-[#ffd27a]">{tags.join(" · ")}</span></>}
                </span>
              </>
            ) : <span className="opacity-75"> — não está no orçamento</span>}
          </span>
        );
      })}
      {clickable && <span className="block border-t border-white/20 pt-1 opacity-70">Clique para ver no orçamento</span>}
    </span>
  );
}

/** Referência a itens no texto: leva ao orçamento no clique e mostra o nome dos itens no hover (quando conhecidos). */
function ItemRef({ text, nums, onItems }: { text: string; nums: number[]; onItems?: OnItems }) {
  const items = useContext(QuoteItemsContext);
  const known = !!items && nums.some((n) => items.has(n));
  const base = "whitespace-nowrap rounded bg-blueprint-soft px-0.5 font-medium text-blueprint transition-colors";
  const el = onItems
    ? <button type="button" onClick={() => onItems(nums)} title={known ? undefined : "Ver no orçamento"}
        aria-label={known ? `${text}: ${nums.map((n) => items!.get(n)?.description ?? `item ${n}`).join("; ")}. Ver no orçamento` : undefined}
        className={`${base} underline decoration-dotted decoration-blueprint/50 underline-offset-2 hover:bg-blueprint hover:text-white hover:decoration-transparent focus-visible:bg-blueprint focus-visible:text-white`}>{text}</button>
    : <span tabIndex={known ? 0 : undefined}
        className={`${base} ${known ? "cursor-help underline decoration-dotted decoration-blueprint/50 underline-offset-2 hover:bg-blueprint/15" : ""}`}>{text}</span>;
  if (!known) return el;
  return <Tooltip className="inline" delay={80} content={<ItemTip nums={nums} items={items!} clickable={!!onItems} />}>{el}</Tooltip>;
}

/**
 * Item da LPU citado no texto: aparece pelo nome; o hover mostra código, esteira, descrição completa e preço.
 * `fallback` (ex.: o similar gravado no parecer) vale quando a LPU ainda não carregou ou mudou desde a análise.
 */
export function LpuRef({ code, label, fallback }: { code: string; label?: string; fallback?: LpuItem | null }) {
  const it = LPU.get(code) ?? (fallback ? { ...fallback, workstream: "" } : undefined);
  if (!it) return <>{code}</>;
  const tip = (
    <span className="block text-left">
      <b className="tabular-nums">{code}</b>{it.workstream && <span className="opacity-75"> · LPU {it.workstream}</span>}
      <span className="block">{it.description}</span>
      <span className="block tabular-nums opacity-75">{brl(it.reference_price)} por {it.unit}</span>
    </span>
  );
  return (
    <Tooltip className="inline" delay={80} content={tip}>
      <span tabIndex={0} aria-label={`${it.description}, código ${code} da LPU, ${brl(it.reference_price)} por ${it.unit}`}
        className="cursor-help whitespace-nowrap rounded bg-blueprint-soft px-0.5 font-medium text-blueprint underline decoration-dotted decoration-blueprint/50 underline-offset-2 hover:bg-blueprint/15">
        {label ?? lpuName(it)}
      </span>
    </Tooltip>
  );
}

/** Situação do item frente à LPU na linha do orçamento: item da LPU (pelo nome), Não LPU (com o similar) ou sem referência. */
export function LpuNote({ item }: { item: Pick<EvaluatedItem, "lpu" | "lpu_code" | "similar_lpu"> }) {
  if (item.lpu === false) {
    const s = item.similar_lpu;
    return s ? <> · Não LPU · similar na LPU: <LpuRef code={s.code} fallback={s} /> ({brl(s.reference_price)}/{s.unit})</> : <> · Não LPU</>;
  }
  const c = item.lpu_code;
  return c && c !== "NO_REFERENCE" && c !== "SEM_REFERENCIA" ? <> · <LpuRef code={c} /></> : <> · sem referência na LPU</>;
}

/** Chamados citáveis no texto (os da mesma agência) e o que fazer ao clicar num deles. */
export interface TicketLinks {
  ids: Set<string>;
  open: (id: string) => void;
  /** chamados marcados como possível duplicado (link em vermelho) */
  flagged?: Set<string>;
}

/** Destaca valores, percentuais, quantidades e referências a itens/anexos dentro de um texto corrido. */
export function highlight(text: string, onItems?: OnItems, tickets?: TicketLinks): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    const i = m.index ?? 0;
    if (i < last) continue; // dentro da descrição da LPU que já foi trocada pelo nome
    if (i > last) out.push(text.slice(last, i));
    const g = m.groups ?? {};
    const s = m[0];
    const k = `${i}`;
    if (g.lpu) {
      const it = LPU.get(s);
      // "(DRY-001)" sozinho entre parênteses é anotação ao lado do nome que o texto já trouxe: fica o código, com hover
      const aside = text[i - 1] === "(" && text[i + s.length] === ")";
      out.push(it ? <LpuRef key={k} code={s} label={aside ? s : undefined} /> : s);
      // "DRY-001 (Parede de drywall …)": a descrição entre parênteses sai, o nome já está no lugar do código
      const paren = it ? ` (${it.description})` : "";
      last = i + s.length + (paren && text.startsWith(paren, i + s.length) ? paren.length : 0);
      continue;
    }
    if (g.money) out.push(<b key={k} className="whitespace-nowrap font-semibold tabular-nums text-ink">{s}</b>);
    else if (g.pct) {
      const around = text.slice(i, i + s.length + 14).toLowerCase();
      const bad = /acima|a mais|além/.test(around);
      out.push(<b key={k} className={`whitespace-nowrap font-semibold tabular-nums ${bad ? "text-bad" : "text-ink"}`}>{s}</b>);
    } else if (g.item) {
      const nums = [...s.matchAll(/\d+/g)].map((x) => Number(x[0]));
      out.push(<ItemRef key={k} text={s} nums={nums} onItems={onItems} />);
    } else if (g.annex) out.push(<span key={k} className="whitespace-nowrap font-medium text-ink">{s}</span>);
    else if (g.ticket) {
      const dup = tickets?.flagged?.has(s);
      out.push(tickets?.ids.has(s)
        ? <button key={k} type="button" onClick={() => tickets.open(s)} title="Comparar os dois chamados"
            className={`inline-flex items-center whitespace-nowrap rounded px-0.5 font-semibold tabular-nums underline decoration-dotted underline-offset-2 hover:decoration-solid ${dup ? "bg-[#fbefed] text-bad" : "bg-blueprint-soft text-blueprint"}`}>{s}</button>
        : s);
    }
    else out.push(<b key={k} className="whitespace-nowrap font-semibold tabular-nums text-ink">{s}</b>);
    last = i + s.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/**
 * Quebra em frases. Não corta em "R$ 1.627,61" nem em "100x50cm." no meio: só corta depois de pontuação + espaço + maiúscula.
 * Com `semicolons`, frases longas emendadas com ";" também viram linhas próprias.
 */
export function sentences(text: string, semicolons = false): string[] {
  const list = text.replace(/\s+/g, " ").trim().split(/(?<=[.!?])\s+(?=[A-ZÀ-Ý"“(])/u);
  const parts = semicolons ? list.flatMap((s) => s.split(/;\s+/).map((x, i, all) => (i < all.length - 1 ? `${x}.` : x))) : list;
  return parts.map((s) => s.trim()).filter(Boolean).map((s) => s.charAt(0).toUpperCase() + s.slice(1));
}

/** Ações separadas por ";" ou quebra de linha (como a mensagem ao fornecedor), cada uma começando com maiúscula. */
export function actions(text: string): string[] {
  const parts = text.split(/\s*(?:;|\n+)\s*/).map((s) => s.trim().replace(/^[-•\d.)\s]+/, "").replace(/[.;]+$/, "")).filter(Boolean);
  const list = parts.length > 1 ? parts : sentences(text).map((s) => s.replace(/[.;]+$/, ""));
  return list.map((s) => s.charAt(0).toUpperCase() + s.slice(1));
}

const TOPICS = [
  { key: "qty", label: "Quantidade", icon: Ruler, re: /\bquantidade|cobra(?:m|do)?\s+\d|\bm²|peças?\b|medida/i },
  { key: "price", label: "Preço", icon: Tag, re: /\bpreço|anúncio|\bLPU\b|tabela de referência|valor de mercado/i },
  { key: "photos", label: "Fotos", icon: Camera, re: /\bfotos?\b/i },
  { key: "docs", label: "Documentos", icon: FileText, re: /\bdocumento|print|laudo|nota fiscal|\bART\b/i },
  { key: "scope", label: "Pedido", icon: ClipboardList, re: /orçamento|\bitens?\b|pedid|escopo|serviço/i },
] as const;

function topicOf(sentence: string) {
  return TOPICS.find((t) => t.re.test(sentence));
}

/** Parágrafo corrido → lista de frases, cada uma com o assunto (pedido, quantidade, preço, fotos) e os números em destaque. */
export function SentenceList({ text, onItems, tickets, topics = true, className = "" }: { text: string; onItems?: OnItems; tickets?: TicketLinks; topics?: boolean; className?: string }) {
  const list = sentences(text, true);
  if (list.length <= 1) return <p className={`leading-relaxed ${className}`}>{highlight(text, onItems, tickets)}</p>;
  return (
    <ul className={`space-y-2 ${className}`}>
      {list.map((s, i) => {
        const t = topics ? topicOf(s) : undefined;
        const Icon = t?.icon;
        return (
          <li key={i} className="flex gap-2.5 leading-relaxed">
            {Icon
              ? <span title={t.label} className="mt-[3px] flex size-5 shrink-0 items-center justify-center rounded-md bg-paper text-muted"><Icon size={12} /></span>
              : <span className="mt-[9px] size-1.5 shrink-0 rounded-full bg-muted/60" />}
            <span className="min-w-0">{highlight(s, onItems, tickets)}</span>
          </li>
        );
      })}
    </ul>
  );
}

/** Divide "Recomendo X: resto." em manchete ("Recomendo X") e corpo, quando o texto abre assim. */
export function splitLead(text: string): { lead: string; body: string } {
  const m = /^\s*(Recomend[oa][^:.]{0,140}):\s*(.+)$/su.exec(text);
  if (!m) return { lead: "", body: text };
  const body = m[2].trim();
  return { lead: m[1].trim(), body: body.charAt(0).toUpperCase() + body.slice(1) };
}
