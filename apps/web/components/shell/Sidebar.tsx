"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Logo } from "@/components/Logo";
import { AccountMenu } from "@/components/shell/AccountMenu";
import { HOME_ITEM, isActive, sidebarGroups } from "@/lib/nav";
import type { CurrentUser } from "@/lib/session";

/** Barra lateral de escritorio: todas las funciones a la vista, agrupadas por tarea. */
export function Sidebar({ user, onQuickAdd }: { user: CurrentUser; onQuickAdd: () => void }) {
  const pathname = usePathname();
  const groups = sidebarGroups(user.role === "admin");
  const HomeIcon = HOME_ITEM.icon;

  const link = (active: boolean) =>
    `flex min-h-9 items-center gap-3 rounded-xl px-3 text-sm font-medium transition-colors ${
      active
        ? "bg-[var(--color-primary-soft)] text-[var(--color-primary)]"
        : "text-[var(--color-muted)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-text)]"
    }`;

  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-[var(--color-border)] bg-[var(--color-surface)] md:flex">
      <div className="flex flex-col gap-4 px-4 pb-2 pt-5">
        <Link href="/" aria-label="MyFood, ir a Hoy">
          <Logo />
        </Link>
        <button
          type="button"
          onClick={onQuickAdd}
          aria-haspopup="dialog"
          className="flex min-h-11 items-center justify-center gap-2 rounded-full bg-[var(--color-primary)] px-4 text-sm font-bold text-[var(--color-on-primary)] shadow-sm transition-colors hover:bg-[var(--color-primary-hover)]"
        >
          <Plus size={18} strokeWidth={2.75} aria-hidden="true" /> Añadir
        </button>
      </div>

      <nav aria-label="Principal" className="flex-1 overflow-y-auto px-3 pb-4">
        <Link
          href={HOME_ITEM.href}
          aria-current={isActive(pathname, HOME_ITEM.href) ? "page" : undefined}
          className={`mt-2 ${link(isActive(pathname, HOME_ITEM.href))}`}
        >
          <HomeIcon size={18} aria-hidden="true" /> {HOME_ITEM.label}
        </Link>
        {groups.map((group) => (
          <div key={group.key} className="mt-3">
            <h2 className="px-3 pb-1 text-[11px] font-bold uppercase tracking-wider text-[var(--color-muted)]">
              {group.label}
            </h2>
            <ul className="flex flex-col gap-0.5">
              {group.items.map((item) => {
                const Icon = item.icon;
                const active = isActive(pathname, item.href);
                return (
                  <li key={item.href}>
                    <Link href={item.href} aria-current={active ? "page" : undefined} className={link(active)}>
                      <Icon size={18} aria-hidden="true" /> {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-[var(--color-border)] p-3">
        <AccountMenu user={user} placement="up" showName />
      </div>
    </aside>
  );
}
