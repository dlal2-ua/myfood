// Alimentos: sugerencias al entrar, búsqueda y filtros por supermercado, tipo de alimento y
// nutrición. Cuenta desechable e2e-*@test.myfood que se borra al terminar.
//   BASE_URL=... CHROME_PATH=... [OUT=/ruta/capturas] node e2e/foods.cjs
const { chromium } = require("playwright-core");
const fs = require("node:fs");
const BASE = process.env.BASE_URL || "https://myfood.cartagena.dpdns.org";
// Con la instancia en «solo con invitación», registrarse exige un código.
const INVITE_CODE = process.env.INVITE_CODE || "";
const OUT = process.env.OUT || "";
const rnd = Math.random().toString(36).slice(2, 10);
const email = `e2e-foods-${rnd}@test.myfood`;
const password = "correcthorse-" + rnd;
const log = (...a) => console.log(...a);
let failures = 0;
const check = (ok, what) => { log(ok ? "ok  " : "FAIL", what); if (!ok) failures++; };

(async () => {
  if (OUT) fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH, args: ["--no-sandbox"] });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: "es-ES", hasTouch: true, isMobile: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error" && !/favicon|Failed to load resource/.test(m.text())) errors.push(m.text().slice(0, 200)); });
  const shot = (name) => OUT && page.screenshot({ path: `${OUT}/foods_${name}.png`, fullPage: true });
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const r = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    let j = null; try { j = await r.json(); } catch {}
    return { status: r.status, body: j };
  }, { method, path, body });
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

  try {
    await page.goto(BASE + "/login");
    await api("POST", "/api/auth/register", { email, password, display_name: "Vera" , invite_code: INVITE_CODE});
    await api("POST", "/api/consents", { kind: "health_data", version: "v1" });
    await api("PUT", "/api/profile", { sex: "female", birth_date: "1994-06-12", height_cm: 168, meals_per_day: 3, activity_level: "moderate", goal: "maintain" });
    await api("POST", "/api/measurements", { measured_on: iso(new Date()), weight_kg: 62 });
    const s = await api("GET", "/api/foods/search?q=avena&limit=1");
    await api("POST", "/api/favorites", { food_id: s.body.items[0].id });

    // --- al entrar: sugerencias
    await page.goto(BASE + "/foods", { waitUntil: "networkidle" });
    await page.waitForSelector("main h2");
    const titles = await page.$$eval("main h2", (els) => els.map((e) => e.textContent.trim()));
    log("secciones:", JSON.stringify(titles));
    check(titles.includes("Tus favoritos"), "sugerencias: favoritos");
    check(titles.some((t) => t.startsWith("Básicos para")), "sugerencias: básicos según la comida");
    check(titles.some((t) => t.startsWith("Hoy te faltan unos")), "sugerencias: proteína que falta");
    await shot("1_sugerencias");

    // --- buscar por texto
    await page.fill('input[type="search"]', "yogur");
    await page.waitForSelector('section[aria-label="Resultados"] a[href^="/foods/"]');
    check(/resultados?/.test(await page.innerText('[role="status"]')), "búsqueda por texto con contador");
    await shot("2_busqueda");

    // --- añadir al diario sin salir de la lista (hoja de raciones)
    await page.getByRole("button", { name: /Añadir .* al diario/ }).first().click();
    await page.waitForSelector('[role="dialog"] select');
    const medidas = await page.$$eval('[role="dialog"] select:first-of-type option', (els) => els.map((e) => e.textContent.trim()));
    log("medidas:", medidas.join(" | "));
    check(medidas.includes("gramos"), "la hoja ofrece al menos los gramos");
    const kcalAntes = await page.locator('[role="dialog"] >> text=/\\d+ kcal/').first().textContent();
    await page.locator('[role="dialog"] button[aria-label="Añadir"]').first().click();
    await page.waitForTimeout(300);
    const kcalDespues = await page.locator('[role="dialog"] >> text=/\\d+ kcal/').first().textContent();
    check(kcalAntes !== kcalDespues, `las calorías se recalculan al cambiar la cantidad (${kcalAntes} -> ${kcalDespues})`);
    await shot("2b_hoja_racion");
    await page.getByRole("button", { name: "Añadir al diario" }).click();
    await page.waitForSelector("text=/Añadido a /", { timeout: 15000 });
    await page.getByRole("button", { name: "Cerrar" }).first().click();
    const dia = await api("GET", `/api/log?date=${iso(new Date())}`);
    check(dia.body?.food?.length > 0, "el alimento queda registrado en el día");

    // --- filtro de supermercado (hoja con recuentos)
    await page.getByRole("button", { name: /^Supermercado/ }).click();
    await page.waitForSelector('[role="dialog"]');
    const options = await page.$$eval('[role="dialog"] label', (els) => els.map((e) => e.innerText.replace(/\s+/g, " ").trim()));
    log("supermercados:", options.slice(0, 5).join(" | "));
    check(options.some((o) => o.startsWith("Mercadona")), "la hoja ofrece Mercadona con su recuento");
    await page.getByRole("checkbox", { name: /Mercadona/ }).check();
    await page.waitForTimeout(700);
    await shot("3_hoja_supermercado");
    await page.getByRole("button", { name: /^Ver \d+/ }).click();
    await page.waitForSelector('button[aria-label="Quitar el filtro Mercadona"]');
    const cards = await page.$$eval('section[aria-label="Resultados"] a[href^="/foods/"]', (els) => els.map((e) => e.innerText));
    check(cards.length > 0 && cards.every((t) => t.includes("Mercadona")), `todos los resultados (${cards.length}) son de Mercadona`);

    // --- filtro de nutrición (se exigen todas)
    await page.getByRole("button", { name: /^Nutrición/ }).click();
    await page.getByRole("checkbox", { name: /Alto en proteína/ }).check();
    await page.waitForTimeout(700);
    await page.getByRole("button", { name: /^Ver \d+|^Buscando|^Listo/ }).click();
    check((await page.$$('button[aria-label^="Quitar el filtro"]')).length === 2, "dos filtros elegidos como chips");
    await shot("4_filtros_combinados");

    // --- sin texto, solo filtros: se explora el catálogo; y limpiar vuelve a las sugerencias
    await page.fill('input[type="search"]', "");
    await page.waitForTimeout(800);
    check((await page.$$('section[aria-label="Resultados"] a[href^="/foods/"]')).length > 0, "solo con filtros (sin texto) hay resultados");
    await page.getByRole("button", { name: "Limpiar filtros" }).click();
    await page.waitForSelector("main h2");
    check((await page.$$('button[aria-label^="Quitar el filtro"]')).length === 0, "limpiar quita los chips");
    check((await page.$$('section[aria-label="Resultados"]')).length === 0, "sin criterios vuelven las sugerencias");

    // --- tipo de alimento y orden
    await page.getByRole("button", { name: /^Tipo de alimento/ }).click();
    await page.getByRole("checkbox", { name: /Pescados y mariscos/ }).check();
    await page.waitForTimeout(700);
    await page.keyboard.press("Escape");
    await page.selectOption("select", "protein_desc");
    await page.waitForTimeout(800);
    const proteins = await page.$$eval('section[aria-label="Resultados"] a[href^="/foods/"]', (els) => els.map((e) => (e.innerText.match(/P ([\d.]+) g/) || [])[1]).map(Number));
    check(proteins.length > 1 && proteins.every((v, i) => i === 0 || v <= proteins[i - 1] + 1e-9), `ordenado por proteína: ${proteins.slice(0, 5).join(" ≥ ")}`);
    await shot("5_pescados_por_proteina");

    // --- escritorio
    await page.setViewportSize({ width: 1280, height: 860 });
    await page.getByRole("button", { name: "Limpiar filtros" }).click();
    await page.waitForSelector("main h2");
    await shot("6_escritorio_sugerencias");
    check(errors.length === 0, `sin errores de consola/página (${errors.slice(0, 2).join(" ; ")})`);
  } catch (e) {
    failures++; log("FALLO:", e.message); await shot("fallo").catch(() => {});
  } finally {
    try {
      const c2 = await browser.newContext(); const p2 = await c2.newPage(); await p2.goto(BASE + "/login");
      const call = (path, body) => p2.evaluate(async ({ path, body }) => (await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).status, { path, body });
      await call("/api/auth/login", { email, password });
      log("cleanup", await call("/api/privacy/delete-account", { password }));
    } catch (e) { log("cleanup error", e.message); }
    await browser.close();
  }
  log(failures ? `${failures} comprobaciones fallidas` : "foods OK");
  process.exitCode = failures ? 1 : 0;
})();
