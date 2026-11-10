import { AlertTriangle, Loader2, MessageSquare, Search, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { adminApi, type AdminAssessmentItem, type DeleteAssessmentsResult } from "../../api";
import { brl } from "../../format";
import { ScorePill } from "../ScoreBadge";
import { InfoBox } from "../ui/InfoBox";

const PAGE = 200;
const CONFIRM_WORD = "APAGAR";
type Confirm = { kind: "selected" } | { kind: "all" } | null;

/** Limpeza do histórico de análises: apaga pareceres já emitidos (todos ou os escolhidos), com feedbacks e chamadas ao modelo. */
export function AnalysesCleanup({ onCleared }: { onCleared?: (r: DeleteAssessmentsResult) => void }) {
  const [items, setItems] = useState<AdminAssessmentItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [mode, setMode] = useState<"all" | "simulated" | "api">("all");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [limit, setLimit] = useState(PAGE);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(() => adminApi.assessments().then((a) => { setItems(a); setError(null); }).catch((e) => setError((e as Error).message)), []);
  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase();
    return (items ?? []).filter((a) => (mode === "all" || a.mode === mode)
      && (!t || `${a.ticket_id} ${a.run_id ?? ""} ${a.run_label ?? ""}`.toLowerCase().includes(t)));
  }, [items, q, mode]);
  useEffect(() => setLimit(PAGE), [q, mode]);

  const filteredSelected = filtered.filter((a) => selected.has(a.id)).length;
  const allFiltered = filtered.length > 0 && filteredSelected === filtered.length;
  const headerBox = useRef<HTMLInputElement>(null);
  useEffect(() => { if (headerBox.current) headerBox.current.indeterminate = filteredSelected > 0 && !allFiltered; }, [filteredSelected, allFiltered]);

  const toggle = (id: number) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const toggleFiltered = () => setSelected((s) => {
    const n = new Set(s);
    filtered.forEach((a) => (allFiltered ? n.delete(a.id) : n.add(a.id)));
    return n;
  });

  const done = (r: DeleteAssessmentsResult) => {
    setConfirm(null);
    setSelected(new Set());
    const runs = r.runs_removed.length ? `, ${r.runs_removed.length} execução(ões) que ficaram vazias` : "";
    const fbs = r.feedbacks ? `, ${r.feedbacks} feedback(s)` : "";
    setMsg(`${r.assessments} análise(s) apagada(s)${fbs}${runs}.`);
    onCleared?.(r);
    load();
  };

  if (error && !items) return <p className="text-bad">{error}</p>;
  if (!items) return <Loader2 className="animate-spin text-muted" />;

  const tickets = new Set(items.map((a) => a.ticket_id)).size;
  const runs = new Set(items.map((a) => a.run_id).filter(Boolean)).size;
  const chosen = items.filter((a) => selected.has(a.id));

  return (
    <div className="space-y-4">
      {msg && (
        <p role="status" className="flex items-center justify-between gap-2 rounded-lg bg-[#e3f2ea] px-3 py-2 text-sm text-ok">
          {msg}<button onClick={() => setMsg(null)} aria-label="Fechar aviso" className="rounded p-0.5 hover:bg-white/60"><X size={14} /></button>
        </p>
      )}

      <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-sheet p-5">
        <div>
          <div className="largo text-[26px] font-bold tabular-nums">{items.length}</div>
          <div className="text-[13px] text-muted">análise(s) gravada(s) · {tickets} chamado(s) · {runs} execução(ões)</div>
        </div>
        <button onClick={() => setConfirm({ kind: "all" })} disabled={!items.length}
          className="flex items-center gap-1.5 rounded-lg border border-bad/40 px-3 py-1.5 text-sm font-semibold text-bad hover:bg-[#fbefed] disabled:pointer-events-none disabled:opacity-50">
          <Trash2 size={15} /> Apagar todas as análises
        </button>
      </section>

      <InfoBox id="admin-cleanup">
        Apagar uma análise remove o parecer, o feedback registrado nele e as chamadas ao modelo. Execuções que ficam sem nenhuma análise saem junto, com o relatório de validação.
        Os chamados continuam na lista e podem ser analisados de novo; os arquivos já exportados em <span className="font-mono">outputs/</span> não são apagados.
      </InfoBox>

      {items.length > 0 && (
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-1.5 rounded-md border border-line bg-sheet px-2 py-1.5 text-sm">
            <Search size={14} className="text-muted" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Chamado, execução ou rótulo" className="w-60 bg-transparent outline-none" />
          </label>
          <div className="flex rounded-lg bg-paper p-0.5 text-sm">
            {(["all", "simulated", "api"] as const).map((m) => (
              <button key={m} onClick={() => setMode(m)} className={`rounded-md px-3 py-1 ${mode === m ? "bg-sheet font-semibold shadow-sm" : "text-muted"}`}>
                {m === "all" ? "Todos os modos" : m === "api" ? "API" : "Simulado"}
              </button>
            ))}
          </div>
          <span className="text-[13px] text-muted">{filtered.length} na lista{selected.size > 0 && ` · ${selected.size} selecionada(s)`}</span>
        </div>
      )}

      {!items.length ? (
        <p className="rounded-xl border border-dashed border-line bg-sheet p-8 text-center text-muted">Nenhuma análise gravada: o histórico está vazio.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-line bg-sheet">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="bg-paper/60 text-left text-[12px] text-muted">
              <tr>
                <th className="w-10 px-4 py-2">
                  <input ref={headerBox} type="checkbox" checked={allFiltered} onChange={toggleFiltered} disabled={!filtered.length}
                    aria-label={allFiltered ? "Desmarcar as análises da lista" : "Selecionar todas as análises da lista"} className="size-4 accent-blueprint" />
                </th>
                <th className="px-3 py-2 font-medium">Chamado</th>
                <th className="px-3 py-2 font-medium">Data</th>
                <th className="px-3 py-2 font-medium">Execução</th>
                <th className="px-3 py-2 font-medium">Modo</th>
                <th className="px-3 py-2 font-medium">Parecer</th>
                <th className="px-5 py-2 text-right font-medium">Custo</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, limit).map((a) => (
                <tr key={a.id} onClick={() => toggle(a.id)} className={`cursor-pointer border-t border-line/70 ${selected.has(a.id) ? "bg-blueprint-soft/50" : "hover:bg-paper/50"}`}>
                  <td className="px-4 py-2" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={selected.has(a.id)} onChange={() => toggle(a.id)} aria-label={`Selecionar a análise #${a.id} do chamado ${a.ticket_id}`} className="size-4 accent-blueprint" />
                  </td>
                  <td className="px-3 py-2 font-mono text-[13px]">{a.ticket_id}</td>
                  <td className="px-3 py-2 text-muted">{new Date(a.generated_at).toLocaleString("pt-BR")}</td>
                  <td className="max-w-[220px] px-3 py-2">
                    <div className="truncate">{a.run_label || <span className="font-mono text-[12px] text-muted">{a.run_id ?? "—"}</span>}</div>
                    {a.run_label && <div className="truncate font-mono text-[11px] text-muted">{a.run_id}</div>}
                  </td>
                  <td className="px-3 py-2">{a.mode === "api" ? "API" : "Simulado"}</td>
                  <td className="px-3 py-2">
                    <span className="flex items-center gap-2">
                      <ScorePill score={a.score} recommendation={a.recommendation} />
                      {a.feedbacks > 0 && <span title={`${a.feedbacks} feedback(s) registrado(s)`} className="flex items-center gap-0.5 text-[12px] text-muted"><MessageSquare size={12} />{a.feedbacks}</span>}
                    </span>
                  </td>
                  <td className="px-5 py-2 text-right tabular-nums text-muted">{a.mode === "api" ? brl(a.cost_brl) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!filtered.length && <p className="p-6 text-center text-sm text-muted">Nenhuma análise com esse filtro.</p>}
          {filtered.length > limit && (
            <button onClick={() => setLimit((l) => l + PAGE)} className="w-full border-t border-line py-2 text-sm font-medium text-blueprint hover:bg-paper/60">
              Mostrar mais ({filtered.length - limit} restantes)
            </button>
          )}
        </div>
      )}

      {/* barra de ação: aparece com seleção */}
      {selected.size > 0 && !confirm && (
        <div className="surgir fixed inset-x-0 bottom-9 z-30 flex justify-center px-4">
          <div className="flex w-full max-w-2xl flex-wrap items-center gap-3 rounded-2xl border border-line bg-sheet p-3 shadow-2xl">
            <span className="flex-1 text-sm font-semibold">{selected.size} análise(s) selecionada(s)</span>
            <button onClick={() => setSelected(new Set())} className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-paper">Limpar seleção</button>
            <button onClick={() => setConfirm({ kind: "selected" })} className="flex items-center gap-1.5 rounded-lg bg-bad px-4 py-1.5 text-sm font-semibold text-white hover:opacity-90">
              <Trash2 size={15} /> Apagar selecionadas
            </button>
          </div>
        </div>
      )}

      {confirm && (
        <ConfirmDelete
          all={confirm.kind === "all"}
          items={confirm.kind === "all" ? items : chosen}
          onCancel={() => setConfirm(null)}
          onConfirm={async () => done(await adminApi.deleteAssessments(confirm.kind === "all" ? { all: true } : { ids: chosen.map((a) => a.id) }))}
        />
      )}
    </div>
  );
}

