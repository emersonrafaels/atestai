import { ArrowRight, Check, ChevronRight, CircleDashed, FileWarning, Lock, ShieldAlert, ThumbsDown, Undo2, X } from "lucide-react";
import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { Assessment, Recommendation, RubricInfo } from "../api";
import { decisionPath, simulate, underCurrentRule, type DecisionStep, type DecisionStepId } from "../evidence";
import { CONFIDENCE_LABEL, CONFIDENCE_TEXT, READING_REDUCERS, REC, REDUCER_HELP, VALIDATION_SHORT, findingLabel } from "../format";
import { tint } from "./ScoreBadge";

export type ExplainKind = "confidence" | "recommendation";

interface Props {
  kind: ExplainKind;
  p: Assessment;
  rubric: RubricInfo;
  /** tipos marcados como "não procede" na revisão do parecer */
  unfounded: Set<string>;
  toggleUnfounded: (kind: string) => void;
  /** abre e rola até o apontamento de índice i */
  focusFinding: (i: number) => void;
  /** rola até a seção da decisão */
  goToDecision?: () => void;
  onSwitch: (kind: ExplainKind) => void;
  onClose: () => void;
}

/** O que cada recomendação quer dizer, em uma frase. */
const REC_MEANING: Record<Recommendation, string> = {
  approve: "O serviço confere com o pedido e as evidências: o score ficou na faixa de aprovação e nenhuma regra mais forte se aplicou.",
  approve_with_caveats: "O serviço pode ser aprovado, mas há pontos para orientar o fornecedor nos próximos chamados.",
  return_to_supplier: "O fornecedor precisa ajustar algo (orçamento, fotos ou documentos) antes de o chamado seguir.",
  return_locked: "Há indício grave de irregularidade (trava de integridade): o chamado volta qualquer que seja o score.",
  detailed_review: "A entrada não basta para concluir com segurança. O Atest.AI não aprova nem devolve: uma pessoa precisa revisar o chamado.",
  checklist_returned: "Faltou documento obrigatório do checklist mínimo: o chamado volta antes de qualquer análise e não recebe score.",
};

const STEP_TITLE: Record<DecisionStepId, string> = {
  checklist: "Checklist mínimo",
  lock: "Trava de integridade",
  gap: "Falta do fornecedor",
  confidence: "Confiança",
  amount: "Valor em questão",
  band: "Faixa do score",
};

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/**
 * Modal que explica a confiança (o que a reduziu e o que isso muda) ou a recomendação (por que a régua chegou nela).
 * Um leva ao outro, sem fechar.
 */
