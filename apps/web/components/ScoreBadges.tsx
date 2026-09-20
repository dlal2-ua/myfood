/** Badges de Open Food Facts: Nutri-Score (A–E), NOVA (1–4) y Eco-Score (A–E). Solo se
 * pintan los que tienen dato — nunca se inventa una nota (R9). Son la escala oficial de
 * cada sistema, sobre la calidad del PRODUCTO, no sobre cuánto has comido (R10). */

const NUTRISCORE_COLORS: Record<string, string> = {
  a: "#038141",
  b: "#85bb2f",
  c: "#fecb02",
  d: "#ee8100",
  e: "#e63e11",
};
const ECOSCORE_COLORS: Record<string, string> = {
  a: "#1e8f4e",
  b: "#60ac0e",
  c: "#eeae0e",
  d: "#ff6f1e",
  e: "#df1f1f",
};
const NOVA_COLORS: Record<number, string> = {
  1: "#038141",
  2: "#85bb2f",
  3: "#ee8100",
  4: "#e63e11",
};
const NOVA_LABELS: Record<number, string> = {
  1: "Sin procesar o mínimamente procesado",
  2: "Ingrediente culinario procesado",
  3: "Alimento procesado",
  4: "Ultraprocesado",
};

function Badge({
  label,
  value,
  color,
  title,
  dark = false,
}: {
  label: string;
  value: string;
  color: string;
  title: string;
  dark?: boolean;
}) {
  return (
    <span
      title={title}
      className="inline-flex items-center overflow-hidden rounded text-[10px] font-semibold leading-none"
    >
      <span className="bg-neutral-200 px-1 py-0.5 text-neutral-700 dark:bg-neutral-700 dark:text-neutral-200">
        {label}
      </span>
      <span
        className="px-1.5 py-0.5"
        style={{ backgroundColor: color, color: dark ? "#1c1917" : "#ffffff" }}
      >
        {value}
      </span>
    </span>
  );
}

export function ScoreBadges({
  nutriscore,
  nova,
  ecoscore,
}: {
  nutriscore?: string | null;
  nova?: number | null;
  ecoscore?: string | null;
}) {
  const n = nutriscore?.toLowerCase();
  const e = ecoscore?.toLowerCase();
  if (!(n && NUTRISCORE_COLORS[n]) && !(nova && NOVA_COLORS[nova]) && !(e && ECOSCORE_COLORS[e])) {
    return null;
  }
  return (
    <span className="flex flex-wrap items-center gap-1">
      {n && NUTRISCORE_COLORS[n] && (
        <Badge
          label="Nutri-Score"
          value={n.toUpperCase()}
          color={NUTRISCORE_COLORS[n]}
          title={`Nutri-Score ${n.toUpperCase()} (calidad nutricional, de A a E)`}
          dark={n === "c"}
        />
      )}
      {nova && NOVA_COLORS[nova] && (
        <Badge
          label="NOVA"
          value={String(nova)}
          color={NOVA_COLORS[nova]}
          title={`NOVA ${nova}: ${NOVA_LABELS[nova]}`}
        />
      )}
      {e && ECOSCORE_COLORS[e] && (
        <Badge
          label="Eco-Score"
          value={e.toUpperCase()}
          color={ECOSCORE_COLORS[e]}
          title={`Eco-Score ${e.toUpperCase()} (impacto ambiental, de A a E)`}
          dark={e === "c"}
        />
      )}
    </span>
  );
}
