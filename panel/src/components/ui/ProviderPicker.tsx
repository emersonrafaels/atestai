import type { AppSettings, ProviderChoice } from "../../api";
import { Tooltip } from "./Tooltip";

const KEY = "atest.provider";

/** Provedores do seletor (config/settings.toml: [panel.providers]); o primeiro é o da configuração. */
export const providerChoices = (c: AppSettings | null): ProviderChoice[] => c?.provider_choices ?? [];

export const findChoice = (c: AppSettings | null, id: string) => providerChoices(c).find((p) => p.id === id) ?? null;

/** Provedor inicial: o último escolhido neste navegador (se ainda tem credencial), senão o da configuração, senão o primeiro com credencial. */
export function initialProvider(c: AppSettings): string {
  const choices = providerChoices(c);
  let saved: string | null = null;
  try { saved = localStorage.getItem(KEY); } catch { /* armazenamento indisponível */ }
  const pick = choices.find((p) => p.id === saved && p.available) ?? (choices[0]?.available ? choices[0] : choices.find((p) => p.available)) ?? choices[0];
  return pick?.id ?? "";
}

export function rememberProvider(id: string) {
  try { localStorage.setItem(KEY, id); } catch { /* armazenamento indisponível */ }
}

/** Modelo sem "provedor:" ganha o prefixo do provedor escolhido (o servidor usaria o provedor padrão da configuração). */
export const withProvider = (model: string, provider: string) => (!model || model.includes(":") || !provider ? model : `${provider}:${model}`);

/** Botões de escolha do provedor; os sem credencial ficam desabilitados com a explicação no tooltip. */
export function ProviderPicker({ config, value, onChange, disabled }: { config: AppSettings; value: string; onChange: (id: string) => void; disabled?: boolean }) {
  const choices = providerChoices(config);
  return (
    <div role="radiogroup" aria-label="Provedor de LLM" className="flex rounded-lg border border-line bg-sheet p-0.5">
      {choices.map((p) => (
        <Tooltip key={p.id} side="bottom"
          content={p.available
            ? <>Modelos: <b>{p.main.split(":").slice(1).join(":")}</b> (principal) e <b>{p.fast.split(":").slice(1).join(":")}</b> (rápido)</>
            : `Sem credencial: defina ${p.credentials.join(" e ") || "a chave"} em config/.secrets.toml ou no ambiente`}>
          <button type="button" role="radio" aria-checked={value === p.id} disabled={disabled || !p.available}
            onClick={() => { rememberProvider(p.id); onChange(p.id); }}
            className={`whitespace-nowrap rounded-md px-3 py-1 transition-colors ${value === p.id ? "bg-blueprint-soft font-semibold text-blueprint shadow-sm" : "text-muted hover:text-ink"} disabled:pointer-events-none disabled:opacity-40`}>
            {p.label}
          </button>
        </Tooltip>
      ))}
    </div>
  );
}
