import type { Metadata, Viewport } from "next";
import "./globals.css";
import { LocalNotificationsSync } from "@/components/LocalNotificationsSync";
import { NavBar } from "@/components/NavBar";
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
        <NavBar user={user} />
        <div className="mx-auto max-w-3xl px-4 py-6">{children}</div>
      </body>
    </html>
  );
}
