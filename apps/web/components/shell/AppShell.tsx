"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Logo } from "@/components/Logo";
import { OfflineSync } from "@/components/OfflineSync";
import { ThemeIconButton } from "@/components/ThemeToggle";
import { AccountMenu } from "@/components/shell/AccountMenu";
import { BottomNav } from "@/components/shell/BottomNav";
import { QuickAddSheet } from "@/components/shell/QuickAddSheet";
import { Sidebar } from "@/components/shell/Sidebar";
import type { CurrentUser } from "@/lib/session";

const NOTICE_MS = 4000;

/** Estructura de la app. Con sesión: barra lateral en escritorio, barra superior y barra inferior
 * con el botón «+» en el móvil. Sin sesión: solo una cabecera con «Entrar» y «Crear cuenta». */
export function AppShell({ user, children }: { user: CurrentUser | null; children: React.ReactNode }) {
  const [quickOpen, setQuickOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);

  function showNotice(message: string) {
    setNotice(message);
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setNotice(null), NOTICE_MS);
  }

  if (!user) {
    return (
      <div className="hero-glow min-h-screen">
        <header className="mx-auto flex max-w-5xl items-center justify-between gap-2 px-4 py-4">
          <Link href="/" aria-label="MyFood, inicio">
            <Logo />
          </Link>
          <div className="flex items-center gap-1 text-sm font-semibold">
            <ThemeIconButton />
            <Link
              href="/login"
              className="inline-flex min-h-10 items-center whitespace-nowrap rounded-full px-3 hover:bg-[var(--color-surface-2)] sm:px-4"
            >
              Entrar
            </Link>
            <Link
              href="/register"
              className="inline-flex min-h-10 items-center whitespace-nowrap rounded-full bg-[var(--color-primary)] px-3.5 text-[var(--color-on-primary)] hover:bg-[var(--color-primary-hover)] sm:px-4"
            >
              Crear cuenta
            </Link>
          </div>
        </header>
        <div id="contenido">{children}</div>
      </div>
    );
  }

  return (
    <>
      <Sidebar user={user} onQuickAdd={() => setQuickOpen(true)} />

      <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-[var(--color-border)] bg-[var(--color-surface)]/95 px-4 py-2 pt-[max(0.5rem,env(safe-area-inset-top))] backdrop-blur md:hidden">
        <Link href="/" aria-label="MyFood, ir a Hoy">
          <Logo size={32} />
        </Link>
        <div className="flex items-center gap-1">
          <ThemeIconButton />
          <AccountMenu user={user} />
        </div>
      </header>

      <div className="md:pl-64">
        <OfflineSync userId={user.id} />
        <div
          id="contenido"
          className="mx-auto max-w-4xl px-4 pb-[calc(var(--nav-height)+2.5rem+env(safe-area-inset-bottom))] pt-5 md:px-8 md:pb-12 md:pt-8"
        >
          {children}
        </div>
      </div>

      <BottomNav onQuickAdd={() => setQuickOpen(true)} />
      <QuickAddSheet open={quickOpen} onClose={() => setQuickOpen(false)} onNotice={showNotice} />

      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-[calc(var(--nav-height)+1.5rem+env(safe-area-inset-bottom))] z-50 flex justify-center px-4 md:bottom-6"
      >
        {notice && (
          <p className="pointer-events-auto max-w-sm rounded-full bg-[var(--color-text)] px-4 py-2.5 text-sm font-medium text-[var(--color-bg)] shadow-lg">
            {notice}
          </p>
        )}
      </div>
    </>
  );
}
