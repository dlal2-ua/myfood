import type { LogFoodEntry, MealType } from "@/lib/types";
import { MEAL_TYPES } from "@/lib/types";

/** Agrupa las entradas del día por comida, en el orden natural del día, sin comidas vacías. */
export function groupByMeal(entries: LogFoodEntry[]): { mealType: MealType; entries: LogFoodEntry[] }[] {
  return MEAL_TYPES.map((mealType) => ({
    mealType,
    entries: entries.filter((e) => e.meal_type === mealType),
  })).filter((group) => group.entries.length > 0);
}

/** Nombre a mostrar de una entrada: la receta, el alimento o, si falta, un texto neutro. */
export function entryName(entry: LogFoodEntry): string {
  return entry.recipe_name ?? entry.food_name ?? "Alimento";
}

/** Porcentaje entero de `value` sobre `target`, sin pasar de 999 y sin dividir por cero. */
export function percentOf(value: number, target: number | null | undefined): number | null {
  if (!target || target <= 0) return null;
  return Math.min(999, Math.round((100 * value) / target));
}

/** Comidas que siempre se muestran en el diario, aunque estén vacías, para poder añadir en ellas. */
export const CORE_MEALS: readonly MealType[] = ["breakfast", "lunch", "dinner"];

export interface DiaryMeal {
  mealType: MealType;
  entries: LogFoodEntry[];
  kcal: number;
}

/** Secciones del diario del día: las tres comidas principales siempre y las demás (medias
 * mañanas, meriendas, recena) solo si tienen algo. Cada una con el total de kcal. */
export function diaryMeals(entries: LogFoodEntry[]): DiaryMeal[] {
  return MEAL_TYPES.map((mealType) => {
    const own = entries.filter((e) => e.meal_type === mealType);
    return { mealType, entries: own, kcal: own.reduce((sum, e) => sum + e.kcal, 0) };
  }).filter((meal) => meal.entries.length > 0 || CORE_MEALS.includes(meal.mealType));
}

export interface CalorieBudget {
  /** Kcal que quedan hasta el objetivo (0 si ya se ha llegado o pasado). */
  remaining: number;
  /** Kcal por encima del objetivo (0 si no se ha llegado). */
  over: number;
  /** Fracción del objetivo consumida, entre 0 y 1 (para dibujar el anillo). */
  fraction: number;
}

/** «Objetivo − comida = restantes». No juzga: pasarse es un dato, no un error (R10). Sin
 * objetivo no hay presupuesto. */
export function calorieBudget(consumed: number, target: number | null | undefined): CalorieBudget | null {
  if (!target || target <= 0) return null;
  const diff = Math.round(target - consumed);
  return {
    remaining: Math.max(0, diff),
    over: Math.max(0, -diff),
    fraction: Math.min(1, Math.max(0, consumed / target)),
  };
}
