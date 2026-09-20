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
