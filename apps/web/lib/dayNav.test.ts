import { describe, expect, it } from "vitest";
import { relativeDayLabel, shiftIsoDate } from "@/lib/dayNav";

describe("shiftIsoDate", () => {
  it("moves across month, year and leap-day boundaries", () => {
    expect(shiftIsoDate("2026-09-21", -1)).toBe("2026-09-20");
    expect(shiftIsoDate("2026-09-30", 1)).toBe("2026-10-01");
    expect(shiftIsoDate("2026-01-01", -1)).toBe("2025-12-31");
    expect(shiftIsoDate("2028-02-28", 1)).toBe("2028-02-29");
    expect(shiftIsoDate("2026-03-01", -1)).toBe("2026-02-28");
  });
  it("is stable around daylight-saving changes", () => {
    expect(shiftIsoDate("2026-03-28", 1)).toBe("2026-03-29");
    expect(shiftIsoDate("2026-03-29", 1)).toBe("2026-03-30");
    expect(shiftIsoDate("2026-10-24", 2)).toBe("2026-10-26");
  });
});

describe("relativeDayLabel", () => {
  const today = "2026-09-21";
  it("names today, yesterday and tomorrow", () => {
    expect(relativeDayLabel("2026-09-21", today)).toBe("Hoy");
    expect(relativeDayLabel("2026-09-20", today)).toBe("Ayer");
    expect(relativeDayLabel("2026-09-22", today)).toBe("Mañana");
  });
  it("shows a short date otherwise, with the year only when it differs", () => {
    expect(relativeDayLabel("2026-09-14", today)).toMatch(/14/);
    expect(relativeDayLabel("2026-09-14", today)).not.toMatch(/2026/);
    expect(relativeDayLabel("2025-12-31", today)).toMatch(/2025/);
    expect(relativeDayLabel("2026-09-14", today)).not.toMatch(/\./);
  });
});
