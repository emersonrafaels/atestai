import { Check, Loader2, ThumbsDown, ThumbsUp, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, type Assessment, type FindingFeedback, type FindingVerdict } from "../api";
import { SEVERITY, VALIDATION_LABEL } from "../format";

const AUTHOR_KEY = "atest.author"; // o mesmo nome usado na decisão do parecer

const VERDICTS: { id: FindingVerdict; label: string; hint: string; icon: typeof ThumbsUp; color: string; bg: string }[] = [
  { id: "correct", label: "Acertou", hint: "O problema existe e foi bem descrito.", icon: ThumbsUp, color: "var(--color-ok)", bg: "#e3f2ea" },
  { id: "wrong", label: "Errou", hint: "O problema não existe ou foi mal interpretado.", icon: ThumbsDown, color: "var(--color-bad)", bg: "#fbefed" },
];

interface Props {
  assessmentId: number;
  index: number;
  finding: Assessment["findings"][number];
  /** último feedback deste apontamento, se já houver: a escolha e o comentário vêm preenchidos */
  previous?: FindingFeedback;
  /** o apontamento já está marcado como "não procede" na revisão do parecer */
  unfounded: boolean;
  onClose: () => void;
  onSaved: (fb: FindingFeedback) => void;
}

/** Feedback de um apontamento: acertou ou errou, com comentário opcional. Grava no banco ao salvar. */
export function FindingFeedbackDialog({ assessmentId, index, finding, previous, unfounded, onClose, onSaved }: Props) {
  const [verdict, setVerdict] = useState<FindingVerdict | null>(previous?.verdict ?? null);
  const [comment, setComment] = useState(previous?.comment ?? "");
  const [author, setAuthor] = useState(() => { try { return localStorage.getItem(AUTHOR_KEY) ?? ""; } catch { return ""; } });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const first = useRef<HTMLInputElement>(null);

  useEffect(() => {
    first.current?.focus();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && !saving && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose, saving]);

  const save = async () => {
    if (!verdict) return;
    setSaving(true);
    setError(null);
    try {
      const name = author.trim();
      try { localStorage.setItem(AUTHOR_KEY, name); } catch { /* armazenamento indisponível */ }
      const fb = await api.sendFindingFeedback(assessmentId, index, { verdict, comment: comment.trim(), ...(name ? { author: name } : {}) });
      onSaved(fb);
    } catch (e) {
      setError(`Não foi possível salvar o feedback: ${(e as Error).message}`);
      setSaving(false);
    }
  };

  const sev = SEVERITY[finding.severity];
  return createPortal(
    <div className="fixed inset-0 z-[55] flex items-start justify-center overflow-y-auto bg-ink/60 p-4 sm:p-6 sm:pt-24" onClick={() => !saving && onClose()}>
      <div role="dialog" aria-modal="true" aria-labelledby="ffb-title" tabIndex={-1}
        className="surgir w-full max-w-lg rounded-2xl bg-sheet shadow-2xl outline-none" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div className="min-w-0">
            <h2 id="ffb-title" className="largo text-xl font-bold">Este apontamento está certo?</h2>
            <p className="mt-0.5 text-sm text-muted">O seu feedback fica gravado e ajuda a calibrar a régua e os prompts.</p>
          </div>
          <button aria-label="Fechar" onClick={onClose} disabled={saving} className="rounded-full p-1.5 hover:bg-paper"><X size={18} /></button>
        </header>

        <div className="space-y-5 px-6 py-5">
          {/* o apontamento avaliado */}
          <div className="rounded-lg border border-line border-l-4 bg-paper/40 px-3 py-2.5 text-sm" style={{ borderLeftColor: sev?.color }}>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="rounded px-1.5 py-0.5 text-[12px] font-semibold text-white" style={{ background: sev?.color }}>{sev?.label}</span>
              <span className="font-medium">{finding.description}</span>
            </div>
            <p className="mt-1 line-clamp-3 text-muted">{finding.evidence}</p>
            <p className="mt-1 text-[12px] text-muted">{VALIDATION_LABEL[finding.validation]}</p>
          </div>

          {/* acertou / errou */}
          <fieldset>
            <legend className="mb-2 text-sm font-semibold">O apontamento</legend>
            <div className="grid grid-cols-2 gap-2">
              {VERDICTS.map((v, k) => {
                const on = verdict === v.id;
                const Icon = v.icon;
                return (
                  <label key={v.id} className={`flex cursor-pointer flex-col gap-1 rounded-lg border-2 p-3 text-sm transition-colors has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-blueprint ${on ? "" : "border-line hover:border-ink/25"}`}
                    style={on ? { borderColor: v.color, background: v.bg } : undefined}>
                    <input ref={k === 0 ? first : undefined} type="radio" name="finding-verdict" className="sr-only" checked={on} onChange={() => setVerdict(v.id)} />
                    <span className="flex items-center gap-2 font-semibold" style={{ color: on ? v.color : undefined }}>
                      <Icon size={17} /> {v.label}
                      {on && <Check size={15} strokeWidth={3} className="ml-auto" />}
                    </span>
                    <span className="text-[13px] text-muted">{v.hint}</span>
                  </label>
                );
              })}
            </div>
            {verdict === "wrong" && !unfounded && (
              <p className="mt-2 text-[13px] text-muted">
                Para a régua deixar de contar este apontamento na sua decisão, marque também <b className="text-ink">Não procede</b> no apontamento.
              </p>
            )}
          </fieldset>

          <div>
            <label htmlFor="ffb-comment" className="mb-1.5 block text-sm font-semibold">
              Comentário <span className="font-normal text-muted">(opcional)</span>
            </label>
            <textarea id="ffb-comment" value={comment} onChange={(e) => setComment(e.target.value)} rows={3} maxLength={2000}
              placeholder={verdict === "wrong" ? "Ex.: a foto do antes não é exigida para pintura de backoffice" : "Ex.: confirmei na planilha, a linha 3 está fora do escopo"}
              className="w-full rounded-md border border-line px-3 py-2 text-sm" />
          </div>

          <label className="flex items-center gap-2 text-sm">
            <span className="text-muted">Seu nome</span>
            <input value={author} onChange={(e) => setAuthor(e.target.value)} maxLength={80} placeholder="Analista" className="w-48 rounded-md border border-line px-2 py-1" />
          </label>

          {previous && (
            <p className="text-[12px] text-muted">
              Último feedback: <b className="font-medium text-ink">{previous.verdict === "correct" ? "acertou" : "errou"}</b>, em {new Date(previous.created_at).toLocaleString("pt-BR")}.
              Salvar de novo grava um registro novo e mantém o histórico.
            </p>
          )}
          {error && <p role="alert" className="rounded-md bg-[#fbefed] px-3 py-2 text-sm text-bad">{error}</p>}
        </div>

        <footer className="flex items-center justify-end gap-3 border-t border-line px-6 py-4">
          <button onClick={onClose} disabled={saving} className="rounded-lg px-3 py-1.5 text-sm text-muted hover:text-ink">Cancelar</button>
          <button onClick={save} disabled={!verdict || saving}
            className="flex items-center gap-2 rounded-lg bg-blueprint px-4 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-[#1d44a0] disabled:pointer-events-none disabled:opacity-50">
            {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />} Salvar feedback
          </button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
