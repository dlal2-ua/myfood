import type { CapacitorConfig } from "@capacitor/cli";

// La app Next.js (`apps/web`) ya está desplegada y sirve sesiones,
// middleware de auth y llamadas a la API — envolverla estáticamente
// (`webDir` como contenido real) no tiene sentido para una app con
// sesión de servidor. Este wrapper de Capacitor es solo un WebView
// nativo apuntando al sitio ya en producción (`server.url`); lo único
// que aporta la capa nativa es el puente a Health Connect (sección de
// wearables, Fase 6), inaccesible desde la web.
const config: CapacitorConfig = {
  appId: "org.dlal2ua.myfood",
  appName: "MyFood",
  webDir: "www",
  server: {
    url: "https://myfood.cartagena.dpdns.org",
    cleartext: false,
  },
};

export default config;
