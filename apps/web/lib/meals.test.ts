import { describe, expect, it } from "vitest";
import { mealTypeForTime } from "@/lib/meals";

const at = (h: number, m = 0) => new Date(2026, 8, 20, h, m);

describe("mealTypeForTime", () => {
  it.each([
    [8, 0, "breakfast"],
    [10, 29, "breakfast"],
    [11, 0, "morning_snack"],
    [14, 0, "lunch"],
    [17, 30, "afternoon_snack"],
    [21, 0, "dinner"],
    [23, 30, "supper"],
    [2, 0, "supper"],
  ])("%i:%i -> %s", (h, m, expected) => {
    expect(mealTypeForTime(at(h, m))).toBe(expected);
  });
});
