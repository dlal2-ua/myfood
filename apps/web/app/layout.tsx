import type { Metadata } from "next";
import "./globals.css";
import { NavBar } from "@/components/NavBar";
import { getCurrentUser } from "@/lib/session";

export const metadata: Metadata = {
  title: "MyFood",
  description: "Nutrición, dieta y suplementación autohospedada.",
  manifest: "/manifest.json",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const user = await getCurrentUser();

  return (
    <html lang="es">
      <body className="min-h-screen antialiased">
        <NavBar user={user} />
        <div className="mx-auto max-w-3xl px-4 py-6">{children}</div>
      </body>
    </html>
  );
}
