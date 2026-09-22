// Escáner sin cámara: buscar un producto escribiendo su código de barras. Cuenta desechable.
//   BASE_URL=... CHROME_PATH=... node e2e/scan.cjs
const { chromium } = require("playwright-core");
const BASE = process.env.BASE_URL || "https://myfood.cartagena.dpdns.org";
// Con la instancia en «solo con invitación», registrarse exige un código.
const INVITE_CODE = process.env.INVITE_CODE || "";
const rnd = Math.random().toString(36).slice(2, 10);
const email = `e2e-scan-${rnd}@test.myfood`;
const password = "correcthorse-" + rnd;
const log = (...a) => console.log(...a);
let failures = 0;
const check = (ok, what) => { log(ok ? "ok  " : "FAIL", what); if (!ok) failures++; };

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH, args: ["--no-sandbox"] });
  const page = await (await browser.newContext({ viewport: { width: 390, height: 844 }, locale: "es-ES" })).newPage();
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const r = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    let j = null; try { j = await r.json(); } catch {}
    return { status: r.status, body: j };
  }, { method, path, body });
  try {
    await page.goto(BASE + "/login");
    await api("POST", "/api/auth/register", { email, password, display_name: "Scan" , invite_code: INVITE_CODE});
    await api("POST", "/api/consents", { kind: "health_data", version: "v1" });
    const found = await api("GET", "/api/foods/search?q=galletas%20maria&limit=10");
    let withCode = null;
    for (const item of found.body.items) {
      const d = await api("GET", `/api/foods/${item.id}`);
      if (d.body.barcode_ean) { withCode = d.body; break; }
    }
    check(withCode != null, "hay un producto con código de barras en el catálogo");

    await page.goto(BASE + "/scan", { waitUntil: "networkidle" });
    check(await page.getByPlaceholder("8410000000000").isVisible(), "el campo para escribir el código está a la vista");
    await page.getByPlaceholder("8410000000000").fill("123");
    await page.getByRole("button", { name: "Buscar" }).click();
    check(await page.getByText(/entre 8 y 14 cifras/).isVisible(), "un código no válido se explica");

    await page.getByPlaceholder("8410000000000").fill(withCode.barcode_ean);
    await page.getByRole("button", { name: "Buscar" }).click();
    await page.getByRole("heading", { name: withCode.name_es }).waitFor({ timeout: 15000 });
    check(true, `encuentra «${withCode.name_es}» por su código`);

    await page.getByRole("button", { name: "Escanear otro código" }).click();
    await page.getByPlaceholder("8410000000000").fill("2912345678904");
    await page.getByRole("button", { name: "Buscar" }).click();
    await page.getByText(/No encontramos el código/).waitFor({ timeout: 20000 });
    check(true, "un código desconocido ofrece el alta a mano");
  } catch (e) { failures++; log("FALLO:", e.message); }
  finally {
    try {
      await page.goto(BASE + "/login");
      await api("POST", "/api/auth/login", { email, password });
      log("cleanup", (await api("POST", "/api/privacy/delete-account", { password })).status);
    } catch (e) { log("cleanup error", e.message); }
    await browser.close();
  }
  log(failures ? `${failures} comprobaciones fallidas` : "scan OK");
  process.exitCode = failures ? 1 : 0;
})();
