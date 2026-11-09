/** Interruptor liga/desliga acessível (role="switch"). */
export function Switch({ on, onChange, label, size = "md", disabled }: { on: boolean; onChange: (v: boolean) => void; label: string; size?: "sm" | "md"; disabled?: boolean }) {
  const w = size === "sm" ? "h-4 w-7" : "h-5 w-9";
  const k = size === "sm" ? "size-3" : "size-4";
  const shift = size === "sm" ? "translate-x-3" : "translate-x-4";
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)}
      className={`relative inline-flex shrink-0 items-center rounded-full p-0.5 transition-colors disabled:opacity-40 ${w} ${on ? "bg-ok" : "bg-line"}`}>
      <span className={`${k} rounded-full bg-white shadow transition-transform ${on ? shift : "translate-x-0"}`} />
    </button>
  );
}
