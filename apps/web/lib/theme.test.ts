// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  THEME_INIT_SCRIPT,
  THEME_STORAGE_KEY,
  applyTheme,
  readThemePreference,
  resolveTheme,
  saveThemePreference,
} from "@/lib/theme";

function mockSystemDark(dark: boolean) {
  window.matchMedia = vi.fn().mockReturnValue({ matches: dark }) as unknown as typeof window.matchMedia;
}

describe("resolveTheme", () => {
  it("follows the system only in system mode", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
});

describe("theme preference", () => {
  beforeEach(() => {
    window.localStorage.clear();
    delete document.documentElement.dataset.theme;
    mockSystemDark(false);
  });
  afterEach(() => vi.restoreAllMocks());

  it("defaults to system and ignores garbage values", () => {
    expect(readThemePreference()).toBe("system");
    window.localStorage.setItem(THEME_STORAGE_KEY, "neon");
    expect(readThemePreference()).toBe("system");
  });

  it("saves and applies an explicit choice over the system setting", () => {
    mockSystemDark(true);
    saveThemePreference("light");
    expect(readThemePreference()).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    saveThemePreference("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("system mode follows prefers-color-scheme", () => {
    mockSystemDark(true);
    expect(applyTheme("system")).toBe("dark");
    mockSystemDark(false);
    expect(applyTheme("system")).toBe("light");
  });

  it("updates the browser bar colour", () => {
    document.head.innerHTML = '<meta name="theme-color" content="#000" media="(prefers-color-scheme: light)">';
    applyTheme("dark");
    const meta = document.head.querySelector<HTMLMetaElement>('meta[name="theme-color"]')!;
    expect(meta.content).toBe("#08120f");
    expect(meta.hasAttribute("media")).toBe(false);
  });
});

describe("THEME_INIT_SCRIPT", () => {
  beforeEach(() => {
    window.localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("applies the stored dark theme before paint", () => {
    mockSystemDark(false);
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    new Function(THEME_INIT_SCRIPT)();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("uses the system theme when nothing is stored", () => {
    mockSystemDark(true);
    new Function(THEME_INIT_SCRIPT)();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("an explicit light choice beats a dark system", () => {
    mockSystemDark(true);
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    new Function(THEME_INIT_SCRIPT)();
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
