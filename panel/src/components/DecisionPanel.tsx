import { ArrowRight, Check, CheckCircle2, ChevronRight, History, Lightbulb, Loader2, MessageSquareWarning, PencilLine, ShieldAlert, Sparkles, ThumbsUp, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, type Assessment, type Feedback, type FeedbackAction, type Recommendation, type RubricInfo } from "../api";
import { REC, findingLabel, authorLabel, CONFIDENCE_LABEL, brl, pts } from "../format";
import { REASONS_BY_DECISION, REASONS_BY_KIND, simulate } from "../evidence";
import { BandScale } from "./ScoreBreakdown";
import { StepTitle } from "./ui/StepTitle";
import { Tooltip } from "./ui/Tooltip";

const DECISIONS: Recommendation[] = ["approve", "approve_with_caveats", "return_to_supplier", "return_locked", "detailed_review"];
const ACTION = {
  accept: { label: "Aceito", verb: "Confirmar parecer", icon: ThumbsUp, cls: "bg-ok hover:bg-[#1c6341]", hint: "Concorda com a recomendação e com todos os apontamentos." },
  adjust: { label: "Ajuste", verb: "Registrar ajuste", icon: PencilLine, cls: "bg-blueprint hover:bg-[#1d44a0]", hint: "Concorda em parte: corrigiu apontamentos e segue a régua." },
  disagree: { label: "Discordância", verb: "Registrar discordância", icon: MessageSquareWarning, cls: "bg-bad hover:bg-[#962217]", hint: "Decide diferente do que a régua indica. Explique o porquê." },
} as const;
const AUTHOR_KEY = "atest.author";

interface Props {
  p: Assessment;
  n?: number;
  rubric: RubricInfo;
  unfounded: Set<string>;
  toggleUnfounded: (kind: string) => void;
  /** abre e rola até o apontamento de índice i */
  focusFinding: (i: number) => void;
  onRegistered?: (registered: boolean) => void;
}

/**
 * Decisão da pessoa analista, no fim do parecer. Recebe as marcações de "não procede" feitas nos apontamentos,
 * reaplica a régua na hora, sugere a decisão, destaca os apontamentos decisivos e infere o tipo de registro.
 */
