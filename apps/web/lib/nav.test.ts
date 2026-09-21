import { describe, expect, it } from "vitest";
import {
  BOTTOM_TABS,
  NAV_GROUPS,
  QUICK_ACTIONS,
  accountItems,
  filterGroups,
  isActive,
  sidebarGroups,
  tabForPath,
  visibleGroups,
} from "@/lib/nav";

describe("isActive", () => {
  it("matches the exact route and its children, not look-alikes", () => {
    expect(isActive("/foods", "/foods")).toBe(true);
    expect(isActive("/foods/abc", "/foods")).toBe(true);
    expect(isActive("/foodstuff", "/foods")).toBe(false);
    expect(isActive("/log", "/")).toBe(false);
    expect(isActive("/", "/")).toBe(true);
  });
});

describe("tabForPath", () => {
  it("marks the main tabs and sends everything else under «Más»", () => {
    expect(tabForPath("/")).toBe("today");
    expect(tabForPath("/log")).toBe("log");
    expect(tabForPath("/foods/123")).toBe("foods");
    expect(tabForPath("/diet-plans/7")).toBe("more");
    expect(tabForPath("/mas")).toBe("more");
    expect(tabForPath("/profile")).toBe("more");
  });
});

describe("navigation config", () => {
  const hrefs = NAV_GROUPS.flatMap((g) => g.items.map((i) => i.href));

  it("has no duplicated routes and every item explains itself", () => {
    expect(new Set(hrefs).size).toBe(hrefs.length);
    for (const item of NAV_GROUPS.flatMap((g) => g.items)) {
      expect(item.description.length).toBeGreaterThan(10);
    }
  });

  it("exposes every bottom-bar and quick-action destination somewhere in the app", () => {
    for (const tab of BOTTOM_TABS) {
      if (tab.key !== "more" && tab.key !== "today") expect(hrefs).toContain(tab.href);
    }
    for (const action of QUICK_ACTIONS) {
      expect(Boolean(action.href) !== Boolean(action.action)).toBe(true);
      if (action.href) expect(hrefs).toContain(action.href.split("#")[0]);
    }
  });

  it("hides the admin area from regular users", () => {
    const regular = visibleGroups(false).flatMap((g) => g.items.map((i) => i.href));
    const admin = visibleGroups(true).flatMap((g) => g.items.map((i) => i.href));
    expect(regular).not.toContain("/admin");
    expect(admin).toContain("/admin");
  });
});

describe("sidebar and account menu", () => {
  it("keeps account settings out of the sidebar and in the account menu, so nothing is lost", () => {
    const side = sidebarGroups(false).flatMap((g) => g.items.map((i) => i.href));
    const account = accountItems(false).map((i) => i.href);
    expect(side).not.toContain("/profile");
    expect(account).toEqual(expect.arrayContaining(["/profile", "/security", "/privacy", "/recordatorios", "/household"]));
    const everything = visibleGroups(false).flatMap((g) => g.items.map((i) => i.href));
    expect([...side, ...account].sort()).toEqual([...everything].sort());
  });

  it("only offers the admin area to admins", () => {
    expect(accountItems(false).map((i) => i.href)).not.toContain("/admin");
    expect(accountItems(true).map((i) => i.href)).toContain("/admin");
  });
});

describe("filterGroups", () => {
  const groups = visibleGroups(false);

  it("returns everything for an empty query", () => {
    expect(filterGroups(groups, "  ")).toEqual(groups);
  });

  it("finds by label without caring about accents or case", () => {
    const found = filterGroups(groups, "RECORDATORIOS").flatMap((g) => g.items.map((i) => i.href));
    expect(found).toContain("/recordatorios");
    expect(found).not.toContain("/foods");
    expect(filterGroups(groups, "calculadoras").flatMap((g) => g.items.map((i) => i.href))).toEqual([
      "/calculadoras",
    ]);
  });

  it("finds by description and drops empty groups", () => {
    const found = filterGroups(groups, "codigo de barras");
    expect(found.flatMap((g) => g.items.map((i) => i.href))).toContain("/scan");
    expect(found.every((g) => g.items.length > 0)).toBe(true);
    expect(filterGroups(groups, "zzzz")).toEqual([]);
  });
});
