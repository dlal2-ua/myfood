import { describe, expect, it } from "vitest";
import { entryName, groupByMeal, percentOf } from "@/lib/today";
import type { LogFoodEntry } from "@/lib/types";

const entry = (over: Partial<LogFoodEntry>): LogFoodEntry => ({
  id: "1",
  log_date: "2026-09-21",
  meal_type: "lunch",
  food_id: "f",
  grams: 100,
  entry_source: "manual",
  kcal: 100,
  protein_g: 1,
  fat_g: 1,
  carbs_g: 1,
  ...over,
});

describe("groupByMeal", () => {
  it("orders meals through the day and leaves out the empty ones", () => {
    const groups = groupByMeal([
      entry({ id: "a", meal_type: "dinner" }),
      entry({ id: "b", meal_type: "breakfast" }),
      entry({ id: "c", meal_type: "dinner" }),
    ]);
    expect(groups.map((g) => g.mealType)).toEqual(["breakfast", "dinner"]);
    expect(groups[1].entries.map((e) => e.id)).toEqual(["a", "c"]);
  });

  it("is empty for a day without entries", () => {
    expect(groupByMeal([])).toEqual([]);
  });
});

describe("entryName", () => {
  it("prefers the recipe name, then the food name, then a neutral text", () => {
    expect(entryName(entry({ recipe_name: "Lentejas", food_name: "Arroz" }))).toBe("Lentejas");
    expect(entryName(entry({ food_name: "Arroz" }))).toBe("Arroz");
    expect(entryName(entry({}))).toBe("Alimento");
  });
});

describe("percentOf", () => {
  it("rounds, caps and never divides by zero", () => {
    expect(percentOf(50, 200)).toBe(25);
    expect(percentOf(2000, 1)).toBe(999);
    expect(percentOf(10, 0)).toBeNull();
    expect(percentOf(10, null)).toBeNull();
    expect(percentOf(10, undefined)).toBeNull();
  });
});
