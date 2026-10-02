// Nota de voz de punta a punta, con un navegador de verdad: se pulsa el micrófono del chat,
// Chromium «oye» un WAV por un micrófono simulado, `MediaRecorder` lo graba, se sube, Whisper
// lo transcribe y el modelo estima cada plato entero. Después se guarda un plato en el
// catálogo y se comprueba que el Diario, por texto, lo reutiliza sin llamar al modelo.
//
// No entra en `pnpm e2e`: gasta cuota de iafood y necesita un WAV con voz y que alguien le
// active la IA a la cuenta desechable (nacen con `ai_enabled=false`).
//
//   AUDIO_WAV=/ruta/frase.wav INVITE_CODE=$(scripts/e2e-invite.sh) CHROME_PATH=... \
//   ENABLE_AI_CMD='sudo docker exec infra-postgres-1 psql -U myfood -d myfood -q -c \
//     "UPDATE users SET ai_enabled = true WHERE email = '\''{email}'\''"' \
//   node e2e/chat-voice.cjs
//
// El plato que guarda en el catálogo es global y la cuenta desechable no puede borrarlo: el
// guion imprime `SAVED_FOOD_ID=<uuid>` para que quien lo lanza lo quite al terminar.
//
// Con `ONLY_VOICE=1` se queda en la nota de voz y solo enseña lo que ha salido, para probar
// otras frases. Con `EXPECT_ERROR=<código>` espera que el servidor la rechace con ese código
// (p. ej. `EMPTY_TRANSCRIPTION` con un WAV de silencio) y que la pantalla lo explique.
const { execSync } = require("node:child_process");
const { chromium } = require("playwright-core");

const BASE = process.env.BASE_URL || "https://myfood.cartagena.dpdns.org";
const INVITE_CODE = process.env.INVITE_CODE || "";
const AUDIO_WAV = process.env.AUDIO_WAV;
const AUDIO_SECONDS = Number(process.env.AUDIO_SECONDS || 9);
const ENABLE_AI_CMD = process.env.ENABLE_AI_CMD || "";
// Lo que se le escribe al Diario después: el plato guardado, para comprobar que se reutiliza.
const SAVED_DISH_TEXT = process.env.SAVED_DISH_TEXT || "a media mañana dos marineras";
const OUT = process.env.OUT || ".";
const ONLY_VOICE = process.env.ONLY_VOICE === "1";
const EXPECT_ERROR = process.env.EXPECT_ERROR || "";
const rnd = Math.random().toString(36).slice(2, 10);
const email = `e2e-voz-${rnd}@test.myfood`, password = "correcthorse-" + rnd;
const log = (...a) => console.log(...a);
const failures = [];
const check = (ok, what) => { log(ok ? "  ok " : "  FALLA", what); if (!ok) failures.push(what); };

