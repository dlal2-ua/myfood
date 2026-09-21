"use client";

import {
  Apple,
  ChefHat,
  Droplets,
  Flame,
  Lock,
  NotebookPen,
  Sprout,
  Sun,
  type LucideIcon,
} from "lucide-react";
import type { Achievement } from "@/lib/types";

/** Cada insignia es una medalla: aro de color según lo que cuesta, dibujo según de qué va.
 * Las que faltan salen apagadas y con el aro a medio llenar — se ve cuánto queda sin tener
 * que leer el número. */
const ICONS: Record<string, LucideIcon> = {
  seedling: Sprout,
  notebook: NotebookPen,
  flame: Flame,
  droplet: Droplets,
  apple: Apple,
  chef: ChefHat,
  sun: Sun,
};

/** Colores de cada nivel. Van fijos y no por variable de tema: una medalla de bronce es de
 * color bronce en claro y en oscuro, no del color de marca. */
const TIER_STYLE: Record<string, { ring: string; fill: string; label: string }> = {
  bronze: { ring: "#c08552", fill: "#c0855222", label: "Bronce" },
  silver: { ring: "#9aa5b1", fill: "#9aa5b122", label: "Plata" },
  gold: { ring: "#d4a017", fill: "#d4a01722", label: "Oro" },
};

const SIZE = 64;
const RADIUS = 28;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export function AchievementBadge({
  achievement,
  size = SIZE,
}: {
  achievement: Achievement;
  size?: number;
}) {
  const Icon = ICONS[achievement.icon] ?? Sprout;
  const tier = TIER_STYLE[achievement.tier] ?? TIER_STYLE.bronze;
  const ratio = achievement.target > 0 ? achievement.progress / achievement.target : 0;
  const earned = achievement.earned;

  return (
    <span
      className="relative inline-grid shrink-0 place-items-center"
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} width={size} height={size} className="absolute inset-0">
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill={earned ? tier.fill : "transparent"}
          stroke="currentColor"
          strokeWidth={4}
          opacity={earned ? 0.12 : 0.18}
        />
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke={tier.ring}
          strokeWidth={4}
          strokeLinecap="round"
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={CIRCUMFERENCE * (1 - (earned ? 1 : Math.min(1, ratio)))}
          transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
          opacity={earned ? 1 : 0.85}
        />
      </svg>
      <span
        className="relative grid place-items-center rounded-full"
        style={{
          width: size * 0.62,
          height: size * 0.62,
          background: earned ? tier.fill : "transparent",
          color: earned ? tier.ring : "var(--color-muted)",
          opacity: earned ? 1 : 0.55,
        }}
      >
        {earned ? <Icon size={size * 0.34} /> : <Lock size={size * 0.3} />}
      </span>
    </span>
  );
}

export function tierLabel(tier: string): string {
  return TIER_STYLE[tier]?.label ?? "";
}
