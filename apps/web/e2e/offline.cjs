const { chromium } = require("playwright-core");
const BASE = process.env.BASE_URL || "https://myfood.cartagena.dpdns.org";
// Con la instancia en «solo con invitación», registrarse exige un código.
const INVITE_CODE = process.env.INVITE_CODE || "";
const exe = process.env.CHROME_PATH;
const rnd = Math.random().toString(36).slice(2, 10);
const email = `e2e-offline-${rnd}@test.myfood`;
const password = "correcthorse-" + rnd;
const log = (...a) => console.log(...a);
const local = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`; };

(async () => {
  const browser = await chromium.launch({ executablePath: exe, args: ["--no-sandbox"] });
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on("pageerror", (e) => log("PAGEERROR", e.message));
  const api = async (method, path, body) =>
    page.evaluate(async ({ method, path, body }) => {
      const r = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
      let j = null; try { j = await r.json(); } catch {}
      return { status: r.status, body: j };
    }, { method, path, body });
  try {
    await page.goto(BASE + "/login");
    let r = await api("POST", "/api/auth/register", { email, password, display_name: "E2E" , invite_code: INVITE_CODE});
    log("register", r.status);
    r = await api("POST", "/api/consents", { kind: "health_data", version: "v1" });
    log("consent", r.status);

    r = await api("GET", "/api/foods/search?q=pollo&limit=5");
    const food = r.body.items[0];
    log("food", food.name_es, food.id);

    await page.goto(BASE + "/log", { waitUntil: "networkidle" });
    await page.goto(BASE + "/water", { waitUntil: "networkidle" });
    await page.goto(BASE + `/foods/${food.id}`, { waitUntil: "networkidle" });
    const ready = await page.evaluate(async () => { const reg = await navigator.serviceWorker.ready; return !!reg.active; });
    log("sw active", ready);
    await page.reload({ waitUntil: "networkidle" }); // ya bajo control del SW
    const controlled = await page.evaluate(() => !!navigator.serviceWorker.controller);
    log("page controlled by sw", controlled);
    const cacheNames = await page.evaluate(() => caches.keys());
    log("caches", cacheNames.sort().join(","));

    // --- sin conexión ---
    await context.setOffline(true);
    await page.waitForTimeout(500);
    // La cantidad va por medida casera: se elige «gramos» para que 150 sean 150 g.
    await page.selectOption("#portion-measure", "g");
    await page.fill("#portion-quantity", "150");
    await page.click('button:has-text("Registrar")');
    await page.waitForSelector("text=guardado en este dispositivo", { timeout: 8000 });
    log("food queued offline: message shown");
    await page.waitForSelector("text=1 registro pendiente", { timeout: 8000 });
    log("status bar shows 1 pending");

    await page.goto(BASE + "/water"); // desde caché de páginas
    await page.waitForSelector("main h1:has-text(\"Agua\")", { timeout: 8000 });
    await page.click('button:has-text("+ Vaso")');
    await page.waitForSelector("text=2 registros pendientes", { timeout: 8000 });
    log("water queued offline, bar shows 2 pending");

    // una página nunca visitada muestra la página de sin conexión, no un error del navegador
    const resp = await page.goto(BASE + "/security").catch((e) => ({ err: e.message }));
    log("unvisited page offline ->", resp && resp.err ? "browser error " + resp.err : "status " + (resp && resp.status()));

    // --- vuelve la red ---
    await page.goto(BASE + "/water").catch(() => {});
    await context.setOffline(false);
    // La barra de estado tarda en pintarse tras recargar, así que no vale «no hay texto pendiente»:
    // se espera a que el servidor tenga de verdad lo registrado sin conexión.
    for (let i = 0; i < 30; i++) {
      const d = await api("GET", `/api/log?date=${local()}`);
      const w = await api("GET", `/api/water/log?date=${local()}`);
      if (d.body.food.length > 0 && w.body.total_ml > 0) break;
      await page.waitForTimeout(2000);
    }
    await page.waitForFunction(() => !document.body.innerText.includes("pendiente"), null, { timeout: 30000 });
    log("queue drained after reconnect");

    const day = await api("GET", `/api/log?date=${local()}`);
    const foodEntries = day.body.food.filter((e) => e.food_id === food.id);
    log("server food entries:", foodEntries.length, foodEntries[0] && foodEntries[0].grams);
    const water = await api("GET", `/api/water/log?date=${local()}`);
    log("server water total:", water.body.total_ml);

    // idempotencia: reenviar el mismo client_id no duplica
    const dup = await api("POST", "/api/log/food", { log_date: local(), meal_type: "lunch", food_id: food.id, grams: 150, client_id: foodEntries[0].id });
    const day2 = await api("GET", `/api/log?date=${local()}`);
    log("resend same client_id ->", dup.status, "entries:", day2.body.food.length);

    // logout limpia cachés con datos de usuario
    await page.goto(BASE + "/log", { waitUntil: "networkidle" });
    await page.getByRole("button", { name: /Cuenta de/ }).first().click(); // «Salir» está en el menú de la cuenta
    await page.click('button:has-text("Salir")');
    await page.waitForURL("**/login", { timeout: 15000 });
    const after = await page.evaluate(() => caches.keys());
    log("caches after logout", after.sort().join(","));
  } catch (e) {
    log("E2E FAILED:", e.message);
    await page.screenshot({ path: "fail.png", fullPage: true }).catch(() => {});
    process.exitCode = 1;
  } finally {
    // limpieza: borrar la cuenta desechable
    try {
      await context.setOffline(false);
      await page.goto(BASE + "/login");
      await api("POST", "/api/auth/login", { email, password });
      const d = await api("POST", "/api/privacy/delete-account", { password });
      log("cleanup delete-account", d.status);
    } catch (e) { log("cleanup error", e.message); }
    await browser.close();
  }
})();
