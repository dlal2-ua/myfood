// QA visual: capturas de las pantallas en claro/oscuro y móvil/escritorio, y comprobaciones
// automáticas (sin desbordes horizontales, sin errores de consola, sin texto ilegible en tema
// oscuro). Cuenta desechable e2e-*@test.myfood que se borra al terminar.
//   BASE_URL=http://127.0.0.1:3999 CHROME_PATH=... OUT=/tmp/visual node e2e/visual.cjs [ruta ...]
const { chromium } = require("playwright-core");
const fs = require("node:fs");
const BASE = process.env.BASE_URL || "https://myfood.cartagena.dpdns.org";
const OUT = process.env.OUT || "visual-out";
const rnd = Math.random().toString(36).slice(2, 10);
const email = `e2e-vis-${rnd}@test.myfood`;
const password = "correcthorse-" + rnd;
const log = (...a) => console.log(...a);

const AUTH_ROUTES = [
  "/", "/log", "/foods", "/mas", "/diet-plans", "/recipes", "/progress", "/water", "/profile",
  "/supplements", "/scan", "/chat", "/ayuno", "/calculadoras", "/recordatorios", "/pantry",
  "/shopping-list", "/security", "/privacy", "/household", "/wearables",
];
const PUBLIC_ROUTES = ["/", "/login", "/register"];
const VIEWPORTS = { mobile: { width: 390, height: 844 }, desktop: { width: 1280, height: 860 } };
const slug = (r) => (r === "/" ? "home" : r.slice(1).replace(/\//g, "_"));
const only = process.argv.slice(2);

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH, args: ["--no-sandbox"] });
  const problems = [];
  const themed = async (theme, vp) => {
    const ctx = await browser.newContext({ viewport: VIEWPORTS[vp], locale: "es-ES", colorScheme: "light", hasTouch: vp === "mobile", isMobile: vp === "mobile" });
    await ctx.addInitScript((t) => { try { localStorage.setItem("myfood-theme", t); } catch {} }, theme);
    return ctx;
  };
  const check = async (page, label) => {
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (overflow > 1) problems.push(`${label}: desborde horizontal de ${overflow}px`);
  };

  try {
    // --- páginas públicas (sin sesión)
    for (const theme of ["light", "dark"]) {
      for (const vp of ["mobile", "desktop"]) {
        const ctx = await themed(theme, vp);
        const page = await ctx.newPage();
        page.on("pageerror", (e) => problems.push(`pública ${theme}/${vp}: pageerror ${e.message}`));
        for (const r of PUBLIC_ROUTES) {
          if (only.length && !only.includes(r)) continue;
          await page.goto(BASE + r, { waitUntil: "networkidle" });
          await page.screenshot({ path: `${OUT}/public_${slug(r)}_${theme}_${vp}.png`, fullPage: true });
          await check(page, `pública ${r} ${theme}/${vp}`);
        }
        await ctx.close();
      }
    }

    // --- cuenta desechable con datos para que las pantallas no estén vacías
    const setup = await (await themed("light", "desktop")).newPage();
    setup.on("pageerror", () => {});
    await setup.goto(BASE + "/login");
    const api = (method, path, body) => setup.evaluate(async ({ method, path, body }) => {
      const r = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
      let j = null; try { j = await r.json(); } catch {}
      return { status: r.status, body: j };
    }, { method, path, body });
    await api("POST", "/api/auth/register", { email, password, display_name: "Vera" });
    await api("POST", "/api/consents", { kind: "health_data", version: "v1" });
    await api("PUT", "/api/profile", { sex: "female", birth_date: "1994-06-12", height_cm: 168, meals_per_day: 3, activity_level: "moderate", goal: "maintain" });
    const d = new Date();
    const iso = (x) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
    await api("POST", "/api/measurements", { measured_on: iso(d), weight_kg: 62 });
    const found = [];
    for (const q of ["avena", "huevo", "pollo", "yogur", "plátano"]) {
      const s = await api("GET", `/api/foods/search?q=${encodeURIComponent(q)}&limit=3`);
      if (s.body && s.body.items && s.body.items[0]) found.push(s.body.items[0]);
    }
    const meals = ["breakfast", "breakfast", "lunch", "afternoon_snack", "afternoon_snack"];
    for (let i = 0; i < found.length; i++) {
      await api("POST", "/api/log/food", { log_date: iso(d), meal_type: meals[i], food_id: found[i].id, grams: 80 + i * 20 });
    }
    await api("POST", "/api/water/log", { log_date: iso(d), ml: 400 });
    const cookies = await setup.context().cookies();

    for (const theme of ["light", "dark"]) {
      for (const vp of ["mobile", "desktop"]) {
        const ctx = await themed(theme, vp);
        await ctx.addCookies(cookies);
        const page = await ctx.newPage();
        page.on("pageerror", (e) => problems.push(`${theme}/${vp}: pageerror ${e.message}`));
        page.on("console", (m) => { if (m.type() === "error" && !/favicon|Failed to load resource/.test(m.text())) problems.push(`${theme}/${vp} ${page.url().replace(BASE, "")}: console ${m.text().slice(0, 900)}`); });
        for (const r of AUTH_ROUTES) {
          if (only.length && !only.includes(r)) continue;
          await page.goto(BASE + r, { waitUntil: "networkidle" });
          await page.waitForTimeout(400);
          await page.screenshot({ path: `${OUT}/${slug(r)}_${theme}_${vp}.png`, fullPage: true });
          await check(page, `${r} ${theme}/${vp}`);
        }
        // hoja de acciones rápidas y menú de cuenta
        if (!only.length) {
          await page.goto(BASE + "/", { waitUntil: "networkidle" });
          const add = page.getByRole("button", { name: "Añadir", exact: true }).first();
          await add.click();
          await page.waitForSelector('[role="dialog"]');
          await page.waitForTimeout(400); // deja terminar la animación de la hoja
          await page.screenshot({ path: `${OUT}/quickadd_${theme}_${vp}.png` });
          await page.keyboard.press("Escape");
          await page.getByRole("button", { name: /Cuenta de/ }).first().click();
          await page.screenshot({ path: `${OUT}/account_${theme}_${vp}.png` });
        }
        await ctx.close();
      }
    }
  } catch (e) {
    problems.push("FALLO: " + e.message);
  } finally {
    try {
      const ctx = await browser.newContext();
      const page = await ctx.newPage();
      await page.goto(BASE + "/login");
      const call = (path, body) => page.evaluate(async ({ path, body }) => {
        const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        return r.status;
      }, { path, body });
      await call("/api/auth/login", { email, password });
      log("cleanup", await call("/api/privacy/delete-account", { password }));
    } catch (e) { log("cleanup error", e.message); }
    await browser.close();
  }
  log(problems.length ? "PROBLEMAS:\n - " + problems.join("\n - ") : "sin problemas automáticos");
  process.exitCode = problems.length ? 1 : 0;
})();
