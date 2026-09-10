import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MyFood",
  description: "Nutrición, dieta y suplementación autohospedada.",
  manifest: "/manifest.json",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
