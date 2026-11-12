import { FileSpreadsheet, Loader2, Paperclip, Upload, X } from "lucide-react";
import { cloneElement, useEffect, useId, useRef, useState, type ReactElement, type ReactNode } from "react";
import { InfoBox } from "./ui/InfoBox";
import { InfoTip } from "./ui/Tooltip";
import { api, type TicketSummary, type AppSettings } from "../api";

interface Props {
  config: AppSettings;
  close: () => void;
  created: (c: TicketSummary) => void;
}

const field = "w-full rounded-md border border-line bg-sheet px-2.5 py-1.5 disabled:opacity-60";
const fileInput = "mt-2 block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-blueprint-soft file:px-3 file:py-1.5 file:text-blueprint";

/** Rótulo do campo: nome, marca de obrigatório, tooltip de ajuda e dica curta abaixo. */
function Field({ label, required, tip, hint, className = "", children }: {
  label: string; required?: boolean; tip: ReactNode; hint?: ReactNode; className?: string; children: ReactElement<{ id?: string; "aria-describedby"?: string }>;
}) {
  const id = useId();
  return (
    <div className={className}>
      <div className="mb-1 flex items-center gap-1.5">
        <label htmlFor={id} className="font-medium">
          {label}
          {required ? <span className="ml-1 text-bad" aria-hidden>*</span> : <span className="ml-1.5 text-[12px] font-normal text-muted">opcional</span>}
          {required && <span className="sr-only"> (obrigatório)</span>}
        </label>
        <InfoTip text={tip} label={`Ajuda: ${label}`} size={13} />
      </div>
      {cloneElement(children, { id, "aria-describedby": hint ? `${id}-hint` : undefined })}
      {hint && <p id={`${id}-hint`} className="mt-1 text-[12px] text-muted">{hint}</p>}
    </div>
  );
}

function Section({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="grid gap-4 md:grid-cols-6">
      <h3 className="flex items-center gap-2 text-[13px] font-semibold uppercase tracking-wide text-muted md:col-span-6">
        <span className="grid size-5 place-items-center rounded-full bg-blueprint-soft text-[11px] text-blueprint">{n}</span>
        {title}
      </h3>
      {children}
    </section>
  );
}

