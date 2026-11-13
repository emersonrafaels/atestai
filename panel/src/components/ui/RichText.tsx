import { Camera, ClipboardList, FileText, Ruler, Tag } from "lucide-react";
import type { ReactNode } from "react";

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
    String.raw`(?<qty>\b\d+(?:[.,]\d+)?\s?(?:m²|m2|m³|m3|ml|un|unid\.?|peças?|pontos?|chapas?|quadros?)(?![\p{L}\d]))`,
  ].join("|"),
  "giu",
);

type OnItems = (items: number[]) => void;

/** Destaca valores, percentuais, quantidades e referências a itens/anexos dentro de um texto corrido. */
export function highlight(text: string, onItems?: OnItems): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    const i = m.index ?? 0;
    if (i > last) out.push(text.slice(last, i));
    const g = m.groups ?? {};
    const s = m[0];
    const k = `${i}`;
    if (g.money) out.push(<b key={k} className="whitespace-nowrap font-semibold tabular-nums text-ink">{s}</b>);
    else if (g.pct) {
      const around = text.slice(i, i + s.length + 14).toLowerCase();
      const bad = /acima|a mais|além/.test(around);
      out.push(<b key={k} className={`whitespace-nowrap font-semibold tabular-nums ${bad ? "text-bad" : "text-ink"}`}>{s}</b>);
    } else if (g.item) {
      const nums = [...s.matchAll(/\d+/g)].map((x) => Number(x[0]));
      out.push(onItems
        ? <button key={k} type="button" onClick={() => onItems(nums)} title="Ver no orçamento"
            className="whitespace-nowrap rounded bg-blueprint-soft px-0.5 font-medium text-blueprint hover:underline">{s}</button>
        : <span key={k} className="whitespace-nowrap rounded bg-blueprint-soft px-0.5 font-medium text-blueprint">{s}</span>);
    } else if (g.annex) out.push(<span key={k} className="whitespace-nowrap font-medium text-ink">{s}</span>);
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
  { key: "price", label: "Preço", icon: Tag, re: /\bpreço|anúncio|tabela de referência|valor de mercado/i },
  { key: "photos", label: "Fotos", icon: Camera, re: /\bfotos?\b/i },
  { key: "docs", label: "Documentos", icon: FileText, re: /\bdocumento|print|laudo|nota fiscal|\bART\b/i },
  { key: "scope", label: "Pedido", icon: ClipboardList, re: /orçamento|\bitens?\b|pedid|escopo|serviço/i },
] as const;

function topicOf(sentence: string) {
  return TOPICS.find((t) => t.re.test(sentence));
}

/** Parágrafo corrido → lista de frases, cada uma com o assunto (pedido, quantidade, preço, fotos) e os números em destaque. */
export function SentenceList({ text, onItems, topics = true, className = "" }: { text: string; onItems?: OnItems; topics?: boolean; className?: string }) {
  const list = sentences(text, true);
  if (list.length <= 1) return <p className={`leading-relaxed ${className}`}>{highlight(text, onItems)}</p>;
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
            <span className="min-w-0">{highlight(s, onItems)}</span>
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
