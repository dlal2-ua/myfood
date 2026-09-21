"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import {
  THEME_CHANGED_EVENT,
  applyTheme,
  readThemePreference,
  saveThemePreference,
  type ResolvedTheme,
  type ThemePreference,
} from "@/lib/theme";

const OPTIONS: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
  { value: "system", label: "Sistema", icon: Monitor },
  { value: "light", label: "Claro", icon: Sun },
  { value: "dark", label: "Oscuro", icon: Moon },
];

function useTheme() {
  // Se lee tras montar: en el servidor no hay localStorage ni matchMedia y así la hidratación coincide.
  const [preference, setPreference] = useState<ThemePreference>("system");
  const [resolved, setResolved] = useState<ResolvedTheme>("light");

  useEffect(() => {
    const current = readThemePreference();
    setPreference(current);
    setResolved(applyTheme(current));
    const media =
      typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
    const onSystemChange = () => {
      if (readThemePreference() === "system") setResolved(applyTheme("system"));
    };
    // Otro selector de tema montado a la vez (p. ej. el icono y el menú) avisa con este evento.
    const onOtherChange = () => {
      const now = readThemePreference();
      setPreference(now);
      setResolved(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
    };
    media?.addEventListener("change", onSystemChange);
    window.addEventListener(THEME_CHANGED_EVENT, onOtherChange);
    return () => {
      media?.removeEventListener("change", onSystemChange);
      window.removeEventListener(THEME_CHANGED_EVENT, onOtherChange);
    };
  }, []);

  function choose(next: ThemePreference) {
    saveThemePreference(next); // avisa por evento: este mismo hook actualiza su estado
  }
  return { preference, resolved, choose };
}

/** Selector de tres opciones: seguir al sistema, claro u oscuro. */
export function ThemeSegmented() {
  const { preference, choose } = useTheme();
  return (
    <div role="radiogroup" aria-label="Apariencia" className="grid grid-cols-3 gap-1 rounded-full bg-[var(--color-surface-2)] p-1">
      {OPTIONS.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={preference === value}
          onClick={() => choose(value)}
          className={`flex min-h-9 items-center justify-center gap-1.5 rounded-full px-2 text-xs font-medium transition-colors ${
            preference === value
              ? "bg-[var(--color-primary)] text-[var(--color-on-primary)] shadow-sm"
              : "text-[var(--color-muted)] hover:text-[var(--color-text)]"
          }`}
        >
          <Icon size={14} aria-hidden="true" />
          {label}
        </button>
      ))}
    </div>
  );
}

/** Botón de un toque: alterna entre claro y oscuro (lo deja explícito, no «sistema»). */
export function ThemeIconButton({ className = "" }: { className?: string }) {
  const { resolved, choose } = useTheme();
  const isDark = resolved === "dark";
  return (
    <button
      type="button"
      onClick={() => choose(isDark ? "light" : "dark")}
      aria-label={isDark ? "Cambiar a tema claro" : "Cambiar a tema oscuro"}
      className={`grid h-10 w-10 place-items-center rounded-full text-[var(--color-muted)] transition-colors hover:bg-[var(--color-surface-2)] hover:text-[var(--color-text)] ${className}`}
    >
      {isDark ? <Sun size={20} aria-hidden="true" /> : <Moon size={20} aria-hidden="true" />}
    </button>
  );
}
