import Link from "next/link";
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
    <main className="flex flex-col gap-6 py-8">
      <div>
        <h1 className="text-2xl font-semibold">Hola, {user.display_name}</h1>
        <p className="text-sm text-neutral-500">{user.email}</p>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Link
          href="/profile"
          className="rounded-lg border border-neutral-200 p-4 hover:border-[var(--color-primary)] dark:border-neutral-800"
        >
          <h2 className="font-medium">Perfil y cálculos</h2>
          <p className="text-sm text-neutral-500">
            Datos personales, medidas y objetivos calóricos.
          </p>
        </Link>
        <Link
          href="/foods"
          className="rounded-lg border border-neutral-200 p-4 hover:border-[var(--color-primary)] dark:border-neutral-800"
        >
          <h2 className="font-medium">Alimentos</h2>
          <p className="text-sm text-neutral-500">Busca alimentos y consulta su información nutricional.</p>
        </Link>
        <Link
          href="/log"
          className="rounded-lg border border-neutral-200 p-4 hover:border-[var(--color-primary)] dark:border-neutral-800"
        >
          <h2 className="font-medium">Registro diario</h2>
          <p className="text-sm text-neutral-500">Registra tus comidas y revisa los totales del día.</p>
        </Link>
      </div>
    </main>
  );
}
