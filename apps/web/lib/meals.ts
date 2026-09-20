import type { MealType } from "@/lib/types";

/** Comida que toca a esta hora del día (hora local del dispositivo). */
export function mealTypeForTime(date: Date = new Date()): MealType {
  const minutes = date.getHours() * 60 + date.getMinutes();
  if (minutes < 5 * 60) return "supper";
  if (minutes < 10 * 60 + 30) return "breakfast";
  if (minutes < 12 * 60) return "morning_snack";
  if (minutes < 16 * 60) return "lunch";
  if (minutes < 19 * 60) return "afternoon_snack";
  if (minutes < 22 * 60 + 30) return "dinner";
  return "supper";
}
