"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { BOTTOM_TABS, tabForPath, type BottomTab } from "@/lib/nav";

function Tab({ tab, active }: { tab: BottomTab; active: boolean }) {
  const Icon = tab.icon;
  return (
    <li>
      <Link
        href={tab.href}
        aria-current={active ? "page" : undefined}
        className={`flex min-h-[3.5rem] flex-col items-center justify-center gap-0.5 rounded-2xl text-[11px] font-semibold transition-colors ${
          active ? "text-[var(--color-primary)]" : "text-[var(--color-muted)] hover:text-[var(--color-text)]"
        }`}
      >
        <span
          className={`grid h-7 w-12 place-items-center rounded-full transition-colors ${
            active ? "bg-[var(--color-primary-soft)]" : ""
          }`}
        >
          <Icon size={22} strokeWidth={active ? 2.5 : 2} aria-hidden="true" />
        </span>
        {tab.label}
      </Link>
    </li>
  );
}

/** Barra inferior del móvil: cuatro destinos principales y, en el centro, el botón «+» de
 * acciones rápidas. En pantallas grandes la sustituye la barra lateral. */
export function BottomNav({ onQuickAdd }: { onQuickAdd: () => void }) {
  const pathname = usePathname();
  const current = tabForPath(pathname);
  const [today, log, foods, more] = BOTTOM_TABS;

  return (
    <nav
      aria-label="Navegación principal"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-[var(--color-border)] bg-[var(--color-surface)]/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
    >
      <ul className="mx-auto grid max-w-lg grid-cols-5 items-center px-1.5 pt-1.5">
        <Tab tab={today} active={current === today.key} />
        <Tab tab={log} active={current === log.key} />
        <li className="flex justify-center">
          <button
            type="button"
            onClick={onQuickAdd}
            aria-label="Añadir"
            aria-haspopup="dialog"
            className="-mt-7 grid h-14 w-14 place-items-center rounded-full bg-[var(--color-primary)] text-[var(--color-on-primary)] shadow-lg ring-4 ring-[var(--color-bg)] transition-transform active:scale-95"
          >
            <Plus size={28} strokeWidth={2.75} aria-hidden="true" />
          </button>
        </li>
        <Tab tab={foods} active={current === foods.key} />
        <Tab tab={more} active={current === more.key} />
      </ul>
    </nav>
  );
}
