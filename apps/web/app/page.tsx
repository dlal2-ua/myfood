import { CalendarDays, Lock, ScanBarcode, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { TodayDashboard } from "@/components/TodayDashboard";
import { Ring } from "@/components/ui/Ring";
import { getCurrentUser } from "@/lib/session";

const FEATURES = [
  {
    icon: ScanBarcode,
    tint: "var(--tint-mint)",
    title: "Registra en segundos",
    text: "Escanea el código de barras, busca en el catálogo o cuéntalo con tus palabras. Sin pesar cada cosa dos veces.",
  },
  {
    icon: CalendarDays,
    tint: "var(--tint-lime)",
    title: "Planes que cuadran",
    text: "Menús con tus calorías y macros exactos, y alternativas del mismo tipo de alimento con los gramos ya ajustados.",
  },
  {
    icon: ShieldCheck,
    tint: "var(--tint-sky)",
    title: "Datos de verdad",
    text: "BEDCA, CIQUAL, USDA y Open Food Facts, con Nutri-Score, NOVA y Eco-Score. La IA nunca inventa una caloría.",
  },
  {
    icon: Lock,
    tint: "var(--tint-lilac)",
    title: "Tuyo y privado",
    text: "Está en tu propio servidor. Exporta todo o borra tu cuenta cuando quieras, sin letra pequeña.",
  },
];

function Landing() {
  const cta =
    "inline-flex min-h-13 items-center justify-center rounded-full px-7 text-base font-bold transition-colors";
  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-16 px-4 pb-20 pt-6 sm:pt-12">
      <section className="grid items-center gap-10 md:grid-cols-[1.15fr_1fr]">
        <div className="flex flex-col items-start gap-6">
          <span className="rounded-full bg-[var(--color-primary-soft)] px-3.5 py-1.5 text-xs font-bold text-[var(--color-primary)]">
            Nutrición autoalojada
          </span>
          <h1 className="text-[2.6rem] font-extrabold leading-[1.05] tracking-tight sm:text-6xl">
            Come mejor, <span className="text-[var(--color-primary)]">sin complicarte.</span>
          </h1>
          <p className="max-w-xl text-lg leading-relaxed text-[var(--color-muted)]">
            Registra lo que comes, ajusta tu dieta a tus objetivos y sigue tu progreso. Los números
            los calcula el sistema con datos oficiales.
          </p>
          <div className="flex flex-wrap gap-3">
            <Link
              href="/register"
              className={`${cta} bg-[var(--color-primary)] text-[var(--color-on-primary)] shadow-md hover:bg-[var(--color-primary-hover)]`}
            >
              Empezar gratis
            </Link>
            <Link
              href="/login"
              className={`${cta} bg-[var(--color-primary-soft)] text-[var(--color-primary)] hover:brightness-95`}
            >
              Ya tengo cuenta
            </Link>
          </div>
        </div>

        <div
          aria-hidden="true"
          className="relative mx-auto w-full max-w-sm rounded-[32px] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-[var(--shadow-card)]"
        >
          <div className="mb-4 flex items-center justify-between">
            <span className="text-sm font-bold">Hoy</span>
            <span className="rounded-full bg-[var(--color-surface-2)] px-2.5 py-1 text-[11px] font-semibold text-[var(--color-muted)]">
              Ejemplo
            </span>
          </div>
          <div className="flex items-center justify-between gap-4">
            <Ring value={1420} target={2100} color="var(--color-primary)" label="Energía" unit="kcal" size={116} />
            <div className="flex flex-1 flex-col gap-2.5 text-xs font-semibold">
              {[
                ["Proteína", 78, 120, "var(--color-protein)"],
                ["Carbohidratos", 160, 230, "var(--color-carbs)"],
                ["Grasa", 44, 70, "var(--color-fat)"],
              ].map(([name, v, t, color]) => (
                <div key={name as string}>
                  <div className="mb-1 flex justify-between">
                    <span>{name}</span>
                    <span className="text-[var(--color-muted)]">
                      {v} / {t} g
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-[var(--color-surface-2)]">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${Math.round(((v as number) / (t as number)) * 100)}%`, background: color as string }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="mt-5 grid grid-cols-2 gap-2 text-xs font-semibold">
            <span className="rounded-2xl bg-[var(--tint-mint)] px-3 py-2.5">Desayuno · 420 kcal</span>
            <span className="rounded-2xl bg-[var(--tint-lime)] px-3 py-2.5">Comida · 780 kcal</span>
          </div>
        </div>
      </section>

      <section aria-labelledby="que-hace" className="flex flex-col gap-6">
        <h2 id="que-hace" className="max-w-xl text-3xl font-extrabold tracking-tight sm:text-4xl">
          Llevar la cuenta, <span className="text-[var(--color-primary)]">hecho fácil</span>
        </h2>
        <ul className="grid gap-4 sm:grid-cols-2">
          {FEATURES.map(({ icon: Icon, tint, title, text }) => (
            <li key={title} className="rounded-[var(--radius-card)] p-6" style={{ background: tint }}>
              <span className="mb-4 grid h-12 w-12 place-items-center rounded-2xl bg-[var(--color-surface)] text-[var(--color-primary)] shadow-sm">
                <Icon size={24} aria-hidden="true" />
              </span>
              <h3 className="text-xl font-extrabold tracking-tight">{title}</h3>
              <p className="mt-1.5 text-[15px] leading-relaxed text-[var(--color-muted)]">{text}</p>
            </li>
          ))}
        </ul>
      </section>

      <p className="text-center text-xs text-[var(--color-muted)]">
        MyFood no da consejo médico: los cálculos y los planes son orientativos. Consulta con un
        profesional sanitario antes de hacer cambios relevantes en tu alimentación.
      </p>
    </main>
  );
}

export default async function HomePage() {
  const user = await getCurrentUser();
  if (!user) return <Landing />;
  return (
    <main>
      <TodayDashboard displayName={user.display_name} />
    </main>
  );
}
