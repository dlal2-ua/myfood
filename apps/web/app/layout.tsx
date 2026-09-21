import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { ConsentGate } from "@/components/ConsentGate";
import { LocalNotificationsSync } from "@/components/LocalNotificationsSync";
import { CurrentUserProvider } from "@/components/CurrentUser";
import { ServiceWorkerRegister } from "@/components/ServiceWorkerRegister";
import { AppShell } from "@/components/shell/AppShell";
import { getCurrentUser } from "@/lib/session";
import { THEME_COLORS, THEME_INIT_SCRIPT } from "@/lib/theme";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: "MyFood",
  description: "Nutrición, dieta y suplementación autohospedada.",
  manifest: "/manifest.json",
  icons: {
    icon: "/icon-192.png",
    apple: "/icon-192.png",
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: THEME_COLORS.light },
    { media: "(prefers-color-scheme: dark)", color: THEME_COLORS.dark },
  ],
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const user = await getCurrentUser();

  return (
    // `data-theme` lo fija el script de <head> antes de pintar, de ahí el suppressHydrationWarning.
    <html lang="es" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className={`${inter.variable} min-h-screen antialiased`}>
        <a
          href="#contenido"
          className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-[60] focus:rounded-full focus:bg-[var(--color-primary)] focus:px-4 focus:py-2 focus:text-[var(--color-on-primary)]"
        >
          Saltar al contenido
        </a>
        <ServiceWorkerRegister />
        <LocalNotificationsSync authenticated={user != null} />
        <CurrentUserProvider userId={user?.id ?? null}>
          <ConsentGate pending={user?.pending_consents ?? []} />
          <AppShell user={user}>{children}</AppShell>
        </CurrentUserProvider>
      </body>
    </html>
  );
}
