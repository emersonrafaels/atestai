import { ArrowRight, Box, Camera, CheckCircle2, ClipboardCheck, FileSearch, ListChecks, MapPin, Ruler, Wrench, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import type { Assessment, RubricInfo, TicketDetail } from "../api";
import { MAINTENANCE_LABEL, SEVERITY, STAGE_LABEL, envLabel, explainFindings, num, pts } from "../format";
import { InfoBox } from "./ui/InfoBox";
import { InfoTip, Tooltip } from "./ui/Tooltip";

interface ScopeReading {
  local: string;
  environment: string;
  equipment: string;
  requested_services: string[];
  mentioned_quantities: { description: string; quantity: number; unit: string }[];
  acceptance_criteria: string[];
  expected_evidence: string[];
  before_evidence_applicable: boolean;
  consistent_with_category_symptom: boolean;
  coherence_note: string;
  vague_scope: boolean;
  vague_reason: string;
}

type Tab = "assessment" | "quote" | "photos" | "calls";

// no modo simulado o modelo não roda: os campos de texto vêm como "(simulado…)"
const placeholder = (s: string) => /^\(simulad/i.test(s.trim());
const real = (s: string | undefined | null) => (s && !placeholder(s) ? s : "");
const realList = (l: string[] | undefined) => (l ?? []).filter((x) => x && !placeholder(x));

/** Aba Escopo: o texto como foi escrito, o que a IA extraiu dele, as verificações e como a leitura alimenta as outras etapas. */
export function ScopeTab({ p, ticket, rubric, goTo }: { p: Assessment; ticket: TicketDetail | null; rubric: RubricInfo; goTo: (t: Tab) => void }) {
  const s = p.scope as ScopeReading | null;
  if (!s) {
    return (
      <InfoBox tone="tip" title="O escopo não foi analisado">
        O chamado voltou no checklist mínimo, antes da leitura do escopo. Depois que o fornecedor completar os documentos, a análise passa por esta etapa.
      </InfoBox>
    );
  }
  const simulated = p.mode === "simulated" || placeholder(s.local);
  const impacts = explainFindings(p.findings, rubric);
  const scopeFindings = p.findings.map((f, i) => ({ f, imp: impacts[i] })).filter((x) => x.f.validation === "scope");
  const grade = p.grades?.scope ?? null;
  const weight = rubric.weights.scope;
  const services = realList(s.requested_services);
  const criteria = realList(s.acceptance_criteria);
  const evidence = realList(s.expected_evidence);
  const quantities = s.mentioned_quantities ?? [];

  return (
    <div className="space-y-5">
      {/* resumo: nota e verificações */}
      <section className="flex flex-wrap items-center gap-x-8 gap-y-3 rounded-xl border border-line bg-sheet p-5">
        <div>
          <div className="flex items-center gap-1 text-[13px] text-muted">Nota de Escopo <InfoTip term="grade" size={12} /></div>
          <div className="flex items-baseline gap-1">
            <span className="largo text-[34px] font-bold leading-none tabular-nums" style={{ color: grade === null ? undefined : grade >= 85 ? "var(--color-ok)" : grade >= 70 ? "var(--color-warn)" : "var(--color-bad)" }}>{grade ?? "—"}</span>
            <span className="text-muted">/100</span>
          </div>
          <div className="text-[12px] text-muted">vale {weight}% do score</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Check ok={!s.vague_scope} yes="Escopo claro" no="Escopo vago" tip="O texto permite saber o que fazer, onde e em quê?" />
          <Check ok={s.consistent_with_category_symptom} yes="Coerente com categoria e sintoma" no="Incoerente com categoria e sintoma" tip="O texto combina com a categoria e o sintoma informados no chamado?" />
          <Tooltip content={s.before_evidence_applicable ? "O serviço muda o estado físico do local (reparo, troca, pintura, limpeza): a foto do antes é esperada." : "Serviço de teste ou inspeção: a foto do antes não se aplica."}>
            <span className={`flex cursor-help items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium ${s.before_evidence_applicable ? "bg-blueprint-soft text-blueprint" : "bg-paper text-muted"}`}>
              <Camera size={15} /> Foto do antes {s.before_evidence_applicable ? "exigida" : "não se aplica"}
            </span>
          </Tooltip>
        </div>
      </section>

      {simulated && (
        <InfoBox tone="tip" title="Análise no modo simulado">
          Os detalhes que a IA extrai do texto (local, serviços, quantidades, critérios de aceite e evidências esperadas) só aparecem nas análises feitas no modo <b>API</b>.
          As verificações de clareza, coerência e foto do antes, acima, valem nos dois modos.
        </InfoBox>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        {/* como foi escrito */}
        <section className="rounded-xl border border-line bg-sheet p-5">
          <h3 className="mb-2 flex items-center gap-2 font-semibold"><FileSearch size={17} className="text-blueprint" /> Como foi escrito</h3>
          <blockquote className="rounded-lg border-l-4 border-blueprint/40 bg-paper/60 px-4 py-3 text-[17px] leading-snug">
            “{highlight(ticket?.scope ?? "", quantities)}”
          </blockquote>
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <Fact label="Categoria">{ticket?.category_label ?? p.category}</Fact>
            <Fact label="Sintoma">{ticket?.symptom_label ?? p.symptom}</Fact>
            <Fact label="Tipo de manutenção">{MAINTENANCE_LABEL[p.maintenance_type] ?? p.maintenance_type}</Fact>
            <Fact label="Etapa da esteira">{STAGE_LABEL[p.moment] ?? p.moment}</Fact>
            {ticket && <Fact label="Agência">{ticket.branch}{ticket.environment ? `, ${envLabel(ticket.environment)}` : ""}</Fact>}
          </dl>
        </section>

        {/* o que a IA extraiu */}
        <section className="rounded-xl border border-line bg-sheet p-5">
          <h3 className="mb-3 flex items-center gap-2 font-semibold"><ClipboardCheck size={17} className="text-blueprint" /> O que a IA extraiu</h3>
          <dl className="space-y-3 text-sm">
            <div className="grid grid-cols-3 gap-3">
              <Extracted icon={<MapPin size={14} />} label="Local" value={real(s.local)} />
              <Extracted icon={<Box size={14} />} label="Ambiente" value={real(s.environment)} />
              <Extracted icon={<Wrench size={14} />} label="Equipamento" value={real(s.equipment)} empty="nenhum citado" />
            </div>
            <div>
              <dt className="mb-1 text-[12px] font-medium text-muted">Serviços pedidos</dt>
              <dd className="flex flex-wrap gap-1.5">
                {services.length ? services.map((x, k) => <span key={k} className="rounded-full bg-blueprint-soft px-2.5 py-0.5 text-[13px] text-blueprint">{x}</span>) : <Empty />}
              </dd>
            </div>
            <div>
              <dt className="mb-1 flex items-center gap-1 text-[12px] font-medium text-muted"><Ruler size={13} /> Quantidades citadas no texto</dt>
              <dd>
                {quantities.length ? (
                  <table className="w-full text-[13px]">
                    <tbody>
                      {quantities.map((q, k) => (
                        <tr key={k} className="border-t border-line/60 first:border-0">
                          <td className="py-1 pr-3 font-semibold tabular-nums">{num(q.quantity)} {q.unit}</td>
                          <td className="py-1 text-muted">{q.description}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <span className="text-[13px] text-muted">{simulated ? "—" : "Nenhuma quantidade explícita: o orçamento é conferido pela plausibilidade."}</span>}
              </dd>
            </div>
          </dl>
        </section>
      </div>

      {/* verificações */}
      <section className="rounded-xl border border-line bg-sheet">
        <h3 className="border-b border-line px-5 py-3 font-semibold">Verificações do escopo</h3>
        <ul className="divide-y divide-line/70">
          <Verification ok={!s.vague_scope} title="Clareza" question="O texto permite saber o que fazer, onde e em quê?"
            okText="Sim: dá para conferir o orçamento e as fotos contra o pedido." badText={real(s.vague_reason) || "O texto não deixa claro o que fazer, onde ou em quê."}
            finding={scopeFindings.find((x) => x.f.kind === "vague_scope")} weight={weight} onSee={() => goTo("assessment")} />
          <Verification ok={s.consistent_with_category_symptom} title="Coerência" question="O texto combina com a categoria e o sintoma informados?"
            okText="Sim: o pedido combina com a categoria e o sintoma do chamado." badText={real(s.coherence_note) || "O pedido não combina com a categoria ou o sintoma."}
            finding={scopeFindings.find((x) => x.f.kind === "inconsistent_scope")} weight={weight} onSee={() => goTo("assessment")} />
        </ul>
      </section>

      {/* como a leitura alimenta as outras etapas */}
      <section>
        <h3 className="mb-2 flex items-center gap-1.5 font-semibold">Como esta leitura é usada <InfoTip text="A leitura do escopo é enviada às etapas seguintes: é a régua contra a qual orçamento e fotos são conferidos." /></h3>
        <div className="grid gap-4 md:grid-cols-3">
          <UseCard icon={<ListChecks size={17} />} title="Critérios de aceite" sub="Conferem cada item do orçamento" items={criteria} empty={simulated ? "Gerados no modo API." : "Nenhum critério extraído."}
            action={<Link onClick={() => goTo("quote")}>Ver orçamento × escopo</Link>} />
          <UseCard icon={<Camera size={17} />} title="Evidências esperadas" sub="O que as fotos precisam mostrar" items={evidence} empty={simulated ? "Geradas no modo API." : "Nenhuma evidência listada."}
            action={<Link onClick={() => goTo("photos")}>Ver fotos</Link>} />
          <div className="rounded-xl border border-line bg-sheet p-4">
            <div className="mb-1 flex items-center gap-2 font-semibold"><Camera size={17} className="text-blueprint" /> Foto do antes</div>
            <p className="text-[13px] text-muted">Define se a falta da foto do antes vira apontamento.</p>
            <p className="mt-3 text-sm">
              {s.before_evidence_applicable
                ? <>Aplicável: se nenhuma foto mostrar o estado anterior, entra o apontamento <b>“Sem foto do antes”</b> (Fase 2).</>
                : <>Não aplicável: é um serviço de teste ou inspeção, então a foto do antes <b>não é cobrada</b>.</>}
            </p>
            <div className="mt-3"><Link onClick={() => goTo("photos")}>Ver fotos</Link></div>
          </div>
        </div>
      </section>

      <p className="text-[13px] text-muted">
        A resposta completa do modelo para esta etapa está em <button onClick={() => goTo("calls")} className="font-medium text-blueprint hover:underline">Chamadas ao modelo</button> (tarefa “Leitura do escopo”).
      </p>
    </div>
  );
}

/** Destaca no texto as quantidades que a IA extraiu (ex.: "240 m²"). */
function highlight(text: string, quantities: ScopeReading["mentioned_quantities"]): ReactNode {
  const nums = [...new Set(quantities.map((q) => String(q.quantity).replace(".", ",")).concat(quantities.map((q) => String(q.quantity))))].filter(Boolean);
  if (!nums.length || !text) return text;
  const re = new RegExp(`(\\b(?:${nums.map((n) => n.replace(/[.,]/g, "[.,]")).join("|")})\\b\\s*(?:m²|m2|m|un\\.?|unidades?|pontos?|peças?|%)?)`, "gi");
  return text.split(re).map((part, i) => (i % 2 ? <mark key={i} className="rounded bg-[#fdf1dc] px-0.5 font-semibold text-ink">{part}</mark> : part));
}

function Check({ ok, yes, no, tip }: { ok: boolean; yes: string; no: string; tip: string }) {
  return (
    <Tooltip content={tip}>
      <span className={`flex cursor-help items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium ${ok ? "bg-[#e3f2ea] text-ok" : "bg-[#f8e4e2] text-bad"}`}>
        {ok ? <CheckCircle2 size={15} /> : <XCircle size={15} />}{ok ? yes : no}
      </span>
    </Tooltip>
  );
}

function Verification({ ok, title, question, okText, badText, finding, weight, onSee }: {
  ok: boolean; title: string; question: string; okText: string; badText: string;
  finding?: { f: Assessment["findings"][number]; imp: ReturnType<typeof explainFindings>[number] }; weight: number; onSee: () => void;
}) {
  return (
    <li className="grid gap-3 px-5 py-4 sm:grid-cols-[auto_1fr_auto] sm:items-center">
      {ok ? <CheckCircle2 className="text-ok" /> : <XCircle className="text-bad" />}
      <div className="min-w-0 text-sm">
        <div className="font-semibold">{title} <span className="font-normal text-muted">· {question}</span></div>
        <div className={ok ? "text-ink/80" : "text-bad"}>{ok ? okText : badText}</div>
      </div>
      {finding && (
        <div className="flex items-center gap-3 sm:justify-end">
          <span className="rounded px-1.5 py-0.5 text-[11px] font-semibold uppercase text-white" style={{ background: SEVERITY[finding.f.severity].color }}>{SEVERITY[finding.f.severity].label}</span>
          <Tooltip content={`Tira ${finding.imp.gradePts} da nota de Escopo; com peso ${weight}%, são ${pts(finding.imp.scorePts)} pontos a menos no score.${finding.f.reduces_confidence ? " Também reduz a confiança da análise." : ""}`}>
            <span className="cursor-help text-right text-sm"><b className="text-bad">−{pts(finding.imp.scorePts)}</b> <span className="text-muted">no score</span></span>
          </Tooltip>
          <Link onClick={onSee}>Ver no Parecer</Link>
        </div>
      )}
    </li>
  );
}

function UseCard({ icon, title, sub, items, empty, action }: { icon: ReactNode; title: string; sub: string; items: string[]; empty: string; action: ReactNode }) {
  return (
    <div className="flex flex-col rounded-xl border border-line bg-sheet p-4">
      <div className="mb-1 flex items-center gap-2 font-semibold"><span className="text-blueprint">{icon}</span>{title}</div>
      <p className="text-[13px] text-muted">{sub}</p>
      {items.length
        ? <ul className="mt-3 flex-1 space-y-1.5 text-sm">{items.map((x, k) => <li key={k} className="flex gap-2"><CheckCircle2 size={15} className="mt-0.5 shrink-0 text-blueprint/60" />{x}</li>)}</ul>
        : <p className="mt-3 flex-1 text-sm text-muted">{empty}</p>}
      <div className="mt-3">{action}</div>
    </div>
  );
}

function Extracted({ icon, label, value, empty = "—" }: { icon: ReactNode; label: string; value: string; empty?: string }) {
  return (
    <div className="rounded-lg bg-paper/60 p-2.5">
      <dt className="flex items-center gap-1 text-[12px] font-medium text-muted">{icon}{label}</dt>
      <dd className={`mt-0.5 ${value ? "font-medium" : "text-muted"}`}>{value || empty}</dd>
    </div>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return <div><dt className="text-[12px] text-muted">{label}</dt><dd className="font-medium">{children}</dd></div>;
}

function Empty() {
  return <span className="text-[13px] text-muted">—</span>;
}

function Link({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return <button onClick={onClick} className="inline-flex items-center gap-1 text-[13px] font-medium text-blueprint hover:underline">{children} <ArrowRight size={13} /></button>;
}
