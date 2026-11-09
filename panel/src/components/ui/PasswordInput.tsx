import { Eye, EyeOff } from "lucide-react";
import { useState, type InputHTMLAttributes } from "react";

/**
 * Campo de senha com botão de mostrar/ocultar e aviso de Caps Lock.
 * A senha volta a ficar oculta quando o campo perde o foco, para não ficar exposta na tela.
 */
export function PasswordInput({ className = "", onBlur, onKeyUp, ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  const [visible, setVisible] = useState(false);
  const [caps, setCaps] = useState(false);
  return (
    <div>
      <div className="relative">
        <input {...props} type={visible ? "text" : "password"} spellCheck={false} autoCapitalize="off" autoCorrect="off"
          onKeyUp={(e) => { setCaps(e.getModifierState?.("CapsLock") ?? false); onKeyUp?.(e); }}
          onBlur={(e) => { setVisible(false); setCaps(false); onBlur?.(e); }}
          className={`${className} pr-10`} />
        <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => setVisible((v) => !v)}
          aria-label={visible ? "Ocultar senha" : "Mostrar senha"} aria-pressed={visible} title={visible ? "Ocultar senha" : "Mostrar senha"}
          className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-lg text-muted hover:text-ink focus-visible:text-blueprint">
          {visible ? <EyeOff size={17} /> : <Eye size={17} />}
        </button>
      </div>
      {caps && <p className="mt-1 text-[12px] font-medium text-warn">Caps Lock está ativado.</p>}
    </div>
  );
}
