import { Lock, RotateCcw, ShieldAlert } from "lucide-react";
import type { FindingTypeConfig, RubricConfig } from "../../api";
import { pts, REC, SEVERITY, VALIDATIONS, VALIDATION_LABEL, VALIDATION_SHORT } from "../../format";
import { BandScale } from "../ScoreBreakdown";
import { InfoBox } from "../ui/InfoBox";
import { Switch } from "../ui/Switch";
import { InfoTip, Tooltip } from "../ui/Tooltip";

interface Props {
  data: RubricConfig;
  base: RubricConfig;
  onChange: (next: RubricConfig) => void;
}

const AMOUNT: Record<string, string> = { item: "Linha inteira", excess: "Só o excedente", none: "—" };
const SEVERITIES = ["critical", "high", "medium", "low"] as const;

/** Tipos de apontamento: ativar/desativar e ajustar severidade, fase, trava e redução de confiança. */
export function FindingRulesEditor({ data, base, onChange }: Props) {
  const total = VALIDATIONS.reduce((s, v) => s + data.weights[v], 0) || 100;
  const set = (kind: string, patch: Partial<FindingTypeConfig>) =>
    onChange({ ...data, finding_types: { ...data.finding_types, [kind]: { ...data.finding_types[kind], ...patch } } });
  const entries = Object.entries(data.finding_types);
  const off = entries.filter(([, f]) => !f.enabled).length;

  return (
    <div className="space-y-5">
      <InfoBox id="admin-findings" title="O que cada regra faz">
        Cada tipo de apontamento é uma verificação. <b>Desativado</b>, ele não é gerado, não desconta e não entra no valor potencial divergente.
        A <b>severidade</b> define quanto tira da nota da validação; a <b>fase</b> define se vale já no MVP (1) ou só na Fase 2;
        a <b>trava</b> devolve o chamado qualquer que seja o score.
      </InfoBox>
      <p className="text-sm text-muted">{entries.length - off} de {entries.length} regras ativas{off ? ` · ${off} desativada${off === 1 ? "" : "s"}` : ""}.</p>

      {VALIDATIONS.map((v) => (
        <section key={v} className="overflow-hidden rounded-xl border border-line bg-sheet">
          <h3 className="flex items-baseline justify-between border-b border-line px-5 py-3 font-semibold">
            {VALIDATION_LABEL[v]} <span className="text-[13px] font-normal text-muted">peso {data.weights[v]}% no score</span>
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-sm">
              <thead className="bg-paper/60 text-left text-[12px] text-muted">
                <tr>
                  <th className="w-14 px-4 py-2 font-medium">Ativa</th>
                  <th className="px-2 py-2 font-medium">Regra</th>
                  <th className="px-2 py-2 font-medium">Severidade</th>
                  <th className="px-2 py-2 text-right font-medium"><Tooltip content="Quanto tira do score final: desconto da severidade × peso da validação"><span className="cursor-help">Efeito no score</span></Tooltip></th>
                  <th className="px-2 py-2 font-medium">Fase</th>
                  <th className="px-2 py-2 text-center font-medium"><Tooltip content="Trava: devolve o chamado qualquer que seja o score"><span className="cursor-help">Trava</span></Tooltip></th>
                  <th className="px-2 py-2 text-center font-medium"><Tooltip content="Reduz a confiança da análise; dois redutores mandam para análise detalhada"><span className="cursor-help">Reduz confiança</span></Tooltip></th>
                  <th className="px-4 py-2 font-medium"><Tooltip content="Como entra no valor potencial divergente (definido no código)"><span className="cursor-help">Valor divergente</span></Tooltip></th>
                </tr>
              </thead>
              <tbody>
                {entries.filter(([, f]) => f.validation === v).map(([kind, f]) => {
                  const b = base.finding_types[kind];
                  const changed = JSON.stringify(b) !== JSON.stringify(f);
                  const effect = (data.discount_by_severity[f.severity] * data.weights[v]) / total;
                  return (
                    <tr key={kind} className={`border-t border-line/70 ${!f.enabled ? "bg-paper/50 text-muted" : changed ? "bg-[#fffaf0]" : ""}`}>
                      <td className="px-4 py-2"><Switch on={f.enabled} onChange={(on) => set(kind, { enabled: on })} label={`${f.description}: ${f.enabled ? "ativa" : "desativada"}`} /></td>
                      <td className="px-2 py-2">
                        <div className={`font-medium ${f.enabled ? "" : "line-through"}`}>{f.description}</div>
                        <div className="flex items-center gap-2 font-mono text-[11px] text-muted">
                          {kind}
                          {changed && (
                            <button onClick={() => set(kind, b)} className="flex items-center gap-0.5 font-sans text-warn hover:underline"><RotateCcw size={11} /> desfazer</button>
                          )}
                        </div>
                      </td>
                      <td className="px-2 py-2">
                        <select value={f.severity} disabled={!f.enabled} onChange={(e) => set(kind, { severity: e.target.value as FindingTypeConfig["severity"] })}
                          className="rounded-md border border-line bg-sheet px-1.5 py-1 font-medium" style={{ color: SEVERITY[f.severity].color }}>
                          {SEVERITIES.map((s) => <option key={s} value={s}>{SEVERITY[s].label} (−{data.discount_by_severity[s]})</option>)}
                        </select>
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">{f.enabled ? <span className="font-semibold text-bad">−{pts(effect)}</span> : "—"}</td>
                      <td className="px-2 py-2">
                        <select value={f.phase} disabled={!f.enabled} onChange={(e) => set(kind, { phase: Number(e.target.value) })} className="rounded-md border border-line bg-sheet px-1.5 py-1">
                          <option value={1}>Fase 1</option><option value={2}>Fase 2</option>
                        </select>
                      </td>
                      <td className="px-2 py-2 text-center"><span className="inline-flex items-center gap-1"><Switch size="sm" on={f.lock} disabled={!f.enabled} onChange={(on) => set(kind, { lock: on })} label="Trava" />{f.lock && <Lock size={12} className="text-lock" />}</span></td>
                      <td className="px-2 py-2 text-center"><span className="inline-flex items-center gap-1"><Switch size="sm" on={f.reduces_confidence} disabled={!f.enabled} onChange={(on) => set(kind, { reduces_confidence: on })} label="Reduz confiança" />{f.reduces_confidence && <ShieldAlert size={12} className="text-muted" />}</span></td>
                      <td className="px-4 py-2 text-[12px] text-muted">{AMOUNT[f.amount_at_issue] ?? f.amount_at_issue}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}

/** Régua do score: pesos, descontos, faixas, confiança e tolerâncias. */
export function ScoreRubricEditor({ data, base, onChange }: Props) {
  const sum = VALIDATIONS.reduce((s, v) => s + (data.weights[v] || 0), 0);
  const approve = data.bands.find((b) => b.recommendation === "approve")?.score_min ?? 85;
  const caveats = data.bands.find((b) => b.recommendation === "approve_with_caveats")?.score_min ?? 70;
  const setBand = (rec: "approve" | "approve_with_caveats", v: number) =>
    onChange({ ...data, bands: data.bands.map((b) => (b.recommendation === rec ? { ...b, score_min: v } : b)) });
  const bandError = !(caveats > 0 && approve > caveats && approve <= 100);
  const num = (v: string) => (v === "" ? 0 : Number(v));
  const diff = (a: unknown, b: unknown) => JSON.stringify(a) !== JSON.stringify(b);
  const field = (changed: boolean, bad = false) => `w-20 rounded-md border px-2 py-1 text-right tabular-nums ${bad ? "border-bad bg-[#fbefed]" : changed ? "border-warn bg-[#fdf6e4]" : "border-line"}`;

  return (
    <div className="space-y-5">
      <InfoBox id="admin-score" title="Mudanças aqui afetam todos os chamados">
        A régua converte apontamentos em score e recomendação. Depois de mudar, rode a <b>Validação</b> para ver o impacto na acurácia antes de usar em produção.
      </InfoBox>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="rounded-xl border border-line bg-sheet p-5">
          <h3 className="flex items-center gap-1.5 font-semibold">Pesos das validações <InfoTip term="weight" /></h3>
          <p className="mb-3 text-[13px] text-muted">Quanto cada validação vale no score. Precisam somar 100.</p>
          <div className="space-y-2 text-sm">
            {VALIDATIONS.map((v) => (
              <label key={v} className="flex items-center justify-between gap-3">
                <span>{VALIDATION_LABEL[v]}</span>
                <span className="flex items-center gap-1"><input type="number" min={0} max={100} value={data.weights[v]} onChange={(e) => onChange({ ...data, weights: { ...data.weights, [v]: num(e.target.value) } })} className={field(data.weights[v] !== base.weights[v], sum !== 100)} />%</span>
              </label>
            ))}
            <div className={`flex justify-between border-t border-line pt-2 font-semibold ${sum === 100 ? "text-ok" : "text-bad"}`}>
              <span>Total</span><span className="tabular-nums">{sum}%{sum !== 100 && ` (faltam ${100 - sum})`}</span>
            </div>
          </div>
        </section>

        <section className="rounded-xl border border-line bg-sheet p-5">
          <h3 className="flex items-center gap-1.5 font-semibold">Desconto por severidade <InfoTip term="severity" /></h3>
          <p className="mb-3 text-[13px] text-muted">Pontos tirados da nota da validação (0–100) por apontamento. O efeito no score depende do peso.</p>
          <div className="space-y-2 text-sm">
            {SEVERITIES.map((s) => (
              <label key={s} className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-2"><i className="size-2.5 rounded-sm" style={{ background: SEVERITY[s].color }} />{SEVERITY[s].label}</span>
                <span className="flex items-center gap-3">
                  <span className="text-[12px] text-muted">{VALIDATIONS.map((v) => `${VALIDATION_SHORT[v]} −${pts((data.discount_by_severity[s] * data.weights[v]) / (sum || 100))}`).join(" · ")}</span>
                  <span className="flex items-center gap-1">−<input type="number" min={0} max={100} value={data.discount_by_severity[s]}
                    onChange={(e) => onChange({ ...data, discount_by_severity: { ...data.discount_by_severity, [s]: num(e.target.value) } })}
                    className={field(data.discount_by_severity[s] !== base.discount_by_severity[s])} /></span>
                </span>
              </label>
            ))}
          </div>
        </section>

        <section className="rounded-xl border border-line bg-sheet p-5">
          <h3 className="flex items-center gap-1.5 font-semibold">Faixas de recomendação <InfoTip term="bands" /></h3>
          <p className="mb-3 text-[13px] text-muted">Score mínimo para cada recomendação. Abaixo de “Ressalvas”, devolve ao fornecedor.</p>
          <div className="space-y-2 text-sm">
            <label className="flex items-center justify-between"><span style={{ color: REC.approve.color }} className="font-medium">Aprovar a partir de</span>
              <input type="number" min={1} max={100} value={approve} onChange={(e) => setBand("approve", num(e.target.value))} className={field(diff(data.bands, base.bands), bandError)} /></label>
            <label className="flex items-center justify-between"><span style={{ color: REC.approve_with_caveats.color }} className="font-medium">Aprovar com ressalvas a partir de</span>
              <input type="number" min={1} max={99} value={caveats} onChange={(e) => setBand("approve_with_caveats", num(e.target.value))} className={field(diff(data.bands, base.bands), bandError)} /></label>
            {bandError && <p className="text-[12px] text-bad">“Aprovar” precisa ser maior que “Ressalvas”, e ambos entre 1 e 100.</p>}
            {!bandError && <div className="pt-2"><BandScale score={approve} rubric={{ weights: data.weights, discount_by_severity: data.discount_by_severity, bands: data.bands, confidence: data.confidence }} /></div>}
          </div>
        </section>

        <section className="rounded-xl border border-line bg-sheet p-5">
          <h3 className="flex items-center gap-1.5 font-semibold">Confiança <InfoTip term="confidence" /></h3>
          <p className="mb-3 text-[13px] text-muted">Quantos redutores (escopo vago, foto ilegível…) levam a confiança média ou baixa. Confiança baixa manda para análise detalhada.</p>
          <div className="space-y-2 text-sm">
            <label className="flex items-center justify-between"><span>Confiança média com</span>
              <span className="flex items-center gap-1"><input type="number" min={1} max={5} value={data.confidence.medium_with_n_reducers} onChange={(e) => onChange({ ...data, confidence: { ...data.confidence, medium_with_n_reducers: num(e.target.value) } })} className={field(data.confidence.medium_with_n_reducers !== base.confidence.medium_with_n_reducers)} /> redutor(es)</span></label>
            <label className="flex items-center justify-between"><span>Confiança baixa com</span>
              <span className="flex items-center gap-1"><input type="number" min={1} max={5} value={data.confidence.low_with_n_reducers} onChange={(e) => onChange({ ...data, confidence: { ...data.confidence, low_with_n_reducers: num(e.target.value) } })} className={field(data.confidence.low_with_n_reducers !== base.confidence.low_with_n_reducers, data.confidence.medium_with_n_reducers > data.confidence.low_with_n_reducers)} /> redutor(es)</span></label>
          </div>
        </section>
      </div>

      <section className="rounded-xl border border-line bg-sheet p-5">
        <h3 className="font-semibold">Tolerâncias das verificações</h3>
        <p className="mb-3 text-[13px] text-muted">Limites das checagens feitas por regra (sem o modelo).</p>
        <div className="grid gap-x-8 gap-y-3 text-sm md:grid-cols-2">
          {([
            ["price_tolerance_pct", "Tolerância de preço sobre a referência (LPU)", "%", "Acima de referência + tolerância vira “Preço acima da referência”."],
            ["spreadsheet_value_tolerance", "Diferença aceita entre planilha e chamado", "R$", "Diferença de valor total tolerada antes de virar “Planilha divergente”."],
            ["photo_date_tolerance_days", "Tolerância da data da foto", "dias", "Foto tirada até N dias antes da abertura não é apontada."],
            ["hash_max_distance", "Semelhança para foto reaproveitada", "dist.", "Distância máxima (0 = idêntica) para considerar a foto uma cópia. Menor = mais rigoroso para acusar."],
            ["hash_max_distance_low_detail", "Semelhança em foto escura/tremida", "dist.", "Limite mais estrito para fotos com pouco detalhe."],
            ["hash_min_detail", "Detalhe mínimo da foto", "", "Abaixo disso a foto é considerada de pouco detalhe."],
          ] as const).map(([k, label, unit, help]) => (
            <label key={k} className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-1">{label} <InfoTip text={help} size={12} /></span>
              <span className="flex items-center gap-1 whitespace-nowrap">
                <input type="number" step="any" min={0} value={data[k]} onChange={(e) => onChange({ ...data, [k]: num(e.target.value) })} className={field(data[k] !== base[k])} />
                <span className="w-8 text-[12px] text-muted">{unit}</span>
              </span>
            </label>
          ))}
        </div>
      </section>
    </div>
  );
}
