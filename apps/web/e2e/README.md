# E2E (Chromium sin interfaz)

Comprobaciones de extremo a extremo contra una instancia real de MyFood, con cuentas desechables
(`e2e-*@test.myfood`) que se borran al terminar. No están en el CI: necesitan una instancia
desplegada y un Chromium.

```bash
cd apps/web
BASE_URL=https://myfood.cartagena.dpdns.org CHROME_PATH=/ruta/a/chrome pnpm e2e
```

- `offline.cjs`: registra comida y agua sin conexión, comprueba la cola, la sincronización al
  volver la red, la idempotencia y que al salir se borran las cachés con datos de usuario.
- `ui.cjs`: ficha del alimento (fuente, licencia, porción) y «copiar día».
- `f7.cjs`: progreso, ayuno, calculadoras y exportación ZIP.
- `foods.cjs`: «Alimentos»: sugerencias al entrar, búsqueda, filtros por supermercado, tipo de alimento y nutrición, y orden.
- `chat-voice.cjs`: nota de voz de punta a punta (no entra en `pnpm e2e`: gasta cuota de iafood). Chromium graba con `MediaRecorder` un WAV que «oye» por un micrófono simulado, se sube, Whisper lo transcribe y el chat estima cada plato entero; después guarda uno en el catálogo y comprueba que el Diario lo reutiliza sin llamar al modelo. Necesita `AUDIO_WAV` (un WAV con la frase dictada) y `ENABLE_AI_CMD` para activarle la IA a la cuenta desechable; la cabecera del guion trae el comando entero. `ONLY_VOICE=1` prueba otra frase sin el resto del recorrido y `EXPECT_ERROR=EMPTY_TRANSCRIPTION` comprueba una nota en silencio.
- `plate-photo.cjs`: registro por foto de punta a punta (tampoco entra en `pnpm e2e`: gasta cuota). Sube una foto desde el panel del Diario, comprueba que se reduce antes de subirla, que cada plato vuelve entero con su desglose en gramos, que el catálogo afina lo que reconoce y aporta micronutrientes, y que al aceptar queda en el diario. Necesita `PHOTO` y `ENABLE_AI_CMD`; `EXPECT=jamon,pan` exige que reconozca esas palabras.
- `visual.cjs`: QA visual (no entra en `pnpm e2e`): capturas de todas las pantallas en claro/oscuro y móvil/escritorio, más comprobaciones de desbordes horizontales y errores de consola. `OUT=/ruta BASE_URL=... node e2e/visual.cjs [ruta ...]`.