export function DecisionPanel({ p, n, rubric, unfounded, toggleUnfounded, focusFinding, onRegistered }: Props) {
  const [history, setHistory] = useState<Feedback[]>([]);
  const [editing, setEditing] = useState(true);
  const [manual, setManual] = useState<Recommendation | null>(null);
  const [comment, setComment] = useState("");
  const [author, setAuthor] = useState(() => { try { return localStorage.getItem(AUTHOR_KEY) ?? ""; } catch { return ""; } });
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justSaved, setJustSaved] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setManual(null);
    setComment("");
    setJustSaved(false);
    setLoaded(false);
    if (!p.record_id) return;
    api.feedbacks(p.record_id).then((h) => { setHistory(h); setEditing(h.length === 0); }).catch(() => setHistory([])).finally(() => setLoaded(true));
  }, [p.record_id]);
  useEffect(() => { if (loaded) onRegistered?.(history.length > 0); }, [loaded, history.length, onRegistered]);

  // a régua reaplicada sem os apontamentos marcados como "não procede"
  const sim = useMemo(() => simulate(p, rubric, unfounded), [p, rubric, unfounded]);
  const suggested: Recommendation = unfounded.size && sim ? sim.recommendation : p.recommendation;
  const final = manual ?? suggested;
  const action: FeedbackAction = !unfounded.size && final === p.recommendation ? "accept" : final === p.recommendation || final === suggested ? "adjust" : "disagree";
  const needsComment = action === "disagree" && comment.trim().length < 5;

  // inteligência: o que merece atenção antes de decidir
  const attention = useMemo(() => buildAttention(p, rubric), [p, rubric]);

  if (!p.record_id) return null;

  const send = async () => {
    setSending(true);
    setError(null);
    try {
      const name = author.trim();
      try { localStorage.setItem(AUTHOR_KEY, name); } catch { /* armazenamento indisponível */ }
      const fb = await api.sendFeedback(p.record_id!, {
        action,
        final_decision: final,
        unfounded_findings: [...unfounded],
        comment: comment.trim(),
        ...(name ? { author: name } : {}),
      });
      setHistory((h) => [...h, fb]);
      setEditing(false);
      setJustSaved(true);
      setManual(null);
      setComment("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSending(false);
    }
  };

  const addReason = (r: string) => setComment((c) => (c.includes(r) ? c : c.trim() ? `${c.trim().replace(/[.;]?$/, ";")} ${r}` : r));
  const reasons = [...new Set([...[...unfounded].map((k) => REASONS_BY_KIND[k]).filter(Boolean), ...(REASONS_BY_DECISION[final] ?? [])])];
  const decisions = DECISIONS.includes(p.recommendation) ? DECISIONS : [p.recommendation, ...DECISIONS];
  const last = history.at(-1);
  const A = ACTION[action];

  return (
    <section data-tour="decision" className="scroll-mt-4 rounded-xl border-2 border-blueprint/30 bg-sheet p-5">
      <StepTitle n={n}
        sub="O parecer é uma recomendação: a decisão final é sua. Ela fica registrada e calibra a régua e os prompts."
        aside={last
          ? <span className="flex items-center gap-1.5 rounded-full bg-[#e3f2ea] px-3 py-1 text-sm font-semibold text-ok"><CheckCircle2 size={15} /> Registrada</span>
          : <span className="flex items-center gap-1.5 rounded-full bg-[#fdf1dc] px-3 py-1 text-sm font-semibold text-warn"><span className="size-2 rounded-full bg-warn pulso" /> Pendente</span>}>
        Decisão da pessoa analista
      </StepTitle>

      {/* decisão já registrada */}
      {last && !editing && (
        <div className={`mt-4 rounded-lg border border-ok/30 bg-[#eef7f1] p-4 ${justSaved ? "surgir" : ""}`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-start gap-3">
              <CheckCircle2 size={22} className="mt-0.5 shrink-0 text-ok" />
              <div className="text-sm">
                <div className="font-semibold">
                  {justSaved ? "Decisão registrada. " : ""}{ACTION[last.action].label}: <span style={{ color: REC[last.final_decision ?? last.atest_recommendation].color }}>{REC[last.final_decision ?? last.atest_recommendation].label}</span>
                </div>
                <div className="text-muted">por {authorLabel(last.author)} em {new Date(last.created_at).toLocaleString("pt-BR")}</div>
                {last.unfounded_findings.length > 0 && <div className="mt-1">Não procedem: {last.unfounded_findings.map((t) => findingLabel(t)).join(", ")}</div>}
                {last.comment && <div className="mt-1 italic text-ink/80">“{last.comment}”</div>}
              </div>
            </div>
            <button onClick={() => { setEditing(true); setJustSaved(false); }} className="rounded-lg border border-line bg-sheet px-3 py-1.5 text-sm font-medium hover:bg-paper">Rever decisão</button>
          </div>
        </div>
      )}

      {editing && (
        <div className="mt-4 space-y-5">
          {/* pontos de atenção gerados a partir do parecer */}
          {attention.length > 0 && (
            <div className="rounded-lg bg-[#fdf6e4] p-3.5">
              <div className="mb-1.5 flex items-center gap-1.5 text-sm font-semibold"><Lightbulb size={16} className="text-warn" /> Antes de decidir, confira</div>
              <ul className="space-y-1 text-sm">
                {attention.map((a, k) => (
                  <li key={k} className="flex items-start gap-2">
                    <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-warn" />
                    <span className="flex-1">{a.text}</span>
                    {a.finding !== undefined && (
                      <button onClick={() => focusFinding(a.finding!)} className="flex shrink-0 items-center gap-0.5 text-[13px] font-medium text-blueprint hover:underline">ver <ChevronRight size={14} /></button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* revisão dos apontamentos e o efeito na régua */}
          <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
            <div>
              <h4 className="mb-1.5 text-sm font-semibold">Sua revisão dos apontamentos</h4>
              {unfounded.size ? (
                <div className="flex flex-wrap gap-1.5">
                  {[...unfounded].map((k) => (
                    <span key={k} className="flex items-center gap-1 rounded-full border border-bad/40 bg-[#fbefed] py-0.5 pl-2.5 pr-1 text-[13px] text-bad">
                      <span className="line-through decoration-bad/50">{findingLabel(k)}</span>
                      <button onClick={() => toggleUnfounded(k)} aria-label={`Desfazer: ${findingLabel(k)}`} className="rounded-full p-0.5 hover:bg-bad/10"><X size={13} /></button>
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted">
                  {p.findings.length
                    ? <>Discorda de algum apontamento? Clique em <b className="text-ink">Não procede</b> no próprio apontamento, na seção acima. A régua é recalculada aqui na hora.</>
                    : "Este parecer não tem apontamentos."}
                </p>
              )}
            </div>
            {sim && (
              <div className="rounded-lg border border-line p-3">
                <div className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
                  <Sparkles size={15} className="text-blueprint" /> {unfounded.size ? "A régua com a sua revisão" : "A régua hoje"}
                </div>
                <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
                  <span className="text-muted">Score</span>
                  {unfounded.size > 0 && sim.score !== p.score && <><span className="tabular-nums text-muted line-through">{p.score}</span><ArrowRight size={13} className="self-center text-muted" /></>}
                  <b className="largo text-xl tabular-nums" style={{ color: REC[sim.recommendation].color }}>{sim.score}</b>
                  <span className="text-muted">·</span>
                  {unfounded.size > 0 && sim.recommendation !== p.recommendation && <span className="text-muted line-through">{REC[p.recommendation].short}</span>}
                  <b style={{ color: REC[sim.recommendation].color }}>{REC[sim.recommendation].label}</b>
                </div>
                <div className="mt-2"><BandScale score={sim.score} rubric={rubric} compact /></div>
                <div className="mt-1.5 text-[12px] text-muted">
                  Confiança {CONFIDENCE_LABEL[sim.confidence]}{unfounded.size ? ` · ${sim.kept} de ${p.findings.length} apontamentos mantidos` : ""}
                </div>
              </div>
            )}
          </div>

          {/* decisão final */}
          <fieldset>
            <legend className="mb-2 text-sm font-semibold">Decisão final</legend>
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
              {decisions.map((d) => {
                const on = final === d;
                return (
                  <label key={d} className={`relative flex cursor-pointer flex-col gap-1 rounded-lg border-2 p-3 text-sm transition-colors ${on ? "bg-sheet shadow-sm" : "border-line hover:border-ink/25"}`}
                    style={on ? { borderColor: REC[d].mark } : undefined}>
                    <input type="radio" name={`decisao-${p.record_id}`} className="sr-only" checked={on} onChange={() => setManual(d === suggested ? null : d)} />
                    <span className="flex items-center gap-2 font-medium">
                      <span className={`flex size-4 shrink-0 items-center justify-center rounded-full border-2 ${on ? "" : "border-line"}`} style={on ? { borderColor: REC[d].mark, background: REC[d].mark } : undefined}>
                        {on && <Check size={10} strokeWidth={4} className="text-white" />}
                      </span>
                      {REC[d].label}
                    </span>
                    <span className="flex flex-wrap gap-1">
                      {d === p.recommendation && <span className="rounded bg-paper px-1.5 text-[11px] font-semibold text-muted">Atest.AI</span>}
                      {d === suggested && unfounded.size > 0 && d !== p.recommendation && <span className="rounded bg-blueprint-soft px-1.5 text-[11px] font-semibold text-blueprint">Régua revisada</span>}
                    </span>
                  </label>
                );
              })}
            </div>
            {manual && manual !== suggested && (
              <p className="mt-2 flex flex-wrap items-center gap-2 text-[13px] text-muted">
                <ShieldAlert size={14} className="text-warn" /> Você escolheu uma decisão diferente da indicada pela régua ({REC[suggested].label}).
                <button onClick={() => setManual(null)} className="font-medium text-blueprint hover:underline">Voltar para a sugestão</button>
              </p>
            )}
          </fieldset>

          {/* motivo */}
          <div>
            <label htmlFor={`coment-${p.record_id}`} className="mb-1.5 block text-sm font-semibold">
              Motivo {action === "disagree" ? <span className="text-bad">* obrigatório para discordância</span> : <span className="font-normal text-muted">(opcional, mas ajuda a calibrar)</span>}
            </label>
            {reasons.length > 0 && (
              <div className="mb-2 flex flex-wrap gap-1.5">
                {reasons.map((r) => (
                  <button key={r} type="button" onClick={() => addReason(r)} disabled={comment.includes(r)}
                    className="rounded-full border border-line bg-paper/60 px-2.5 py-0.5 text-[13px] text-ink/80 hover:border-blueprint hover:text-blueprint disabled:opacity-40">
                    + {r}
                  </button>
                ))}
              </div>
            )}
            <textarea id={`coment-${p.record_id}`} value={comment} onChange={(e) => setComment(e.target.value)} rows={2} maxLength={2000}
              placeholder="Ex.: foto do antes não é exigida em pintura de backoffice"
              className={`w-full rounded-md border px-3 py-2 text-sm ${needsComment && comment ? "border-bad" : "border-line"}`} />
          </div>

          {/* rodapé: o que será gravado */}
          <div className="flex flex-wrap items-end justify-between gap-3 border-t border-line pt-4">
            <div className="space-y-2 text-sm">
              <label className="flex items-center gap-2">
                <span className="text-muted">Seu nome</span>
                <input value={author} onChange={(e) => setAuthor(e.target.value)} maxLength={80} placeholder="Analista" className="w-44 rounded-md border border-line px-2 py-1" />
              </label>
              <p className="text-muted">
                Será registrado como <Tooltip content={A.hint}><b className="cursor-help text-ink underline decoration-dotted underline-offset-2">{A.label}</b></Tooltip>
                {" "}· decisão final <b style={{ color: REC[final].color }}>{REC[final].label}</b>
                {unfounded.size > 0 && <> · {unfounded.size} apontamento{unfounded.size === 1 ? "" : "s"} não procede{unfounded.size === 1 ? "" : "m"}</>}
              </p>
            </div>
            <div className="flex items-center gap-3">
              {last && <button onClick={() => setEditing(false)} className="text-sm text-muted hover:text-ink">Cancelar</button>}
              {error && <span className="text-sm text-bad">{error}</span>}
              <Tooltip content={needsComment ? "Escreva o motivo da discordância para registrar" : A.hint}>
                <button onClick={send} disabled={sending || needsComment}
                  className={`flex items-center gap-2 rounded-lg px-4 py-2 font-semibold text-white shadow-sm transition-colors disabled:pointer-events-none disabled:opacity-50 ${A.cls}`}>
                  {sending ? <Loader2 size={16} className="animate-spin" /> : <A.icon size={16} />} {A.verb}
                </button>
              </Tooltip>
            </div>
          </div>
        </div>
      )}

      {history.length > 0 && (
        <details className="group mt-4 text-sm">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-muted hover:text-ink">
            <ChevronRight size={14} className="transition group-open:rotate-90" /><History size={14} /> Histórico de decisões ({history.length})
          </summary>
          <ol className="mt-2 space-y-2 border-l-2 border-line pl-4">
            {[...history].reverse().map((h) => (
              <li key={h.id}>
                <div><b>{ACTION[h.action].label}</b> · {REC[h.final_decision ?? h.atest_recommendation].label} <span className="text-muted">· {authorLabel(h.author)}, {new Date(h.created_at).toLocaleString("pt-BR")}</span></div>
                {h.unfounded_findings.length > 0 && <div className="text-muted">Não procedem: {h.unfounded_findings.map((t) => findingLabel(t)).join(", ")}</div>}
                {h.comment && <div className="italic text-muted">“{h.comment}”</div>}
              </li>
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}

/** Pontos de atenção: travas, confiança, valor potencial divergente, proximidade de faixa e apontamentos decisivos. */
function buildAttention(p: Assessment, rubric: RubricInfo): { text: React.ReactNode; finding?: number }[] {
  const out: { text: React.ReactNode; finding?: number }[] = [];
  const idx = (pred: (f: Assessment["findings"][number]) => boolean) => { const i = p.findings.findIndex(pred); return i >= 0 ? i : undefined; };

  const lock = idx((f) => f.lock);
  if (lock !== undefined) out.push({ text: <><b>Trava de integridade</b> ({p.findings[lock].description.toLowerCase()}): compare as fotos antes de confirmar.</>, finding: lock });

  if (p.confidence && p.confidence !== "high") {
    out.push({ text: <>Confiança <b>{CONFIDENCE_LABEL[p.confidence]}</b>: {p.confidence_reducers.map((r) => findingLabel(r)).join(", ").toLowerCase()}.</>, finding: idx((f) => f.reduces_confidence) });
  }

  // apontamentos decisivos: tirar só este tipo muda a recomendação
  const kinds = [...new Set(p.findings.map((f) => f.kind))];
  const decisive = kinds
    .map((k) => ({ k, s: simulate(p, rubric, new Set([k])) }))
    .filter((x) => x.s && x.s.recommendation !== p.recommendation)
    .slice(0, 3);
  for (const d of decisive) {
    out.push({
      text: <>Apontamento decisivo: se <b>{findingLabel(d.k)}</b> não proceder, a régua vai a <b>{d.s!.score}</b> e a recomendação muda para <b style={{ color: REC[d.s!.recommendation].color }}>{REC[d.s!.recommendation].label}</b>.</>,
      finding: idx((f) => f.kind === d.k),
    });
  }

  // score perto da borda de uma faixa
  if (p.score !== null && !decisive.length && lock === undefined) {
    const edge = rubric.bands.map((b) => b.score_min).filter((m) => m > 0).find((m) => Math.abs(p.score! - m) <= 5 && p.score !== m);
    if (edge !== undefined) out.push({ text: <>O score <b>{p.score}</b> está a {pts(Math.abs(p.score - edge))} ponto{Math.abs(p.score - edge) === 1 ? "" : "s"} da faixa seguinte ({edge}). Vale revisar os apontamentos com atenção.</> });
  }

  if (p.amount_at_issue > 0) {
    const biggest = p.findings.reduce((best, f, i) => (f.amount_at_issue > (best < 0 ? 0 : p.findings[best].amount_at_issue) ? i : best), -1);
    out.push({ text: <><b>{brl(p.amount_at_issue)}</b> de valor potencial divergente ({p.amount_at_issue_pct.toFixed(0)}% do orçado){biggest >= 0 ? <>, a maior parte em “{p.findings[biggest].description.toLowerCase()}”</> : null}.</>, finding: biggest >= 0 ? biggest : undefined });
  }
  return out;
}
