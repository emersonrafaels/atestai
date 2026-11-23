import {
  ArrowLeft, ArrowRight, BarChart3, Compass, Copy, FileDown, FileText, FlaskConical, Image as ImageIcon, ListChecks,
  Receipt, ScanSearch, Search, Settings, ShieldAlert, SlidersHorizontal, ThumbsDown, X, Zap, type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { PANEL_VERSION, versionLabel } from "../version";

const DONE_KEY = "atest.onboarding.done";
/** Já viu o onboarding? (primeira visita: abre sozinho) */
export const onboardingDone = () => { try { return localStorage.getItem(DONE_KEY) === "1"; } catch { return true; } };
const markDone = () => { try { localStorage.setItem(DONE_KEY, "1"); } catch { /* armazenamento indisponível */ } };

interface Slide {
  icon: LucideIcon;
  tone: string;
  kicker: string;
  title: string;
  text: ReactNode;
  points: { icon: LucideIcon; text: ReactNode }[];
}

const SLIDES: Slide[] = [
  {
    icon: ScanSearch, tone: "#2450b8", kicker: "Boas-vindas", title: "Pré-análise de chamados SETA e SISR",
    text: <>O Atest.AI confere cada chamado como um engenheiro de manutenção e sugere um parecer. <b>A decisão final é sempre sua.</b></>,
    points: [
      { icon: ListChecks, text: <>Checklist mínimo de documentos da categoria e da etapa</> },
      { icon: Receipt, text: <>Escopo, orçamento (itens × pedido × LPU), fotos e documentos lidos por OCR</> },
      { icon: Zap, text: <>Recomendação com score de 0 a 100, confiança e motivo</> },
    ],
  },
  {
    icon: Search, tone: "#2450b8", kicker: "1 · Encontre", title: "Escolha os chamados na lista",
    text: <>A lista à esquerda traz os chamados do conjunto escolhido. Marque os que quer analisar e clique em <b>Analisar</b>.</>,
    points: [
      { icon: Search, text: <>Busca por nº do chamado (vários de uma vez), agência, fornecedor ou texto. Atalho: <kbd>/</kbd></> },
      { icon: SlidersHorizontal, text: <><b>Filtros</b>: agência por nome ou núm. do ponto, etapa, categoria, parecer, valor, data…</> },
      { icon: Settings, text: <>Escolha o provedor e os modelos; envio <b>Síncrono</b> ou em <b>Lote</b> (metade do custo)</> },
    ],
  },
  {
    icon: Zap, tone: "#008300", kicker: "2 · Decida", title: "Parecer em Resumo ou Completo",
    text: <>O <b>Resumo</b> traz só o que pesa na decisão; o <b>Completo</b>, a conta inteira com cada evidência.</>,
    points: [
      { icon: Zap, text: <>Resumo: recomendação, pontos de atenção do mais grave ao mais leve e a decisão, na mesma tela</> },
      { icon: ThumbsDown, text: <>Marque <b>Não procede</b> num apontamento errado: a régua recalcula na hora</> },
      { icon: FileText, text: <>Completo: checklist, racional do engenheiro, como o score foi calculado e a evidência de cada ponto</> },
    ],
  },
  {
    icon: ShieldAlert, tone: "#6250d6", kicker: "3 · Integridade", title: "Foto reaproveitada e chamado duplicado",
    text: <>Antes de olhar o preço, o Atest.AI procura sinais de que o chamado não deveria seguir.</>,
    points: [
      { icon: ImageIcon, text: <>Foto reaproveitada de outro chamado vira <b>trava</b>: devolve qualquer que seja o score</> },
      { icon: Copy, text: <>Chamados da mesma agência abertos até 60 dias antes ou depois (ou ainda abertos): <b>possível duplicado</b>, com comparação lado a lado</> },
    ],
  },
  {
    icon: Receipt, tone: "#b26a00", kicker: "4 · Orçamento", title: "Itens, LPU e preço de mercado",
    text: <>Cada item é ligado ao que foi pedido e comparado com a LPU da esteira ou com o preço de mercado anexado.</>,
    points: [
      { icon: Receipt, text: <>Item fora do escopo, troca sem justificativa, quantidade acima do que as fotos mostram</> },
      { icon: ShieldAlert, text: <>Preço acima da LPU ou do mercado; item sem referência leva a <b>aprovar com ressalvas</b></> },
      { icon: Search, text: <>Passe o mouse em “item 3” no texto para ver o nome do item; clique para ir à linha</> },
    ],
  },
  {
    icon: FileDown, tone: "#c62f2f", kicker: "5 · Compartilhe", title: "Exporte o caso e o parecer",
    text: <>No topo do chamado, <b>Exportar parecer</b> gera o relatório completo, com fotos e documentos.</>,
    points: [
      { icon: FileDown, text: <><b>PDF</b> para anexar ou enviar; <b>HTML</b> que abre em qualquer navegador</> },
      { icon: FileText, text: <><b>JSON</b> com o parecer inteiro, para auditoria ou integração</> },
    ],
  },
  {
    icon: Compass, tone: "#2450b8", kicker: "6 · Mais do painel", title: "As outras áreas",
    text: <>Além da Análise, o menu do topo leva a:</>,
    points: [
      { icon: ListChecks, text: <><b>Cenários</b>: o roteiro de cada caso de demonstração e o que esperar dele</> },
      { icon: FlaskConical, text: <><b>Validação</b>: a qualidade do Atest.AI contra chamados com gabarito</> },
      { icon: BarChart3, text: <><b>Operação</b>: volume, custo, tempo e as decisões das pessoas analistas</> },
      { icon: Settings, text: <><b>Configuração</b>: checklists, régua e cadastros (com usuário e senha)</> },
    ],
  },
];

/**
 * Lightbox de boas-vindas: as principais funções do painel, uma por tela. Abre sozinho na primeira visita e pelo
 * menu Ajuda; a última tela oferece o tour guiado da tela atual.
 */
export function Onboarding({ onClose, onTour }: { onClose: () => void; onTour: () => void }) {
  const [i, setI] = useState(0);
  const last = i === SLIDES.length - 1;
  const primary = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => { markDone(); onClose(); }, [onClose]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      else if (e.key === "ArrowRight") setI((k) => Math.min(SLIDES.length - 1, k + 1));
      else if (e.key === "ArrowLeft") setI((k) => Math.max(0, k - 1));
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [close]);
  useEffect(() => { primary.current?.focus(); }, [i]);

  const s = SLIDES[i];
  const Icon = s.icon;
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="onboarding-title" className="fixed inset-0 z-[60] flex items-center justify-center bg-ink/60 p-4" onClick={close}>
      <div className="surgir flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-sheet shadow-2xl md:flex-row" onClick={(e) => e.stopPropagation()}>
        {/* faixa colorida com o ícone da tela */}
        <div className="relative flex shrink-0 flex-col justify-between p-6 text-white md:w-60" style={{ background: `linear-gradient(160deg, ${s.tone}, #12233f)` }}>
          <div>
            <p className="text-[12px] font-semibold uppercase tracking-wider text-white/75">Atest.AI</p>
            <p className="text-[12px] text-white/60">Painel {`v${PANEL_VERSION}`}</p>
          </div>
          <div className="my-6 flex justify-center md:my-0">
            <span className="flex size-24 items-center justify-center rounded-3xl bg-white/15 ring-1 ring-white/25 backdrop-blur">
              <Icon size={46} strokeWidth={1.6} />
            </span>
          </div>
          <p className="hidden text-[12px] text-white/70 md:block">{i + 1} de {SLIDES.length}</p>
        </div>

        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex items-start justify-between gap-3 px-6 pt-5">
            <p className="text-[12px] font-semibold uppercase tracking-wider" style={{ color: s.tone }}>{s.kicker}</p>
            <button aria-label="Fechar" onClick={close} className="-mr-2 -mt-1 rounded-full p-1.5 text-muted hover:bg-paper hover:text-ink"><X size={18} /></button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-4">
            <h2 id="onboarding-title" className="largo mt-1 text-2xl font-bold leading-tight">{s.title}</h2>
            <p className="mt-2 text-[15px] leading-relaxed text-ink/85">{s.text}</p>
            <ul className="mt-4 space-y-2.5">
              {s.points.map((pt, k) => {
                const P = pt.icon;
                return (
                  <li key={k} className="flex items-start gap-3 text-[14px] leading-snug">
                    <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-paper" style={{ color: s.tone }}><P size={15} /></span>
                    <span className="pt-1">{pt.text}</span>
                  </li>
                );
              })}
            </ul>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-6 py-4">
            <div className="flex items-center gap-1.5" role="tablist" aria-label="Telas">
              {SLIDES.map((sl, k) => (
                <button key={k} role="tab" aria-selected={k === i} aria-label={`${k + 1}. ${sl.title}`} onClick={() => setI(k)}
                  className={`h-2 rounded-full transition-all ${k === i ? "w-6 bg-blueprint" : "w-2 bg-line hover:bg-muted/50"}`} />
              ))}
            </div>
            <div className="flex items-center gap-2">
              {i > 0 && (
                <button onClick={() => setI(i - 1)} className="flex items-center gap-1 rounded-lg px-3 py-2 text-sm text-muted hover:bg-paper hover:text-ink">
                  <ArrowLeft size={15} /> Anterior
                </button>
              )}
              {!last && <button onClick={close} className="rounded-lg px-3 py-2 text-sm text-muted hover:bg-paper hover:text-ink">Pular</button>}
              {last && (
                <button onClick={() => { close(); onTour(); }} className="flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-sm font-medium hover:border-blueprint hover:text-blueprint">
                  <Compass size={15} /> Fazer o tour guiado
                </button>
              )}
              <button ref={primary} onClick={() => (last ? close() : setI(i + 1))}
                className="flex items-center gap-1.5 rounded-lg bg-blueprint px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-[#1c3f94]">
                {last ? "Começar a usar" : <>Próximo <ArrowRight size={15} /></>}
              </button>
            </div>
          </div>
          <p className="border-t border-line/60 bg-paper/50 px-6 py-1.5 text-right text-[11px] text-muted">Painel web do Atest.AI {versionLabel}</p>
        </div>
      </div>
    </div>
  );
}
