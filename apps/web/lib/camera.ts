/** Mensaje en español para un fallo al abrir la cámara del escáner. html5-qrcode rechaza con
 * cadenas («NotAllowedError: Permission denied»), no con `Error`, así que no basta con leer
 * `.message`. */
export function cameraErrorMessage(err: unknown): string {
  const raw = typeof err === "string" ? err : err instanceof Error ? `${err.name}: ${err.message}` : "";
  const text = raw.toLowerCase();
  if (/notallowed|permission|denied/.test(text)) {
    return "No tengo permiso para usar la cámara. Permítelo en los ajustes del navegador o escribe el código de barras a mano.";
  }
  if (/notfound|requested device not found|no camera|devicesnotfound/.test(text)) {
    return "No se ha encontrado ninguna cámara en este dispositivo. Escribe el código de barras a mano.";
  }
  if (/notreadable|trackstart|in use|could not start/.test(text)) {
    return "La cámara está siendo usada por otra aplicación. Ciérrala o escribe el código de barras a mano.";
  }
  if (/secure|https/.test(text)) {
    return "El navegador solo deja usar la cámara en conexiones seguras. Escribe el código de barras a mano.";
  }
  return "No se ha podido abrir la cámara. Escribe el código de barras a mano.";
}