export function ExplainDialog(props: Props) {
  const { kind, p, onClose } = props;
  const dialog = useRef<HTMLDivElement>(null);

  // foco no modal ao abrir (e ao trocar de explicação); ao fechar, volta para quem abriu
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    return () => opener?.focus?.({ preventScroll: true });
  }, []);
  useEffect(() => { dialog.current?.focus(); }, [kind]);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  const rec = REC[p.recommendation];
  const level = p.confidence;
  const title = kind === "confidence"
    ? level ? <>Por que a confiança está <span className={CONFIDENCE_TEXT[level]}>{CONFIDENCE_LABEL[level]}</span>?</> : "Confiança"
    : <>Por que <span style={{ color: rec.color }}>{rec.label.charAt(0).toLowerCase() + rec.label.slice(1)}</span>?</>;
  const sub = kind === "confidence"
    ? "Confiança mede o quanto o modelo conseguiu ler e entender o que foi enviado (escopo, orçamento, fotos, documentos). Problemas que ele conseguiu ver, como preço acima, item fora do escopo ou serviço sem item no orçamento, viram apontamentos e não reduzem a confiança."
    : REC_MEANING[p.recommendation];

  return createPortal(
    <div className="fixed inset-0 z-[55] flex items-start justify-center overflow-y-auto bg-ink/60 p-4 sm:p-6 sm:pt-16" onClick={onClose}>
      <div ref={dialog} role="dialog" aria-modal="true" aria-labelledby="explain-title" aria-describedby="explain-sub" tabIndex={-1}
        className="surgir w-full max-w-2xl rounded-2xl bg-sheet shadow-2xl outline-none" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div className="min-w-0">
            <div className="mb-1 flex gap-1 text-[12px] font-medium" role="tablist" aria-label="Explicação">
              {(["recommendation", "confidence"] as const).filter((k) => k === "recommendation" || p.confidence).map((k) => (
                <button key={k} role="tab" aria-selected={kind === k} onClick={() => props.onSwitch(k)}
                  className={`rounded-full px-2.5 py-0.5 transition-colors ${kind === k ? "bg-ink text-white" : "text-muted hover:bg-paper hover:text-ink"}`}>
                  {k === "recommendation" ? "Recomendação" : "Confiança"}
                </button>
              ))}
            </div>
            <h2 id="explain-title" className="largo text-xl font-bold">{title}</h2>
            <p id="explain-sub" className="mt-0.5 text-sm text-muted">{sub}</p>
          </div>
          <button aria-label="Fechar" onClick={onClose} className="rounded-full p-1.5 hover:bg-paper"><X size={18} /></button>
        </header>

        <div className="max-h-[70vh] space-y-5 overflow-y-auto px-6 py-5">
          {kind === "confidence" ? <ConfidenceBody {...props} /> : <RecommendationBody {...props} />}
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-6 py-4">
          {kind === "confidence"
            ? <button onClick={() => props.onSwitch("recommendation")} className="flex items-center gap-1 text-sm font-medium text-blueprint hover:underline">
                Ver por que a recomendação é “{rec.label}” <ChevronRight size={15} />
              </button>
            : props.goToDecision && p.record_id
              ? <button onClick={() => { onClose(); props.goToDecision!(); }} className="flex items-center gap-1 text-sm font-medium text-blueprint hover:underline">
                  Ir para a decisão <ArrowRight size={15} />
                </button>
              : <span />}
          <button onClick={onClose} className="rounded-lg bg-ink px-4 py-1.5 text-sm font-semibold text-white hover:bg-[#1c3359]">Entendi</button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}