(async () => {
  if (!AUDIO_WAV) throw new Error("falta AUDIO_WAV: un WAV con la frase que se va a dictar");
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH,
    args: [
      "--no-sandbox",
      // El permiso del micrófono se concede solo y lo que «oye» es el WAV, una sola vez.
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      `--use-file-for-fake-audio-capture=${AUDIO_WAV}%noloop`,
    ],
  });
  const context = await browser.newContext({ viewport: { width: 412, height: 915 } });
  await context.grantPermissions(["microphone"], { origin: BASE });
  const page = await context.newPage();
  // Lo que de verdad sale por `fetch`: el multipart no se puede leer desde fuera, así que se
  // apunta aquí el fichero de audio (tipo, tamaño, nombre) justo antes de enviarlo.
  await page.addInitScript(() => {
    const realFetch = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const audio = init?.body instanceof FormData ? init.body.get("audio") : null;
      if (audio instanceof File) window.__voiceUpload = { type: audio.type, size: audio.size, name: audio.name };
      return realFetch(input, init);
    };
  });
  page.on("pageerror", (e) => { log("PAGEERROR", e.message); failures.push("error de página: " + e.message); });
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const r = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    let j = null; try { j = await r.json(); } catch {}
    return { status: r.status, body: j };
  }, { method, path, body });
  const shot = (name) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true }).catch(() => {});
  let savedFoodId = null;

  try {
    await page.goto(BASE + "/login");
    const reg = await api("POST", "/api/auth/register", { email, password, display_name: "E2E voz", invite_code: INVITE_CODE });
    check(reg.status === 201 || reg.status === 200, `registro (${reg.status})`);
    await api("POST", "/api/consents", { kind: "health_data", version: "v1" });
    await api("POST", "/api/consents", { kind: "ai_processing", version: "v1" });
    if (ENABLE_AI_CMD) execSync(ENABLE_AI_CMD.replaceAll("{email}", email), { stdio: "ignore" });

    // --- 1. Grabar y enviar una nota de voz desde el botón del chat ---------------------
    log("1. nota de voz en el chat");
    await page.goto(BASE + "/chat", { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "Grabar una nota de voz" }).click();
    await page.getByRole("button", { name: "Enviar la nota de voz" }).waitFor({ timeout: 5000 });
    check(true, "el micrófono empieza a grabar");
    await page.waitForTimeout((AUDIO_SECONDS + 1) * 1000);
    const started = Date.now();
    const [response] = await Promise.all([
      page.waitForResponse((r) => r.url().endsWith("/api/chat/message"), { timeout: 110000 }),
      page.getByRole("button", { name: "Enviar la nota de voz" }).click(),
    ]);
    const seconds = ((Date.now() - started) / 1000).toFixed(1);
    const body = await response.json().catch(() => null);
    const upload = await page.evaluate(() => window.__voiceUpload || null);
    log(`   grabación: ${upload?.name} · ${upload?.type} · ${upload?.size} bytes · respuesta en ${seconds} s`);
    check(!!upload && upload.size > 1000 && /^audio\/(webm|mp4|ogg)/.test(upload.type) && /^nota\.(webm|m4a|ogg)$/.test(upload.name), "se graba audio de verdad, con su tipo y extensión reales");
    if (EXPECT_ERROR) {
      check(response.status() !== 200 && body?.error?.code === EXPECT_ERROR, `el servidor la rechaza con ${EXPECT_ERROR} (${response.status()} ${body?.error?.code})`);
      const shown = await page.getByText(body?.error?.message || "###").isVisible().catch(() => false);
      check(shown, `y la pantalla lo explica: «${body?.error?.message}»`);
      await shot("voz-error");
      return;
    }
    check(response.status() === 200, `el servidor acepta la nota (${response.status()})`);
    if (response.status() !== 200) log("   respuesta:", JSON.stringify(body));

    const history = await api("GET", "/api/chat/history?limit=10");
    const voice = (history.body || []).find((m) => m.role === "user");
    log("   transcripción:", JSON.stringify(voice?.content));
    check(voice?.source === "voice" && (voice?.content || "").length > 3, "Whisper transcribe la nota y queda como mensaje de voz");
    log("   respuesta:", JSON.stringify(body?.message));

    const items = body?.proposal?.payload?.items || [];
    log("   platos:", items.map((i) => `${i.name} ≈${Math.round(i.kcal)} kcal → ${i.meal_type} [${(i.components || []).map((c) => c.name).join(", ")}]`).join(" | "));
    if (ONLY_VOICE) {
      if (body?.proposal) await page.getByText("¿Lo apunto así?").waitFor({ timeout: 10000 });
      await shot("voz-solo");
      return;
    }
    check(body?.proposal?.scope === "diary", "deja una propuesta de diario");
    check(items.length === 3, `tres platos, no una lista de ingredientes (${items.length})`);
    check(items.every((i) => i.estimated), "todo va marcado como estimación");
    const bocadillo = items.find((i) => /bocadillo/i.test(i.name));
    check(!!bocadillo && (bocadillo.components || []).length >= 3, "el bocadillo es un conjunto, con su desglose");
    const marinera = items.find((i) => /marinera/i.test(i.name));
    check(!!marinera && (marinera.components || []).some((c) => /ensaladilla/i.test(c.name)), "la marinera se reconoce como plato y se desglosa");
    check(/kcal en total/.test(body?.message || "") && /aprox\./i.test(body?.message || ""), "la respuesta trae el total aproximado y el desglose");

    await page.getByText("¿Lo apunto así?").waitFor({ timeout: 10000 });
    const card = await page.locator("text=¿Lo apunto así?").locator("..").innerText();
    check(/aprox\. \d+ kcal/.test(card) && /estimación orientativa/.test(card), "la tarjeta enseña las cifras como «aprox.»");
    await shot("voz-1-propuesta");

    // --- 2. Aceptar guardando la marinera en el catálogo ---------------------------------
    log("2. aceptar y guardar en el catálogo");
    await page.getByLabel(/Guardar «Marinera/i).check();
    await Promise.all([
      page.waitForResponse((r) => /\/api\/ai\/proposals\/.+\/approve$/.test(r.url()) && r.status() === 200, { timeout: 20000 }),
      page.getByRole("button", { name: /Sí, apúntalo y guárdalo/ }).click(),
    ]);
    await page.getByText(/guardado en el catálogo/).waitFor({ timeout: 10000 });
    const today = await page.evaluate(() => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; });
    const day = await api("GET", `/api/log?date=${today}`);
    const entries = day.body?.food || [];
    check(entries.length === 3 && entries.every((e) => e.entry_source === "ai_estimate"), `el diario tiene los tres platos, como estimaciones (${entries.length})`);
    savedFoodId = entries.find((e) => /marinera/i.test(e.food_name || ""))?.food_id || null;
    check(!!savedFoodId, "la marinera tiene ficha en el catálogo");
    if (savedFoodId) {
      const food = await api("GET", `/api/foods/${savedFoodId}`);
      check(food.body?.source === "ai_estimate" && (food.body?.components || []).length > 0, "la ficha es una estimación, con su desglose");
      const search = await api("GET", "/api/foods/search?q=marinera&limit=10");
      check((search.body?.items || []).some((i) => i.id === savedFoodId), "sale en el buscador de alimentos");
    }

    // --- 3. El Diario, por texto: reutiliza el plato guardado sin llamar al modelo -------
    log("3. el Diario reutiliza el plato guardado");
    await page.goto(BASE + "/log", { waitUntil: "networkidle" });
    const dayText = await page.locator('section[aria-label="Comidas del día"]').innerText();
    check(/aprox\. \d+\s+kcal/.test(dayText) && /estimación/.test(dayText), "el diario enseña lo estimado como «aprox.»");
    check(/ensaladilla/i.test(dayText), "y de qué se compone cada plato");
    await shot("voz-2-diario");

    const quotaBefore = await api("GET", "/api/ai/quota?scope=smart_log");
    await page.getByPlaceholder(/una marinera y una caña/).fill(SAVED_DISH_TEXT);
    const t0 = Date.now();
    const [smart] = await Promise.all([
      page.waitForResponse((r) => r.url().endsWith("/api/log/smart"), { timeout: 20000 }),
      page.getByRole("button", { name: "Estimar" }).click(),
    ]);
    const smartBody = await smart.json();
    const reused = smartBody.response_payload?.proposal?.payload?.items?.[0];
    const quotaAfter = await api("GET", "/api/ai/quota?scope=smart_log");
    check(smartBody.status === "succeeded" && smartBody.response_payload?.from_saved === true, `responde al momento, sin modelo (${Date.now() - t0} ms)`);
    check(reused?.food_id === savedFoodId && reused?.quantity === 2, "usa la estimación guardada, por dos");
    check(quotaAfter.body?.used === quotaBefore.body?.used, "y no gasta cuota");
    await page.getByText("guardado", { exact: true }).waitFor({ timeout: 5000 });
    await page.getByRole("button", { name: /Sí, apúntalo/ }).click();
    await page.getByText("Apuntado.").waitFor({ timeout: 10000 });

    // --- 4. El Diario, por texto, con algo que no está guardado: misma lógica que el chat -
    log("4. el Diario estima un plato nuevo");
    await page.getByPlaceholder(/una marinera y una caña/).fill("de cena un bocadillo de calamares y una caña");
    await page.getByRole("button", { name: "Estimar" }).click();
    await page.getByText("¿Lo apunto así?").waitFor({ timeout: 90000 });
    const diaryCard = await page.locator("text=¿Lo apunto así?").locator("..").innerText();
    log("   tarjeta:", diaryCard.replace(/\n+/g, " | ").slice(0, 400));
    check(/[Bb]ocadillo de calamares/.test(diaryCard) && /aprox\. \d+ kcal/.test(diaryCard), "el bocadillo de calamares sale entero y como «aprox.»");
    check(/cena/i.test(diaryCard), "y va a la cena, que es lo que dice el texto");
    await shot("voz-3-diario-texto");
    await page.getByRole("button", { name: "No", exact: true }).click();
  } catch (e) {
    log("FALLO:", e.message);
    failures.push(e.message);
    await shot("voz-fallo");
  } finally {
    if (savedFoodId) log(`SAVED_FOOD_ID=${savedFoodId}`);
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
