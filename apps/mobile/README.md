# MyFood Mobile (Fase 6)

Envoltorio nativo de Android hecho con [Capacitor](https://capacitorjs.com/).
No sirve contenido propio: el `WebView` carga directamente
`https://myfood.cartagena.dpdns.org` (ver `capacitor.config.ts`) — la app
Next.js de `apps/web` sigue siendo la única fuente de la interfaz. Lo único
que aporta esta capa nativa es el puente a APIs de Android inaccesibles
desde la web, empezando por Health Connect (wearables, sección de la
especificación de la Fase 6).

## Requisitos para compilar

- JDK 21 (`sudo apt install openjdk-21-jdk`)
- Android SDK cmdline-tools, con `platforms;android-36` y
  `build-tools;36.0.0` instalados vía `sdkmanager`
- Variables de entorno:
  ```bash
  export ANDROID_HOME=/opt/android-sdk
  export ANDROID_SDK_ROOT=/opt/android-sdk
  export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
  export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"
  ```

## Compilar un APK de depuración

```bash
pnpm install
pnpm sync           # cap sync android — por si cambia capacitor.config.ts
cd android && ./gradlew assembleDebug
```

El APK queda en `android/app/build/outputs/apk/debug/app-debug.apk`, listo
para sideload (autofirmado por Gradle, no requiere keystore propia para
depuración).

## Iconos y pantalla de arranque

Los iconos del lanzador y la pantalla de arranque (`android/app/src/main/res/mipmap-*` y `drawable*/splash.png`) se generan a partir del logo de la marca con `scripts/build_brand_assets.py` (ver `docs/brand/README.md`); no los edites a mano.
