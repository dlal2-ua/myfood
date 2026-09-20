import Link from "next/link";
import { TodayDashboard } from "@/components/TodayDashboard";
import { getCurrentUser } from "@/lib/session";

export default async function HomePage() {
  const user = await getCurrentUser();

  if (!user) {
    return (
      <main className="flex flex-col items-center gap-4 py-16 text-center">
        <h1 className="text-2xl font-semibold">MyFood</h1>
        <p className="text-sm text-neutral-500">Nutrición, dieta y suplementación autohospedada.</p>
        <Link href="/login" className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-white">
          Iniciar sesión
        </Link>
      </main>
    );
  }

  return (
    <main className="py-6">
      <TodayDashboard displayName={user.display_name} />
    </main>
  );
}
