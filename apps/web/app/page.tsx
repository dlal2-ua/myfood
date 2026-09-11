import Link from "next/link";
import { cookies } from "next/headers";

async function getCurrentUser() {
  const cookieStore = await cookies();
  const session = cookieStore.get("myfood_session");
  if (!session) return null;

  const res = await fetch("http://api:8000/api/auth/me", {
    headers: { cookie: `myfood_session=${session.value}` },
    cache: "no-store",
  });
  if (!res.ok) return null;
  return res.json();
}

export default async function HomePage() {
  const user = await getCurrentUser();

  if (!user) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">
        <h1 className="text-2xl font-semibold">MyFood</h1>
        <p className="text-sm text-neutral-500">Nutrición, dieta y suplementación autohospedada.</p>
        <Link
          href="/login"
          className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-white"
        >
          Iniciar sesión
        </Link>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-2 p-8">
      <h1 className="text-2xl font-semibold">Hola, {user.display_name}</h1>
      <p className="text-sm text-neutral-500">{user.email}</p>
    </main>
  );
}
