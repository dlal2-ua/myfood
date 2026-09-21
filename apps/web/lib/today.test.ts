import { describe, expect, it } from "vitest";
import { calorieBudget, diaryMeals, entryName, groupByMeal, percentOf } from "@/lib/today";
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

describe("diaryMeals", () => {
  it("always lists breakfast, lunch and dinner, even empty", () => {
    const meals = diaryMeals([]);
    expect(meals.map((m) => m.mealType)).toEqual(["breakfast", "lunch", "dinner"]);
    expect(meals.every((m) => m.kcal === 0 && m.entries.length === 0)).toBe(true);
  });

  it("adds snacks only when they have entries, in the natural order, with kcal subtotals", () => {
    const meals = diaryMeals([
      entry({ id: "a", meal_type: "afternoon_snack", kcal: 120 }),
      entry({ id: "b", meal_type: "breakfast", kcal: 300 }),
      entry({ id: "c", meal_type: "breakfast", kcal: 50 }),
    ]);
    expect(meals.map((m) => m.mealType)).toEqual(["breakfast", "lunch", "afternoon_snack", "dinner"]);
    expect(meals[0].kcal).toBe(350);
    expect(meals[2].kcal).toBe(120);
  });
});

describe("calorieBudget", () => {
  it("is target minus food, never negative", () => {
    expect(calorieBudget(1420, 2100)).toMatchObject({ remaining: 680, over: 0 });
    expect(calorieBudget(2100, 2100)).toMatchObject({ remaining: 0, over: 0, fraction: 1 });
  });

  it("reports going over as data, capped ring", () => {
    expect(calorieBudget(2350, 2100)).toMatchObject({ remaining: 0, over: 250, fraction: 1 });
  });

  it("has no budget without a target", () => {
    expect(calorieBudget(500, null)).toBeNull();
    expect(calorieBudget(500, 0)).toBeNull();
  });
});
