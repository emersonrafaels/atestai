import { FileSpreadsheet, Loader2, Upload, X } from "lucide-react";
import { useEffect, useState } from "react";
import { InfoBox } from "./ui/InfoBox";
import { api, type TicketSummary, type AppSettings } from "../api";

interface Props {
  config: AppSettings;
  close: () => void;
  created: (c: TicketSummary) => void;
}

/** Envio de um chamado novo pela tela: dados do chamado, planilha Excel padrão e fotos/documentos. */
export function NewTicket({ config, close, created }: Props) {
  const [category, setCategory] = useState(config.categories[0]?.value ?? "");
  const [symptom, setSymptom] = useState(config.symptoms[0]?.value ?? "");
  const [scope, setScope] = useState("");
  const [spreadsheet, setSpreadsheet] = useState<File | null>(null);
  const [attachments, setAttachments] = useState<File[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && !sending && close();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [close, sending]);

  const send = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    const data = new FormData(e.currentTarget);
    if (!spreadsheet) return setError("Anexe a planilha de orçamento.");
    data.set("spreadsheet", spreadsheet);
    data.delete("attachments");
    attachments.forEach((f) => data.append("attachments", f));
    setSending(true);
    try {
      created(await api.sendTicket(data));
    } catch (er) {
      setError((er as Error).message);
    } finally {
      setSending(false);
    }
  };

  const model = `/api/spreadsheet-template?${new URLSearchParams({ category, symptom, scope })}`;
  const field = "w-full rounded-md border border-line bg-sheet px-2.5 py-1.5";
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="titulo-novo" className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/60 p-6">
      <form onSubmit={send} className="w-full max-w-3xl rounded-2xl bg-sheet shadow-2xl">
        <header className="flex items-center justify-between border-b border-line px-6 py-4">
          <div>
            <h2 id="titulo-novo" className="largo text-xl font-bold">Novo chamado</h2>
            <p className="text-sm text-muted">Envie um chamado real ou de teste para analisar no modo API.</p>
          </div>
          <button type="button" aria-label="Fechar" onClick={close} className="rounded-full p-1.5 hover:bg-paper"><X size={18} /></button>
        </header>

        <div className="grid gap-4 px-6 py-5 text-sm md:grid-cols-2">
          <InfoBox id="novo-chamado" className="md:col-span-2" title="Como preencher">
            Descreva o escopo como quem abriu o chamado, escolha categoria e sintoma e baixe o <b>modelo de planilha</b> já preenchido com eles. Depois anexe a planilha do fornecedor e as fotos.
          </InfoBox>
          <label className="md:col-span-2">
            <span className="mb-1 block font-medium">Escopo, como descrito por quem abriu o chamado</span>
            <textarea name="scope" required minLength={3} rows={3} value={scope} onChange={(e) => setScope(e.target.value)} className={field}
              placeholder="Ex.: Ar-condicionado da sala de reunião pingando água no piso. Verificar dreno e corrigir." />
          </label>
          <label>
            <span className="mb-1 block font-medium">Categoria</span>
            <select name="category" value={category} onChange={(e) => setCategory(e.target.value)} className={field}>
              {config.categories.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </label>
          <label>
            <span className="mb-1 block font-medium">Sintoma</span>
            <select name="symptom" value={symptom} onChange={(e) => setSymptom(e.target.value)} className={field}>
              {config.symptoms.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </label>
          <label>
            <span className="mb-1 block font-medium">Esteira</span>
            <select name="workstream" className={field}><option>SETA</option><option>SISR</option></select>
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label>
              <span className="mb-1 block font-medium">Manutenção</span>
              <select name="maintenance_type" className={field}><option value="corrective">Corretiva</option><option value="preventive">Preventiva</option></select>
            </label>
            <label>
              <span className="mb-1 block font-medium">Momento</span>
              <select name="moment" className={field}><option value="execution">Retorno da execução</option><option value="quote">Aprovação do orçamento</option></select>
            </label>
          </div>
          <label>
            <span className="mb-1 block font-medium">Agência</span>
            <input name="branch_name" required placeholder="Ag. Centro" className={field} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label><span className="mb-1 block font-medium">Código</span><input name="branch_code" placeholder="0418" className={field} /></label>
            <label><span className="mb-1 block font-medium">Ambiente</span><input name="environment" placeholder="backoffice" className={field} /></label>
          </div>
          <label><span className="mb-1 block font-medium">Fornecedor</span><input name="supplier_name" placeholder="Razão social" className={field} /></label>
          <div className="grid grid-cols-2 gap-3">
            <label><span className="mb-1 block font-medium">CNPJ</span><input name="supplier_cnpj" className={field} /></label>
            <label><span className="mb-1 block font-medium">Abertura</span><input type="date" name="opened_on" className={field} /></label>
          </div>

          <div className="rounded-xl border border-dashed border-line p-4 md:col-span-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">Orçamento (planilha Excel padrão)</span>
              <a href={model} className="flex items-center gap-1.5 text-blueprint hover:underline"><FileSpreadsheet size={15} /> Baixar modelo preenchido com categoria, sintoma e escopo</a>
            </div>
            <input type="file" accept=".xlsx,.xlsm" required onChange={(e) => setSpreadsheet(e.target.files?.[0] ?? null)}
              className="mt-2 block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-blueprint-soft file:px-3 file:py-1.5 file:text-blueprint" />
          </div>
          <div className="rounded-xl border border-dashed border-line p-4 md:col-span-2">
            <span className="font-medium">Fotos e documentos (JPG, PNG, WEBP ou PDF)</span>
            <input type="file" multiple accept=".jpg,.jpeg,.png,.webp,.pdf" onChange={(e) => setAttachments([...(e.target.files ?? [])])}
              className="mt-2 block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-blueprint-soft file:px-3 file:py-1.5 file:text-blueprint" />
            {attachments.length > 0 && <p className="mt-1 text-muted">{attachments.length} arquivo(s): {attachments.map((f) => f.name).join(", ")}</p>}
          </div>
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-line px-6 py-4">
          <span className="text-sm text-bad">{error}</span>
          <div className="flex gap-2">
            <button type="button" onClick={close} className="rounded-lg border border-line px-4 py-2">Cancelar</button>
            <button type="submit" disabled={sending} className="flex items-center gap-2 rounded-lg bg-blueprint px-4 py-2 font-semibold text-white disabled:opacity-50">
              {sending ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />} Enviar chamado
            </button>
          </div>
        </footer>
      </form>
    </div>
  );
}
