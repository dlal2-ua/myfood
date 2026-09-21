const { chromium } = require("playwright-core");
const BASE = process.env.BASE_URL || "https://myfood.cartagena.dpdns.org";
const exe = process.env.CHROME_PATH;
const rnd = Math.random().toString(36).slice(2, 10);
const email = `e2e-ui-${rnd}@test.myfood`, password = "correcthorse-" + rnd;
const log = (...a) => console.log(...a);
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
    await api("POST", "/api/auth/register", { email, password, display_name: "E2E" });
    await api("POST", "/api/consents", { kind: "health_data", version: "v1" });
    const s = await api("GET", "/api/foods/search?q=galletas%20maria&limit=5");
    const food = s.body.items.find((i) => i.brand) || s.body.items[0];
    log("food", food.name_es, "|", food.brand, "| nutri", food.nutriscore_grade);
    await page.goto(BASE + `/foods/${food.id}`, { waitUntil: "networkidle" });
    const txt = await page.innerText("main");
    // La cantidad ya no es una casilla de gramos con un botón de porción: es un selector de
    // medidas caseras, con la porción del envase entre ellas cuando el catálogo la trae.
    const medidas = await page.$$eval("#portion-measure option", (els) => els.map((e) => e.textContent.trim()));
    log("ficha has Fuente:", /Fuente:/.test(txt), "| Licencia:", /Licencia:/.test(txt), "| medidas:", medidas.join(", "));
    await page.screenshot({ path: "ficha.png", fullPage: true });
    // registrar hoy y copiar al día anterior desde la UI
    await api("POST", "/api/log/food", { log_date: (() => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`; })(), meal_type: "lunch", food_id: food.id, grams: 50 });
    await page.goto(BASE + "/log", { waitUntil: "networkidle" });
    // ver día de ayer -> copiar hoy a ayer (origen = hoy)
    const y = new Date(); y.setDate(y.getDate() - 1);
    const yIso = `${y.getFullYear()}-${String(y.getMonth()+1).padStart(2,"0")}-${String(y.getDate()).padStart(2,"0")}`;
    const t = new Date(); const tIso = `${t.getFullYear()}-${String(t.getMonth()+1).padStart(2,"0")}-${String(t.getDate()).padStart(2,"0")}`;
    await page.locator('input[type="date"]').first().fill(yIso); // día que se ve = ayer
    await page.locator('input[type="date"]').nth(1).fill(tIso);   // origen = hoy
    await page.click(`button:has-text("Copiar al ${yIso}")`);
    await page.waitForSelector("text=Copiados 1 registro", { timeout: 10000 });
    log("copy-day UI ok");
  } catch (e) { log("UI FAILED:", e.message); await page.screenshot({ path: "ui-fail.png", fullPage: true }).catch(()=>{}); process.exitCode = 1; }
  finally {
    try { await page.goto(BASE + "/login"); await api("POST", "/api/auth/login", { email, password }); const d = await api("POST", "/api/privacy/delete-account", { password }); log("cleanup", d.status); } catch (e) { log("cleanup error", e.message); }
    await browser.close();
  }
})();