/** Envio de um chamado novo pela tela: classificação, descrição, agência/fornecedor, planilha com os itens e fotos/documentos. */
export function NewTicket({ config, close, created }: Props) {
  // cadastro: só itens ativos; a esteira filtra categorias e locais, e a categoria filtra os sintomas
  const [workstream, setWorkstream] = useState<"SETA" | "SISR">("SETA");
  const categories = config.categories.filter((c) => c.enabled !== false && (!c.workstreams?.length || c.workstreams.includes(workstream)));
  const [category, setCategory] = useState(categories[0]?.value ?? "");
  const symptoms = config.symptoms.filter((s) => s.enabled !== false && (!s.categories?.length || s.categories.includes(category)));
  const [symptom, setSymptom] = useState(symptoms[0]?.value ?? "");
  const locations = (config.locations ?? []).filter((l) => l.enabled !== false && (!l.workstreams?.length || l.workstreams.includes(workstream)));
  const [location, setLocation] = useState("");
  useEffect(() => { if (location && !locations.some((l) => l.value === location)) setLocation(""); }, [locations, location]);
  const [blocksOpening, setBlocksOpening] = useState(false);
  useEffect(() => { if (!categories.some((c) => c.value === category)) setCategory(categories[0]?.value ?? ""); }, [categories, category]);
  useEffect(() => { if (!symptoms.some((s) => s.value === symptom)) setSymptom(symptoms[0]?.value ?? ""); }, [symptoms, symptom]);
  const [scope, setScope] = useState("");
  const [spreadsheet, setSpreadsheet] = useState<File | null>(null);
  const [attachments, setAttachments] = useState<File[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useRef<HTMLFormElement>(null);

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

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="titulo-novo" className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/60 p-6">
      <form ref={form} onSubmit={send} className="w-full max-w-3xl rounded-2xl bg-sheet shadow-2xl">
        <header className="flex items-center justify-between border-b border-line px-6 py-4">
          <div>
            <h2 id="titulo-novo" className="largo text-xl font-bold">Novo chamado</h2>
            <p className="text-sm text-muted">
              Envie um chamado real ou de teste para analisar no modo API. Campos com <span className="text-bad">*</span> são obrigatórios.
            </p>
          </div>
          <button type="button" aria-label="Fechar" onClick={close} className="rounded-full p-1.5 hover:bg-paper"><X size={18} /></button>
        </header>

        <div className="grid gap-6 px-6 py-5 text-sm">
          <InfoBox id="novo-chamado" title="Como preencher">
            Comece pela <b>esteira</b>: ela define as categorias e os locais disponíveis. Depois descreva o problema como quem abriu o chamado
            e anexe o orçamento e as fotos. No orçamento basta a <b>lista de itens</b>: os dados do chamado vêm deste formulário.
          </InfoBox>

          <Section n={1} title="Classificação">
            <Field className="md:col-span-2" label="Esteira" required
              tip="Fluxo de atendimento do chamado. SETA e SISR têm categorias, locais e regras de checklist próprios.">
              <select name="workstream" required value={workstream} onChange={(e) => setWorkstream(e.target.value as "SETA" | "SISR")} className={field}>
                <option>SETA</option><option>SISR</option>
              </select>
            </Field>
            <Field className="md:col-span-2" label="Etapa da esteira" required
              tip="Momento em que a análise acontece: na aprovação do orçamento (antes do serviço) ou na atestação (serviço já executado, com fotos do depois).">
              <select name="moment" required className={field}><option value="quote">Aprovação de Orçamento</option><option value="execution">Atestação do Serviço</option></select>
            </Field>
            <Field className="md:col-span-2" label="Tipo de manutenção" required
              tip="Corretiva: conserto de algo que falhou. Preventiva: manutenção programada para evitar falhas.">
              <select name="maintenance_type" required className={field}><option value="corrective">Corretiva</option><option value="preventive">Preventiva</option></select>
            </Field>
            <Field className="md:col-span-3" label="Categoria" required
              tip="Disciplina do serviço (elétrica, ar-condicionado…). A lista mostra só as categorias ativas da esteira escolhida."
              hint={categories.length === 0 ? <span className="text-bad">Nenhuma categoria ativa para a esteira {workstream}.</span> : undefined}>
              <select name="category" required value={category} onChange={(e) => setCategory(e.target.value)} className={field}>
                {categories.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </Field>
            <Field className="md:col-span-3" label="Sintoma" required
              tip="O problema relatado dentro da categoria. Define o checklist de evidências que a análise vai cobrar."
              hint={symptoms.length === 0 ? <span className="text-bad">Nenhum sintoma ativo para esta categoria.</span> : undefined}>
              <select name="symptom" required value={symptom} onChange={(e) => setSymptom(e.target.value)} className={field}>
                {symptoms.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
            </Field>
            <Field className="md:col-span-3" label="Local do chamado" tip="Ambiente da agência onde está o problema (fachada, autoatendimento…). A lista depende da esteira.">
              <select name="environment" value={location} onChange={(e) => setLocation(e.target.value)} className={field}>
                <option value="">Não informado</option>
                {locations.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
              </select>
            </Field>
            <fieldset className="md:col-span-3">
              <legend className="mb-1 flex items-center gap-1.5 font-medium">
                Este problema está impedindo a abertura da agência? <span className="text-bad" aria-hidden>*</span>
                <InfoTip text="Marque Sim quando a agência não consegue abrir ao público por causa do problema. O chamado ganha prioridade." label="Ajuda: impede a abertura" size={13} />
              </legend>
              <input type="hidden" name="blocks_opening" value={blocksOpening ? "true" : "false"} />
              <div className="flex gap-5">
                {([[true, "Sim"], [false, "Não"]] as const).map(([v, l]) => (
                  <label key={l} className="flex cursor-pointer items-center gap-1.5">
                    <input type="radio" name="blocks_opening_choice" checked={blocksOpening === v} onChange={() => setBlocksOpening(v)} className="size-4 accent-[var(--color-blueprint)]" /> {l}
                  </label>
                ))}
              </div>
            </fieldset>
          </Section>

          <Section n={2} title="Descrição">
            <Field className="md:col-span-6" label="Descrição detalhada do problema" required
              tip="Texto de quem abriu o chamado. A análise compara o orçamento e as fotos com o que foi pedido aqui."
              hint="Diga o que acontece, onde e desde quando. Mínimo de 3 caracteres.">
              <textarea name="scope" required minLength={3} rows={3} value={scope} onChange={(e) => setScope(e.target.value)} className={field}
                placeholder="Ex.: Ar-condicionado da sala de reunião pingando água no piso. Verificar dreno e corrigir." />
            </Field>
            <Field className="md:col-span-6" label="Descrição da solução"
              tip="O que o fornecedor propõe fazer. Pode ser preenchida agora ou só na aprovação do orçamento."
              hint="Até 4.000 caracteres.">
              <textarea name="solution_description" rows={2} maxLength={4000} className={field}
                placeholder="Ex.: Desobstruir o dreno, trocar a mangueira e testar o escoamento." />
            </Field>
          </Section>

          <Section n={3} title="Agência e fornecedor">
            <Field className="md:col-span-4" label="Agência" required tip="Nome da agência onde o serviço será feito.">
              <input name="branch_name" required placeholder="Ag. Centro" className={field} />
            </Field>
            <Field className="md:col-span-2" label="Código da agência" tip="Código interno da agência. Ajuda a identificar reuso de fotos e orçamentos entre chamados da mesma agência."
              hint="Em branco: 0000.">
              <input name="branch_code" inputMode="numeric" placeholder="0418" className={field} />
            </Field>
            <Field className="md:col-span-2" label="Data de abertura" tip="Quando o chamado foi aberto." hint="Em branco: hoje.">
              <input type="date" name="opened_on" className={field} />
            </Field>
            <Field className="md:col-span-4" label="Fornecedor" tip="Razão social de quem executa o serviço. Ajuda a comparar chamados do mesmo fornecedor."
              hint="Em branco: fica como fornecedor não informado.">
              <input name="supplier_name" placeholder="Razão social" className={field} />
            </Field>
          </Section>

          <Section n={4} title="Arquivos">
            <InfoBox id="novo-chamado-planilha-itens" tone="tip" className="md:col-span-6">
              Envie só os itens, com <b>Descrição, Unidade, LPU (Sim/Não), Quantidade e Valor unitário</b>. Os totais são calculados automaticamente.
            </InfoBox>
            <div className="rounded-xl border border-dashed border-line p-4 md:col-span-6">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 font-medium">
                  Orçamento (planilha Excel com os itens) <span className="text-bad" aria-hidden>*</span><span className="sr-only">(obrigatório)</span>
                  <InfoTip text="Arquivo .xlsx ou .xlsm com os itens do orçamento (descrição, unidade, LPU, quantidade e valor unitário). LPU: Sim se o item está na tabela de preços, Não se é fora dela; em branco conta como Sim. O Atest.AI calcula o total de cada item e o valor do orçamento." label="Ajuda: planilha de orçamento" size={13} />
                </span>
                <a href="/api/spreadsheet-template" download="modelo_orcamento_atest.xlsx" className="flex items-center gap-1.5 text-blueprint hover:underline"
                  title="Planilha com as colunas Descrição, Unidade, Quantidade e Valor unitário">
                  <FileSpreadsheet size={15} /> Baixar modelo da planilha
                </a>
              </div>
              <input type="file" accept=".xlsx,.xlsm" required aria-label="Planilha de orçamento" onChange={(e) => setSpreadsheet(e.target.files?.[0] ?? null)} className={fileInput} />
            </div>
            <div className="rounded-xl border border-dashed border-line p-4 md:col-span-6">
              <span className="flex items-center gap-1.5 font-medium">
                Fotos e documentos <span className="text-[12px] font-normal text-muted">opcional · JPG, PNG, WEBP ou PDF</span>
                <InfoTip text="Fotos do antes/depois e documentos de apoio. Sem fotos, a análise não consegue confirmar os itens do orçamento." label="Ajuda: fotos e documentos" size={13} />
              </span>
              <input type="file" multiple accept=".jpg,.jpeg,.png,.webp,.pdf" aria-label="Fotos e documentos" onChange={(e) => setAttachments([...(e.target.files ?? [])])} className={fileInput} />
              {attachments.length > 0 && (
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {attachments.map((f) => (
                    <li key={f.name} className="flex items-center gap-1 rounded-full bg-paper px-2 py-0.5 text-[12px] text-muted"><Paperclip size={12} />{f.name}</li>
                  ))}
                </ul>
              )}
            </div>
          </Section>
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-line px-6 py-4">
          <span role="alert" className="text-sm text-bad">{error}</span>
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