function ConfirmDelete({ all, items, onCancel, onConfirm }: { all: boolean; items: AdminAssessmentItem[]; onCancel: () => void; onConfirm: () => Promise<void> }) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tickets = new Set(items.map((a) => a.ticket_id)).size;
  const feedbacks = items.reduce((s, a) => s + a.feedbacks, 0);
  const running = items.some((a) => a.run_status === "running");
  const ok = !all || typed.trim().toUpperCase() === CONFIRM_WORD;

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onCancel(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [busy, onCancel]);

  const go = async () => {
    setBusy(true);
    setError(null);
    try { await onConfirm(); } catch (e) { setError((e as Error).message); setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-ink/30 p-4" onClick={() => !busy && onCancel()}>
      <div role="alertdialog" aria-modal="true" aria-labelledby="cleanup-title" onClick={(e) => e.stopPropagation()}
        className="surgir w-full max-w-md rounded-2xl border border-line bg-sheet p-6 shadow-2xl">
        <div className="mb-3 flex items-center gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-[#fbefed] text-bad"><AlertTriangle size={20} /></span>
          <h3 id="cleanup-title" className="largo text-lg font-bold">{all ? "Apagar todas as análises?" : `Apagar ${items.length} análise(s)?`}</h3>
        </div>
        <p className="text-sm">
          Serão apagados <b>{items.length}</b> parecer(es) de <b>{tickets}</b> chamado(s){feedbacks > 0 && <>, com <b>{feedbacks}</b> feedback(s) da equipe</>}.
          {all && " As execuções e os relatórios de validação também saem; as métricas da aba Operação voltam a zero."}
          {" "}Não dá para desfazer.
        </p>
        {running && <p className="mt-2 text-[13px] text-warn">Há execução em andamento: os pareceres que ela ainda gravar não entram nesta limpeza.</p>}
        {all && (
          <label className="mt-4 block text-sm">
            <span className="mb-1 block">Digite <b className="font-mono">{CONFIRM_WORD}</b> para confirmar</span>
            <input autoFocus value={typed} onChange={(e) => setTyped(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && ok && !busy) go(); }}
              className="w-full rounded-lg border border-line px-3 py-1.5 font-mono outline-none focus:border-bad" />
          </label>
        )}
        {error && <p role="alert" className="mt-3 rounded-md bg-[#fbefed] px-3 py-1.5 text-sm text-bad">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onCancel} disabled={busy} autoFocus={!all} className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-paper">Cancelar</button>
          <button onClick={go} disabled={!ok || busy}
            className="flex items-center gap-1.5 rounded-lg bg-bad px-4 py-1.5 text-sm font-semibold text-white hover:opacity-90 disabled:pointer-events-none disabled:opacity-50">
            {busy ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />} Apagar
          </button>
        </div>
      </div>
    </div>
  );
}
