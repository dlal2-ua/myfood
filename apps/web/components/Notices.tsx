"use client";

import { ChevronDown, TriangleAlert } from "lucide-react";
import { createContext, useCallback, useContext, useId, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";

interface NoticePrefs {
  collapsed: ReadonlySet<string>;
  toggle: (id: string) => void;
}

const NoticePrefsContext = createContext<NoticePrefs | null>(null);

/** Qué avisos tiene plegados el usuario. Llega con la sesión (`/auth/me`) para que la primera
 * pantalla ya salga con ellos plegados, y cada cambio se guarda en su cuenta: al volver a
 * entrar, en este dispositivo o en otro, siguen como los dejó. */
export function NoticePrefsProvider({
  initial,
  children,
}: {
  initial: string[];
  children: React.ReactNode;
}) {
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set(initial));

  const toggle = useCallback((id: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      // Sin esperar la respuesta: plegar un aviso no puede depender de la red. Si falla,
      // lo peor que pasa es que la próxima vez salga desplegado.
      apiFetch("/api/profile/ui-prefs", {
        method: "PUT",
        body: JSON.stringify({ collapsed_notices: [...next] }),
      }).catch(() => {});
      return next;
    });
  }, []);

  const value = useMemo(() => ({ collapsed, toggle }), [collapsed, toggle]);
  return <NoticePrefsContext.Provider value={value}>{children}</NoticePrefsContext.Provider>;
}

/** Un aviso fijo (el de «no es consejo médico», el de «estimación orientativa»…) que se
 * puede dejar en una línea. Plegado sigue a la vista con su título: no desaparece, solo
 * deja de ocupar media pantalla en un móvil.
 *
 * `id` identifica el aviso en las preferencias del usuario: minúsculas, cifras y guiones. */
export function CollapsibleNotice({
  id,
  title,
  children,
  className = "",
}: {
  id: string;
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  const prefs = useContext(NoticePrefsContext);
  // Sin sesión (o en un test) no hay dónde guardarlo: el plegado vive lo que la pantalla.
  const [localCollapsed, setLocalCollapsed] = useState(false);
  const collapsed = prefs ? prefs.collapsed.has(id) : localCollapsed;
  const bodyId = useId();

  return (
    <div
      role="note"
      className={`rounded-lg border border-amber-300 bg-amber-50 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200 ${className}`}
    >
      <button
        type="button"
        aria-expanded={!collapsed}
        aria-controls={bodyId}
        onClick={() => (prefs ? prefs.toggle(id) : setLocalCollapsed((value) => !value))}
        className="flex min-h-9 w-full items-center gap-2 px-3 py-2 text-left font-semibold"
      >
        <TriangleAlert size={13} aria-hidden="true" className="shrink-0" />
        <span className="min-w-0 flex-1">{title}</span>
        <span className="sr-only">{collapsed ? "Desplegar el aviso" : "Plegar el aviso"}</span>
        <ChevronDown
          size={14}
          aria-hidden="true"
          className={`shrink-0 transition-transform ${collapsed ? "" : "rotate-180"}`}
        />
      </button>
      {!collapsed && (
        <div id={bodyId} className="px-3 pb-3">
          {children}
        </div>
      )}
    </div>
  );
}
