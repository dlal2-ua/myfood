"use client";

import { PartyPopper, X } from "lucide-react";
import { useEffect, useState } from "react";
import { AchievementBadge, tierLabel } from "@/components/AchievementBadge";
import type { Achievement } from "@/lib/types";

/** Cuántas insignias se nombran en la celebración. Al entrar por primera vez con historial
 * se consiguen muchas de golpe, y la lista entera empujaba la pantalla hacia abajo. */
const CELEBRATION_MAX = 3;

const FAMILY_TITLES: Record<string, string> = {
  logging: "Constancia",
  streak: "Rachas",
  water: "Agua",
  variety: "Variedad",
  recipes: "Cocina",
  complete: "Días completos",
};

function groupByFamily(achievements: Achievement[]): [string, Achievement[]][] {
  const groups = new Map<string, Achievement[]>();
  for (const a of achievements) {
    groups.set(a.family, [...(groups.get(a.family) ?? []), a]);
  }
  return [...groups.entries()];
}

function AchievementCard({ achievement }: { achievement: Achievement }) {
  const pct = achievement.target > 0 ? (achievement.progress / achievement.target) * 100 : 0;
  return (
    <li
      className={`flex items-center gap-3 rounded-[var(--radius-card)] border p-3 ${
        achievement.earned
          ? "border-[var(--color-primary)] bg-[var(--color-primary-soft)]"
          : "border-[var(--color-border)] bg-[var(--color-surface)]"
      }`}
    >
      <AchievementBadge achievement={achievement} size={56} />
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-x-2 text-sm font-bold">
          {achievement.title}
          <span className="text-[11px] font-semibold text-[var(--color-muted)]">
            {tierLabel(achievement.tier)}
          </span>
        </p>
        <p className="mt-0.5 text-xs text-[var(--color-muted)]">{achievement.description}</p>
        {achievement.earned ? (
          <p className="mt-1 text-xs font-semibold text-[var(--color-primary)]">
            Conseguido{achievement.earned_on ? ` · ${achievement.earned_on}` : ""}
          </p>
        ) : (
          <div className="mt-1.5 flex items-center gap-2">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--color-surface-2)]">
              <div
                className="h-full rounded-full bg-[var(--color-primary)] opacity-70"
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="shrink-0 text-[11px] font-semibold text-[var(--color-muted)]">
              {achievement.progress}/{achievement.target}
            </span>
          </div>
        )}
      </div>
    </li>
  );
}

/** Lo que se ve al conseguir un logro. Aparece una sola vez: el API solo devuelve una clave
 * en `newly_earned` la primera vez que detecta el logro, y el worker manda además el aviso
 * push por si no estabas mirando. */
function Celebration({
  achievements,
  onClose,
}: {
  achievements: Achievement[];
  onClose: () => void;
}) {
  useEffect(() => {
    const id = setTimeout(onClose, 12000);
    return () => clearTimeout(id);
  }, [onClose]);

  return (
    <div
      role="alert"
      className="sheet-in flex items-start gap-3 rounded-[var(--radius-card)] border border-[var(--color-primary)] bg-[var(--color-primary-soft)] p-4"
    >
      <PartyPopper
        size={22}
        aria-hidden="true"
        className="mt-0.5 shrink-0 text-[var(--color-primary)]"
      />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-extrabold text-[var(--color-primary)]">
          {achievements.length === 1 ? "¡Logro conseguido!" : "¡Logros conseguidos!"}
        </p>
        <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-2">
          {achievements.slice(0, CELEBRATION_MAX).map((a) => (
            <li key={a.key} className="flex items-center gap-2">
              <AchievementBadge achievement={a} size={40} />
              <span className="text-sm font-bold">{a.title}</span>
            </li>
          ))}
        </ul>
        {achievements.length > CELEBRATION_MAX && (
          <p className="mt-1.5 text-xs font-semibold text-[var(--color-primary)]">
            y {achievements.length - CELEBRATION_MAX} más, aquí abajo.
          </p>
        )}
      </div>
      <button
        type="button"
        onClick={onClose}
        aria-label="Cerrar el aviso"
        className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-[var(--color-primary)] hover:bg-[var(--color-surface)]"
      >
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  );
}

export function Achievements({
  achievements,
  newlyEarned,
}: {
  achievements: Achievement[];
  newlyEarned: string[];
}) {
  const [dismissed, setDismissed] = useState(false);
  const earned = achievements.filter((a) => a.earned);
  const fresh = achievements.filter((a) => newlyEarned.includes(a.key));

  return (
    <div className="flex flex-col gap-4">
      {fresh.length > 0 && !dismissed && (
        <Celebration achievements={fresh} onClose={() => setDismissed(true)} />
      )}

      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-extrabold tracking-tight">Logros</h2>
        <p className="text-xs font-semibold text-[var(--color-muted)]">
          {earned.length} de {achievements.length} conseguidos
        </p>
      </div>

      {groupByFamily(achievements).map(([family, items]) => (
        <section key={family} aria-labelledby={`logros-${family}`}>
          <h3
            id={`logros-${family}`}
            className="mb-2 text-xs font-bold uppercase tracking-wide text-[var(--color-muted)]"
          >
            {FAMILY_TITLES[family] ?? family}
          </h3>
          <ul className="grid gap-2.5 sm:grid-cols-2">
            {items.map((a) => (
              <AchievementCard key={a.key} achievement={a} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
