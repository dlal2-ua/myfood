// Registro por foto de punta a punta, en un navegador de verdad: se elige una foto en el
// panel del Diario, la pantalla la reduce antes de subirla, el modelo la mira y devuelve cada
// plato entero con su desglose en gramos, el catálogo afina cada ingrediente que reconoce, y
// al aceptar queda apuntado con sus micronutrientes.
//
// No entra en `pnpm e2e`: gasta cuota de iafood y necesita una foto de comida y que alguien
// le active la IA a la cuenta desechable (nacen con `ai_enabled=false`).
//
//   PHOTO=/ruta/bocadillo.jpg INVITE_CODE=$(scripts/e2e-invite.sh) CHROME_PATH=... \
//   ENABLE_AI_CMD='sudo docker exec infra-postgres-1 psql -U myfood -d myfood -q -c \
//     "UPDATE users SET ai_enabled = true WHERE email = '\''{email}'\''"' \
//   node e2e/plate-photo.cjs
//
// `EXPECT` (opcional): palabras que tienen que salir entre los platos y sus ingredientes,
// separadas por comas («jamon,pan»). Sin tildes.
const { execSync } = require("node:child_process");
const { chromium } = require("playwright-core");

const BASE = process.env.BASE_URL || "https://myfood.cartagena.dpdns.org";
const INVITE_CODE = process.env.INVITE_CODE || "";
const PHOTO = process.env.PHOTO;
const ENABLE_AI_CMD = process.env.ENABLE_AI_CMD || "";
const EXPECT = (process.env.EXPECT || "").split(",").map((w) => w.trim()).filter(Boolean);
const OUT = process.env.OUT || ".";
const rnd = Math.random().toString(36).slice(2, 10);
const email = `e2e-foto-${rnd}@test.myfood`, password = "correcthorse-" + rnd;
const log = (...a) => console.log(...a);
const failures = [];
const check = (ok, what) => { log(ok ? "  ok " : "  FALLA", what); if (!ok) failures.push(what); };
const plain = (text) => text.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();

