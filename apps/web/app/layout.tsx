import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ConsentGate } from "@/components/ConsentGate";
import { LocalNotificationsSync } from "@/components/LocalNotificationsSync";
import { CurrentUserProvider } from "@/components/CurrentUser";
import { NavBar } from "@/components/NavBar";
import { OfflineSync } from "@/components/OfflineSync";
import { ServiceWorkerRegister } from "@/components/ServiceWorkerRegister";
import { getCurrentUser } from "@/lib/session";

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
  themeColor: "#16a34a",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const user = await getCurrentUser();

  return (
    <html lang="es">
      <body className="min-h-screen antialiased">
        <ServiceWorkerRegister />
        <LocalNotificationsSync authenticated={user != null} />
        <CurrentUserProvider userId={user?.id ?? null}>
          <NavBar user={user} />
          <OfflineSync userId={user?.id ?? null} />
          <ConsentGate pending={user?.pending_consents ?? []} />
          <div className="mx-auto max-w-3xl px-4 py-6">{children}</div>
        </CurrentUserProvider>
      </body>
    </html>
  );
}