// ============================================================================ confiança
function ConfidenceBody({ p, rubric, unfounded, toggleUnfounded, focusFinding, onClose }: Props) {
  const level = p.confidence;
  const reducers = p.confidence_reducers;
  const { medium_with_n_reducers: med, low_with_n_reducers: low } = rubric.confidence;
  // a régua de hoje: pareceres antigos podem contar como redutor o que hoje é só apontamento
  const cur = useMemo(() => underCurrentRule(p, rubric), [p, rubric]);
  const path = useMemo(() => decisionPath(p, rubric), [p, rubric]);
  const sim = useMemo(() => simulate(p, rubric, unfounded), [p, rubric, unfounded]);
  const go = (i: number) => { onClose(); focusFinding(i); };
  const dropped = new Set(cur.dropped);
  const listed = [...reducers, ...cur.added];

  if (!level) {
    return <p className="text-sm text-muted">Este parecer não tem confiança calculada: o chamado parou no checklist mínimo, antes das validações.</p>;
  }

  // faixas da régua: quantos redutores levam a cada nível
  const tiers = ([
    { id: "high", from: 0, to: med - 1 },
    { id: "medium", from: med, to: low - 1 },
    { id: "low", from: low, to: Infinity },
  ] as const).filter((t) => t.to >= t.from);
  const range = (a: number, b: number) => (b === Infinity ? `${a} ou mais` : a === b ? `${a}` : `${a} a ${b}`);

  return (
    <>
      {cur.outdated && (
        <p className="rounded-lg border border-[#e9cf8f] bg-[#fdf6e4] px-3 py-2 text-[13px] leading-relaxed">
          Este parecer foi gerado com a régua <b>{p.rubric_version}</b>.
          {cur.dropped.length > 0 && <> Pela régua atual, {cur.dropped.length === 1 ? "um destes itens não reduz" : `${cur.dropped.length} destes itens não reduzem`} mais a confiança ({cur.dropped.map((r) => findingLabel(r).toLowerCase()).join(", ")}).</>}
          {cur.added.length > 0 && <> Pela régua atual, {cur.added.map((r) => findingLabel(r).toLowerCase()).join(", ")} passa{cur.added.length === 1 ? "" : "m"} a reduzir.</>}
          {" "}A confiança seria <b className={CONFIDENCE_TEXT[cur.p.confidence!]}>{CONFIDENCE_LABEL[cur.p.confidence!]}</b> e a recomendação <b style={{ color: REC[path.recommendation].color }}>{REC[path.recommendation].label}</b>.
          {" "}Rode a análise de novo para atualizar o parecer.
        </p>
      )}

      {/* a régua */}
      <section>
        <h3 className="mb-2 text-sm font-semibold">Como a régua chega ao nível</h3>
        <p className="mb-2.5 text-[13px] text-muted">
          Cada tipo diferente de dificuldade de leitura ou entendimento conta como <b className="text-ink">um redutor</b>, mesmo que apareça várias vezes.
          Este chamado tem <b className="text-ink">{plural(reducers.length, "redutor", "redutores")}</b>{cur.outdated ? <> no parecer gravado e <b className="text-ink">{cur.p.confidence_reducers.length}</b> pela régua atual</> : null}.
        </p>
        <ol className="grid gap-2 sm:grid-cols-3">
          {tiers.map((t) => {
            const on = level === t.id;
            return (
              <li key={t.id} className={`rounded-lg border-2 px-3 py-2 text-sm ${on ? "bg-sheet shadow-sm" : "border-line text-muted"}`}
                style={on ? { borderColor: `var(--color-${t.id === "high" ? "ok" : t.id === "medium" ? "warn" : "bad"})` } : undefined}>
                <div className={`font-semibold capitalize ${on ? CONFIDENCE_TEXT[t.id] : ""}`}>{CONFIDENCE_LABEL[t.id]}{on && <span className="ml-1.5 text-[11px] font-medium normal-case text-muted">este chamado</span>}</div>
                <div className="text-[12px]">{range(t.from, t.to)} redutor{t.to === t.from && t.from === 1 ? "" : "es"}</div>
                <div className="mt-0.5 text-[12px]">
                  {t.id === "high" ? "Segue a faixa do score" : t.id === "medium" ? "Segue a faixa, com aviso de revisar com atenção" : "Vai para análise detalhada"}
                </div>
              </li>
            );
          })}
        </ol>
      </section>

      {/* os redutores deste chamado */}
      <section>
        <h3 className="mb-2 text-sm font-semibold">{reducers.length ? `O que reduziu a confiança neste chamado (${reducers.length})` : "O que reduziu a confiança neste chamado"}</h3>
        {listed.length === 0 ? (
          <p className="rounded-lg bg-[#e3f2ea] px-3 py-2 text-sm text-ok">Nenhum redutor: a entrada foi suficiente para concluir.</p>
        ) : (
          <ul className="space-y-2.5">
            {listed.map((r) => {
              const idxs = p.findings.flatMap((f, i) => (f.kind === r ? [i] : []));
              const reading = READING_REDUCERS.has(r) || idxs.length === 0;
              const off = unfounded.has(r);
              const gone = dropped.has(r);  // a régua atual não conta mais como redutor
              const isNew = cur.added.includes(r);
              const help = REDUCER_HELP[r];
              const first = idxs.length ? p.findings[idxs[0]] : null;
              // e se só este redutor (além da revisão já feita) não procedesse?
              const whatIf = !reading && !off && !gone ? simulate(p, rubric, new Set([...unfounded, r])) : null;
              const changes = whatIf && sim && (whatIf.confidence !== sim.confidence || whatIf.recommendation !== sim.recommendation);
              return (
                <li key={r} className={`rounded-lg border border-line border-l-4 px-3.5 py-3 text-sm ${off || gone ? "opacity-70" : ""}`}
                  style={{ borderLeftColor: off || gone ? "var(--color-line)" : reading ? "var(--color-detail)" : "var(--color-warn)" }}>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {reading ? <FileWarning size={15} className="text-detail" /> : <ShieldAlert size={15} className="text-warn" />}
                    <span className={`font-semibold ${off ? "line-through decoration-ink/40" : ""}`}>{findingLabel(r)}</span>
                    <span className="rounded bg-paper px-1.5 py-0.5 text-[11px] font-semibold text-muted">
                      {reading ? "Falha de leitura" : `${VALIDATION_SHORT[first!.validation]} · ${plural(idxs.length, "apontamento", "apontamentos")}`}
                    </span>
                    {off && <span className="rounded bg-[#fbefed] px-1.5 py-0.5 text-[11px] font-semibold text-bad">Não procede</span>}
                    {gone && <span className="rounded bg-[#fdf6e4] px-1.5 py-0.5 text-[11px] font-semibold text-warn">Não reduz mais a confiança</span>}
                    {isNew && <span className="rounded bg-[#fdf6e4] px-1.5 py-0.5 text-[11px] font-semibold text-warn">Passou a reduzir (régua atual)</span>}
                  </div>
                  {gone ? (
                    <p className="mt-1 leading-relaxed text-ink/90">
                      {first?.description ?? findingLabel(r)}. Pela régua atual, é um problema {first?.validation === "photos" ? "das evidências" : first?.validation === "scope" ? "do chamado ou do orçamento" : "do orçamento"} que o modelo conseguiu ver, não uma dificuldade de leitura: segue como apontamento, mas não reduz a confiança.
                    </p>
                  ) : <p className="mt-1 leading-relaxed text-ink/90">{help?.what ?? first?.description ?? "Faltou informação para concluir."}</p>}
                  {first?.evidence && <p className="mt-1 line-clamp-2 text-[13px] text-muted">Neste chamado: {first.evidence}</p>}
                  {!gone && help?.todo && <p className="mt-1 text-[13px]"><b className="font-semibold">Como resolver:</b> <span className="text-muted">{help.todo}</span></p>}
                  {reading && <p className="mt-1 text-[12px] text-muted">Não é apontamento da régua: veio de uma falha na leitura automática, por isso não pode ser marcado como não procede.</p>}
                  {changes && (
                    <p className="mt-1.5 flex flex-wrap items-center gap-1 text-[13px]">
                      <span className="text-muted">Se não proceder:</span> confiança <b className={CONFIDENCE_TEXT[whatIf!.confidence]}>{CONFIDENCE_LABEL[whatIf!.confidence]}</b>
                      <ArrowRight size={12} className="text-muted" /> <b style={{ color: REC[whatIf!.recommendation].color }}>{REC[whatIf!.recommendation].label}</b>
                    </p>
                  )}
                  {!reading && (
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button onClick={() => go(idxs[0])} className="flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[12px] font-medium text-blueprint hover:bg-blueprint-soft">
                        Ver apontamento{idxs.length > 1 ? "s" : ""} <ChevronRight size={13} />
                      </button>
                      <button onClick={() => toggleUnfounded(r)} aria-pressed={off}
                        className={`flex items-center gap-1 rounded-md border px-2 py-1 text-[12px] font-medium transition-colors ${off ? "border-line bg-paper text-ink hover:bg-sheet" : "border-line text-muted hover:border-bad hover:bg-[#fbefed] hover:text-bad"}`}>
                        {off ? <><Undo2 size={13} /> Desfazer</> : <><ThumbsDown size={13} /> Não procede{idxs.length > 1 ? ` (${idxs.length})` : ""}</>}
                      </button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* efeito na recomendação */}
      <section className="rounded-lg bg-paper/60 px-4 py-3 text-sm">
        <h3 className="mb-1 font-semibold">O que isso muda na recomendação</h3>
        <p className="leading-relaxed">
          {level === "low" && p.recommendation === "detailed_review" && <>Com {plural(reducers.length, "redutor", "redutores")} (a partir de {low}, a confiança fica baixa) o chamado vai para <b style={{ color: REC.detailed_review.color }}>Análise detalhada</b>, qualquer que seja o score{p.score !== null ? <> (aqui, {p.score})</> : null}.</>}
          {level === "low" && p.recommendation !== "detailed_review" && <>A confiança está baixa, mas o chamado ficou em <b style={{ color: REC[p.recommendation].color }}>{REC[p.recommendation].label}</b>: {p.recommendation === "return_locked" ? "a trava de integridade" : p.recommendation === "return_to_supplier" ? "a falta do fornecedor" : "uma regra anterior"} vem antes da confiança na ordem de decisão.</>}
          {level === "medium" && <>Confiança média não muda a recomendação: o chamado segue as outras regras e o motivo ganha o aviso “revisar com atenção”. Com mais {plural(Math.max(1, low - reducers.length), "redutor", "redutores")}, iria para análise detalhada.</>}
          {level === "high" && <>Sem redutores, a confiança não interfere: a recomendação segue as outras regras da régua.</>}
        </p>
        {cur.outdated && (
          <p className="mt-2 flex flex-wrap items-center gap-1 border-t border-line pt-2">
            <span className="text-muted">Pela régua atual:</span>
            confiança <b className={CONFIDENCE_TEXT[cur.p.confidence!]}>{CONFIDENCE_LABEL[cur.p.confidence!]}</b>
            <ArrowRight size={12} className="text-muted" /> <b style={{ color: REC[path.recommendation].color }}>{REC[path.recommendation].label}</b>
          </p>
        )}
        {unfounded.size > 0 && sim && (
          <p className="mt-2 flex flex-wrap items-center gap-1 border-t border-line pt-2">
            <span className="text-muted">Com a sua revisão{cur.outdated ? ", pela régua atual" : ""} ({plural(unfounded.size, "tipo", "tipos")} não procede{unfounded.size === 1 ? "" : "m"}):</span>
            confiança <b className={CONFIDENCE_TEXT[sim.confidence]}>{CONFIDENCE_LABEL[sim.confidence]}</b>
            <ArrowRight size={12} className="text-muted" /> <b style={{ color: REC[sim.recommendation].color }}>{REC[sim.recommendation].label}</b>
            <span className="text-muted">· score {sim.score}</span>
          </p>
        )}
      </section>
    </>
  );
}

// ============================================================================ recomendação
function RecommendationBody({ p, rubric, focusFinding, onSwitch, onClose }: Props) {
  const path = useMemo(() => decisionPath(p, rubric), [p, rubric]);
  const cur = useMemo(() => underCurrentRule(p, rubric), [p, rubric]);
  const go = (i: number) => { onClose(); focusFinding(i); };
  const missing = p.checklist.requirements.filter((r) => !r.met).map((r) => r.description);

  // apontamentos decisivos: tirar só este tipo muda a recomendação
  const decisive = useMemo(() => {
    if (p.score === null) return [];
    return [...new Set(p.findings.map((f) => f.kind))]
      .map((k) => ({ k, i: p.findings.findIndex((f) => f.kind === k), s: simulate(p, rubric, new Set([k])) }))
      .filter((x) => x.s && x.s.recommendation !== p.recommendation)
      .slice(0, 3);
  }, [p, rubric]);

  const todo = nextSteps(p, missing);

  return (
    <>
      <section className="rounded-lg border border-line border-l-4 px-4 py-3 text-sm" style={{ borderLeftColor: REC[p.recommendation].mark, background: tint(p.recommendation, 7) }}>
        <div className="text-[12px] font-medium text-muted">Motivo registrado no parecer</div>
        <p className="mt-0.5 leading-relaxed">{p.recommendation_reason || "—"}</p>
      </section>

      {!path.consistent && (
        <p className="rounded-lg bg-[#fdf6e4] px-3 py-2 text-[13px]">
          Este parecer foi gerado com a régua <b>{p.rubric_version}</b>. Pela régua atual a recomendação seria <b style={{ color: REC[path.recommendation].color }}>{REC[path.recommendation].label}</b>
          {cur.dropped.length > 0 && <> ({cur.dropped.map((r) => findingLabel(r).toLowerCase()).join(", ")} deixa{cur.dropped.length === 1 ? "" : "ram"} de reduzir a confiança)</>}; o caminho abaixo usa a régua atual.
        </p>
      )}

      <section>
        <h3 className="mb-1 text-sm font-semibold">A ordem de decisão da régua</h3>
        <p className="mb-3 text-[13px] text-muted">As regras são conferidas nesta ordem. A primeira que se aplica decide, e as seguintes não mudam o resultado.</p>
        <ol className="relative space-y-0">
          {path.steps.map((s, k) => (
            <Step key={s.id} n={k + 1} s={s} last={k === path.steps.length - 1}>
              <StepDetail s={s} p={cur.p} rubric={rubric} band={path.band} missing={missing} go={go} onConfidence={() => onSwitch("confidence")} />
            </Step>
          ))}
        </ol>
      </section>

      {decisive.length > 0 && (
        <section>
          <h3 className="mb-1.5 text-sm font-semibold">O que mudaria a recomendação</h3>
          <ul className="space-y-1.5 text-sm">
            {decisive.map((d) => (
              <li key={d.k} className="flex flex-wrap items-center gap-1">
                Se <button onClick={() => go(d.i)} className="font-semibold text-blueprint hover:underline">{findingLabel(d.k)}</button> não proceder:
                score {d.s!.score} <ArrowRight size={12} className="text-muted" /> <b style={{ color: REC[d.s!.recommendation].color }}>{REC[d.s!.recommendation].label}</b>
              </li>
            ))}
          </ul>
        </section>
      )}

      {todo.length > 0 && (
        <section className="rounded-lg bg-paper/60 px-4 py-3 text-sm">
          <h3 className="mb-1.5 font-semibold">O que fazer agora</h3>
          <ul className="space-y-1">
            {todo.map((t, k) => (
              <li key={k} className="flex items-start gap-2"><span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-ink/50" /><span>{t}</span></li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

function Step({ n, s, last, children }: { n: number; s: DecisionStep; last: boolean; children: ReactNode }) {
  const fired = s.state === "fired", unreached = s.state === "unreached";
  return (
    <li className={`relative flex gap-3 pb-3 ${unreached ? "opacity-55" : ""}`}>
      {!last && <span className="absolute left-[13px] top-7 bottom-0 w-px bg-line" aria-hidden />}
      <span className={`relative z-10 flex size-7 shrink-0 items-center justify-center rounded-full text-[12px] font-bold ${fired ? "bg-ink text-white" : unreached ? "border border-dashed border-line bg-sheet text-muted" : "bg-[#e3f2ea] text-ok"}`}>
        {fired ? n : unreached ? <CircleDashed size={13} /> : <Check size={14} strokeWidth={3} />}
      </span>
      <div className={`min-w-0 flex-1 rounded-lg px-3 py-1.5 text-sm ${fired ? "bg-blueprint-soft/70 ring-1 ring-blueprint/25" : ""}`}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold">{STEP_TITLE[s.id]}</span>
          {fired && <span className="rounded-full bg-ink px-2 py-0.5 text-[11px] font-semibold text-white">decidiu aqui</span>}
          {s.state === "passed" && <span className="text-[12px] text-muted">não se aplica</span>}
          {unreached && <span className="text-[12px] text-muted">não chega a decidir</span>}
        </div>
        {children}
      </div>
    </li>
  );
}

function StepDetail({ s, p, rubric, band, missing, go, onConfidence }: {
  s: DecisionStep; p: Assessment; rubric: RubricInfo; band: ReturnType<typeof decisionPath>["band"]; missing: string[];
  go: (i: number) => void; onConfidence: () => void;
}) {
  const fired = s.state === "fired";
  // um chip por tipo de apontamento, que leva ao primeiro deles
  const chips = [...new Map(s.findings.map((i) => [p.findings[i].kind, i])).entries()].slice(0, 5);
  const chipList = chips.length > 0 && (fired || s.state === "passed") && (
    <span className="mt-1 flex flex-wrap gap-1.5">
      {chips.map(([k, i]) => (
        <button key={k} onClick={() => go(i)} className="flex items-center gap-1 rounded-full border border-line bg-sheet px-2 py-0.5 text-[12px] hover:border-blueprint hover:text-blueprint">
          {p.findings[i].lock && <Lock size={11} />}{findingLabel(k)} <ChevronRight size={11} />
        </button>
      ))}
    </span>
  );
  const cap = rubric.max_amount_at_issue_for_caveats_pct ?? 30;
  const approveCap = rubric.max_amount_at_issue_for_approve_pct ?? 10;
  const pctText = `${p.amount_at_issue_pct.toFixed(0)}%`;
  let text: ReactNode;
  switch (s.id) {
    case "checklist":
      text = fired ? <>Falta{missing.length === 1 ? "" : "m"}: {missing.join("; ") || "documento obrigatório"}. Sem eles, o chamado volta sem score.</> : "Documentos obrigatórios completos.";
      break;
    case "lock":
      text = fired ? "Indício grave (ex.: foto reaproveitada de outro chamado): devolve qualquer que seja o score." : "Nenhuma trava de integridade.";
      break;
    case "gap":
      text = fired ? "O que o fornecedor precisa ajustar está claro (serviço sem orçamento, item fora do escopo ou em dobro): volta ao fornecedor." : "Nenhuma falta do fornecedor.";
      break;
    case "confidence":
      text = (
        <>
          {!p.confidence ? "Sem confiança calculada."
            : fired ? <>Confiança <b className="text-bad">baixa</b> ({plural(p.confidence_reducers.length, "redutor", "redutores")}: {p.confidence_reducers.map((r) => findingLabel(r).toLowerCase()).join(", ")}): a entrada não basta para concluir.</>
            : <>Confiança <b className={CONFIDENCE_TEXT[p.confidence]}>{CONFIDENCE_LABEL[p.confidence]}</b>{p.confidence_reducers.length ? ` (${plural(p.confidence_reducers.length, "redutor", "redutores")})` : ""}{p.confidence === "medium" ? ": não manda para análise detalhada, mas pede revisão com atenção." : "."}</>}
          {p.confidence && (
            <button onClick={onConfidence} className="ml-1.5 inline-flex items-center gap-0.5 text-[13px] font-medium text-blueprint hover:underline">
              {fired ? "Ver o que reduziu a confiança" : "Detalhes"} <ChevronRight size={13} />
            </button>
          )}
        </>
      );
      break;
    case "amount":
      text = fired ? <>{pctText} do orçamento está em questão (a partir de {cap}% volta ao fornecedor).</>
        : p.amount_at_issue > 0 ? <>{pctText} do orçamento em questão, abaixo de {cap}%.</> : "Nenhum valor em questão.";
      break;
    case "band": {
      if (p.score === null || !band) { text = "Sem score."; break; }
      const range = `${band.score_min}–${Math.min(100, band.end - 1)}`;
      text = fired
        ? <>Score <b>{p.score}</b>: faixa <b style={{ color: REC[band.recommendation].color }}>{REC[band.recommendation].label}</b> ({range}).{band.capped && <> Como {pctText} do orçamento está em questão (acima de {approveCap}%), aprovar vira <b style={{ color: REC.approve_with_caveats.color }}>aprovar com ressalvas</b>.</>}</>
        : <>Pelo score ({p.score}), seria <b>{REC[band.capped ? "approve_with_caveats" : band.recommendation].label}</b> ({range}), mas uma regra anterior já decidiu.</>;
      break;
    }
  }
  return (
    <div className="mt-0.5 text-[13px] leading-relaxed text-ink/85">
      {s.state === "unreached" && s.id !== "band" ? <span className="text-muted">Não chega a ser conferida: a decisão já foi tomada acima.</span> : text}
      {chipList}
    </div>
  );
}

/** Próximos passos para a pessoa analista, conforme a recomendação. */
function nextSteps(p: Assessment, missing: string[]): ReactNode[] {
  switch (p.recommendation) {
    case "detailed_review": {
      const todos = [...new Set(p.confidence_reducers.map((r) => REDUCER_HELP[r]?.todo).filter(Boolean))] as string[];
      return [
        ...todos,
        "Se precisar, faça vistoria no local ou consulte o gestor da agência.",
        <>Se, depois de conferir, algum redutor não proceder, marque <b>Não procede</b> no apontamento: a régua recalcula na seção da decisão. Ou escolha a decisão final diretamente.</>,
      ];
    }
    case "checklist_returned":
      return [<>Peça ao fornecedor: {missing.join("; ") || "os documentos obrigatórios"}.</>];
    case "return_locked":
      return ["Compare as evidências do apontamento de trava (ex.: a foto e o chamado de origem).", "Se o indício se confirmar, encaminhe para auditoria."];
    case "return_to_supplier":
      return ["Revise a mensagem sugerida e devolva ao fornecedor.", "Se algum apontamento estiver errado, marque Não procede antes de decidir."];
    case "approve_with_caveats":
      return ["Aprove e use a mensagem sugerida para orientar o fornecedor."];
    case "approve":
      return ["Confira os pontos de atenção na seção da decisão e confirme o parecer."];
  }
}
