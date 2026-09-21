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
- `visual.cjs`: QA visual (no entra en `pnpm e2e`): capturas de todas las pantallas en claro/oscuro y móvil/escritorio, más comprobaciones de desbordes horizontales y errores de consola. `OUT=/ruta BASE_URL=... node e2e/visual.cjs [ruta ...]`.