(async () => {
  if (!PHOTO) throw new Error("falta PHOTO: una foto de comida (jpg, png o webp)");
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH, args: ["--no-sandbox"] });
  const page = await (await browser.newContext({ viewport: { width: 412, height: 915 } })).newPage();
  page.on("pageerror", (e) => { log("PAGEERROR", e.message); failures.push("error de página: " + e.message); });
  // Lo que de verdad se sube: el multipart no se puede leer desde fuera.
  await page.addInitScript(() => {
    const realFetch = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const image = init?.body instanceof FormData ? init.body.get("image") : null;
      if (image instanceof Blob) window.__photoUpload = { type: image.type, size: image.size };
      return realFetch(input, init);
    };
  });
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const r = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    let j = null; try { j = await r.json(); } catch {}
    return { status: r.status, body: j };
  }, { method, path, body });
  const shot = (name) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true }).catch(() => {});

  try {
    await page.goto(BASE + "/login");
    const reg = await api("POST", "/api/auth/register", { email, password, display_name: "E2E foto", invite_code: INVITE_CODE });
    check(reg.status === 201 || reg.status === 200, `registro (${reg.status})`);
    await api("POST", "/api/consents", { kind: "health_data", version: "v1" });
    await api("POST", "/api/consents", { kind: "ai_processing", version: "v1" });
    if (ENABLE_AI_CMD) execSync(ENABLE_AI_CMD.replaceAll("{email}", email), { stdio: "ignore" });

    log("1. foto en el Diario");
    await page.goto(BASE + "/log", { waitUntil: "networkidle" });
    const started = Date.now();
    const [created] = await Promise.all([
      page.waitForResponse((r) => r.url().endsWith("/api/log/photo"), { timeout: 60000 }),
      // El selector de la galería: el de la cámara lleva `capture` y un navegador sin
      // cámara no tiene nada que abrir.
      page.locator('#foto input[type="file"]:not([capture])').setInputFiles(PHOTO),
    ]);
    const upload = await page.evaluate(() => window.__photoUpload || null);
    check(created.status() === 202, `el servidor acepta la foto (${created.status()})`);
    check(!!upload && upload.type === "image/jpeg" && upload.size < 1_500_000, `se reduce antes de subirla (${upload?.size} bytes)`);

    await page.locator("#foto").getByText("¿Lo apunto así?").waitFor({ timeout: 110000 });
    const seconds = ((Date.now() - started) / 1000).toFixed(1);
    const session = await api("GET", `/api/ai/sessions/${(await created.json()).id}`);
    const response = session.body?.response_payload;
    const items = response?.proposal?.payload?.items || [];
    log(`   ${seconds} s · estado ${session.body?.status}`);
    for (const item of items) {
      log(`   • ${item.name}: ${item.grams} g, ${Math.round(item.kcal)} kcal${item.catalog ? ` ✓ ${item.catalog}` : ""}`);
      for (const c of item.components || []) log(`       - ${c.name}: ${c.grams} g, ${c.kcal} kcal${c.catalog ? ` ✓ ${c.catalog}` : " (estimado)"}`);
    }
    if (response?.pregunta) log("   pregunta:", response.pregunta);
    check(session.body?.status === "succeeded" && items.length > 0, `la foto se analiza sin errores (${items.length} platos)`);
    check(items.every((i) => i.estimated && i.grams > 0 && i.kcal >= 0), "cada plato con sus gramos y sus calorías, como estimación");
    const parts = items.flatMap((i) => i.components || []);
    check(parts.length === 0 || parts.every((c) => c.grams > 0), "cada ingrediente del desglose lleva sus gramos");
    const confirmed = parts.filter((c) => c.catalog).length + items.filter((i) => i.catalog).length;
    check(confirmed > 0, `el catálogo afina lo que reconoce (${confirmed} de ${parts.length + items.filter((i) => !(i.components || []).length).length})`);
    check(items.some((i) => Object.keys(i.micros || {}).length > 0), "y aporta micronutrientes");
    const everything = plain(items.map((i) => [i.name, ...(i.components || []).map((c) => c.name)].join(" ")).join(" "));
    for (const word of EXPECT) check(everything.includes(plain(word)), `reconoce «${word}»`);

    const card = await page.locator("#foto").innerText();
    check(/aprox\. \d+ kcal/.test(card) && /estimación orientativa/.test(card), "la tarjeta lo enseña como «aprox.»");
    check(parts.length === 0 || /\d+ g\s+\d+ kcal/.test(card.replace(/\n/g, " ")), "con los gramos de cada ingrediente a la vista");
    await shot("foto-1-propuesta");

    log("2. aceptar");
    await Promise.all([
      page.waitForResponse((r) => /\/api\/ai\/proposals\/.+\/approve$/.test(r.url()) && r.status() === 200, { timeout: 20000 }),
      page.locator("#foto").getByRole("button", { name: /Sí, apúntalo/ }).click(),
    ]);
    await page.locator("#foto").getByText(/^Apuntado/).waitFor({ timeout: 10000 });
    const today = await page.evaluate(() => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; });
    const day = await api("GET", `/api/log?date=${today}`);
    const entries = day.body?.food || [];
    check(entries.length === items.length && entries.every((e) => e.entry_source === "ai_estimate"), `el diario tiene los ${items.length} platos, como estimaciones`);
    const micros = await api("GET", `/api/log/micronutrients?date=${today}`);
    check((micros.body?.nutrients || []).some((nutrient) => nutrient.amount > 0), "el panel de micronutrientes ya no cuenta cero");
    await page.waitForTimeout(800);
    await shot("foto-2-diario");
  } catch (e) {
    log("FALLO:", e.message);
    failures.push(e.message);
    await shot("foto-fallo");
  } finally {
    try {
      await page.goto(BASE + "/login");
      await api("POST", "/api/auth/login", { email, password });
      const d = await api("POST", "/api/privacy/delete-account", { password });
      log("cleanup", d.status);
    } catch (e) { log("cleanup error", e.message); }
    await browser.close();
    log(failures.length ? `\n${failures.length} comprobaciones fallidas` : "\nTODO OK");
    process.exitCode = failures.length ? 1 : 0;
  }
})();
