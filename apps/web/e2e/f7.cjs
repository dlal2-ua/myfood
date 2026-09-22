const { chromium } = require("playwright-core");
const BASE = process.env.BASE_URL || "https://myfood.cartagena.dpdns.org";
// Con la instancia en «solo con invitación», registrarse exige un código.
const INVITE_CODE = process.env.INVITE_CODE || "";
const exe = process.env.CHROME_PATH;
const rnd = Math.random().toString(36).slice(2, 10);
const email = `e2e-f7-${rnd}@test.myfood`, password = "correcthorse-" + rnd;
const log = (...a) => console.log(...a);
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
(async () => {
  const browser = await chromium.launch({ executablePath: exe, args: ["--no-sandbox"] });
  const page = await (await browser.newContext()).newPage();
  page.on("pageerror", (e) => log("PAGEERROR", e.message));
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const r = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    let j = null; try { j = await r.json(); } catch {}
    return { status: r.status, body: j };
  }, { method, path, body });
  try {
    await page.goto(BASE + "/login");
    await api("POST", "/api/auth/register", { email, password, display_name: "E2E" , invite_code: INVITE_CODE});
    await api("POST", "/api/consents", { kind: "health_data", version: "v1" });
    await api("PUT", "/api/profile", { sex: "male", birth_date: "1992-04-10", height_cm: 178, meals_per_day: 3, activity_level: "moderate", goal: "maintain" });
    const food = (await api("GET", "/api/foods/search?q=arroz&limit=3")).body.items[0];
    for (let i = 20; i >= 0; i -= 2) {
      const d = new Date(); d.setDate(d.getDate() - i);
      await api("POST", "/api/measurements", { measured_on: iso(d), weight_kg: 80 - (20 - i) * 0.05 });
      await api("POST", "/api/log/food", { log_date: iso(d), meal_type: "lunch", food_id: food.id, grams: 250 });
    }
    await api("POST", "/api/fasting/start", { target_hours: 16, started_at: new Date(Date.now() - 5 * 3600e3).toISOString() });

    await page.goto(BASE + "/progress", { waitUntil: "networkidle" });
    let txt = await page.innerText("main");
    log("progress: Tendencias", /Tendencias/.test(txt), "| Peso", /Peso/.test(txt), "| kcal por día", /Calorías por día/.test(txt), "| svg charts", await page.locator("main svg[role=img]").count());
    await page.screenshot({ path: "progress.png", fullPage: true });

    await page.goto(BASE + "/ayuno", { waitUntil: "networkidle" });
    txt = await page.innerText("main");
    log("ayuno: timer", /5 h 0\d min|4 h 5\d min/.test(txt), "| Terminar ayuno", /Terminar ayuno/.test(txt), "| disclaimer", /no es adecuado para todo el mundo/.test(txt));
    await page.click('button:has-text("Terminar ayuno")');
    await page.waitForSelector("text=Empezar un ayuno", { timeout: 8000 });
    log("ayuno: ended -> start card shown");

    await page.goto(BASE + "/calculadoras", { waitUntil: "networkidle" });
    await page.click('main section:first-of-type button:has-text("Calcular")');
    await page.waitForSelector("text=Metabolismo basal (TMB)", { timeout: 8000 });
    log("calculadoras: BMR result shown");
    await page.selectOption('main section:nth-of-type(2) select >> nth=0', "deurenberg");
    await page.fill('main section:nth-of-type(2) input >> nth=0', "178");
    await page.fill('main section:nth-of-type(2) input >> nth=1', "80");
    await page.fill('main section:nth-of-type(2) input >> nth=2', "33");
    await page.click('main section:nth-of-type(2) button:has-text("Calcular")');
    await page.waitForSelector("text=Grasa corporal", { timeout: 8000 });
    log("calculadoras: body fat shown:", (await page.innerText("main section:nth-of-type(2) dl")).replace(/\n/g, " ").slice(0, 120));

    const z = await page.evaluate(async () => { const r = await fetch("/api/privacy/export?format=zip"); const b = await r.arrayBuffer(); return { status: r.status, type: r.headers.get("content-type"), size: b.byteLength }; });
    log("export zip:", JSON.stringify(z));
  } catch (e) { log("F7 FAILED:", e.message); await page.screenshot({ path: "f7-fail.png", fullPage: true }).catch(()=>{}); process.exitCode = 1; }
  finally {
    try { await page.goto(BASE + "/login"); await api("POST", "/api/auth/login", { email, password }); const d = await api("POST", "/api/privacy/delete-account", { password }); log("cleanup", d.status); } catch (e) { log("cleanup error", e.message); }
    await browser.close();
  }
})();
