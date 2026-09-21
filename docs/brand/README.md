# Marca de MyFood

`myfood-logo-original.jpg` es el logo oficial (tres rombos verdes entrelazados; el central lleva
hojas y frutas). Es la portada de la web y de ahí salen todos los iconos.

Para regenerar todo tras cambiar el original:

```bash
apps/api/.venv/bin/python scripts/build_brand_assets.py
```

Genera, con fondo blanco y el dibujo centrado:

| Dónde | Ficheros |
|---|---|
| Web (`apps/web/public`) | `icon-192.png`, `icon-512.png`, `icon-maskable-512.png` (con margen de seguridad), `apple-icon.png`, `favicon.ico`, `badge-96.png` (silueta blanca de los avisos), `brand/logo-mark.png` (cabecera) y `brand/logo-cover.png` (portada) |
| Android (`apps/mobile/android/app/src/main/res`) | `mipmap-*/ic_launcher.png`, `ic_launcher_round.png`, `ic_launcher_foreground.png` (icono adaptativo, fondo blanco en `values/ic_launcher_background.xml`) y `drawable*/splash.png` (pantalla de arranque) |

Tras regenerar hay que volver a compilar el APK (`apps/mobile/README.md`) y, si cambian los
iconos de la web, subir `VERSION` en `apps/web/public/sw.js` para que las instalaciones existentes
descarguen los nuevos.
