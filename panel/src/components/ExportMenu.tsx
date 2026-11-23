import { ChevronDown, Download, FileCode2, FileJson, FileText, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Assessment, TicketDetail } from "../api";
import { buildReport, download } from "../export/report";
import { downloadPdf } from "../export/pdf";

/**
 * Exportar o chamado e o parecer: arquivo PDF ou relatório HTML (os dois com as fotos e os documentos em imagem) ou o
 * JSON completo (auditoria e integração).
 */
export function ExportMenu({ p, ticket }: { p: Assessment; ticket: TicketDetail | null }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<"html" | "pdf" | null>(null);
  const [error, setError] = useState("");
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !root.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("keydown", close); };
  }, [open]);

  const html = async () => {
    setBusy("html"); setError("");
    try {
      download(await buildReport(p, ticket), `parecer_${p.ticket_id}.html`, "text/html;charset=utf-8");
      setOpen(false);
    } catch { setError("Não foi possível gerar o relatório."); } finally { setBusy(null); }
  };

  const pdf = async () => {
    setBusy("pdf"); setError("");
    try {
      await downloadPdf(p, ticket);
      setOpen(false);
    } catch { setError("Não foi possível gerar o PDF."); } finally { setBusy(null); }
  };

  const json = () => {
    download(JSON.stringify(p, null, 2), `parecer_${p.ticket_id}.json`, "application/json");
    setOpen(false);
  };

  const item = "flex w-full items-start gap-2.5 rounded-md px-2.5 py-2 text-left hover:bg-paper disabled:opacity-60";
  return (
    <div ref={root} className="relative shrink-0">
      <button onClick={() => setOpen(!open)} aria-haspopup="menu" aria-expanded={open}
        className={`flex items-center gap-1.5 whitespace-nowrap rounded-lg border bg-sheet px-3 py-1.5 text-sm font-medium shadow-sm transition-colors ${open ? "border-blueprint text-blueprint" : "border-line text-ink hover:border-blueprint hover:text-blueprint"}`}>
        {busy ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />} Exportar parecer <ChevronDown size={13} className={`transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 top-full z-30 mt-1 w-72 rounded-lg border border-line bg-sheet p-1.5 text-sm shadow-lg">
          <button role="menuitem" onClick={pdf} disabled={!!busy} className={item}>
            <FileText size={16} className="mt-0.5 shrink-0 text-bad" />
            <span><b className="block font-medium">PDF</b><span className="text-[12px] text-muted">Baixa o arquivo com o chamado, o parecer, as fotos e os documentos.</span></span>
          </button>
          <button role="menuitem" onClick={html} disabled={!!busy} className={item}>
            <FileCode2 size={16} className="mt-0.5 shrink-0 text-blueprint" />
            <span><b className="block font-medium">HTML</b><span className="text-[12px] text-muted">O mesmo relatório numa página que abre em qualquer navegador.</span></span>
          </button>
          <button role="menuitem" onClick={json} className={item}>
            <FileJson size={16} className="mt-0.5 shrink-0 text-muted" />
            <span><b className="block font-medium">JSON</b><span className="text-[12px] text-muted">O parecer completo, para auditoria ou integração.</span></span>
          </button>
          {error && <p className="px-2.5 py-1.5 text-[12px] text-bad">{error}</p>}
        </div>
      )}
    </div>
  );
}
