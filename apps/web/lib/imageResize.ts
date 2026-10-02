/** Reduce una foto en el propio dispositivo antes de subirla.
 *
 * Un móvil actual hace fotos de 5 a 15 MB, y el servidor las va a dejar en 1024 px de todas
 * formas: subirlas enteras por datos móviles era lo más lento del registro por foto, y por
 * encima de 10 MB ni siquiera entraban. A 1600 px de lado mayor pesan unos cientos de KB.
 *
 * Si el navegador no sabe hacerlo (o la imagen no se deja leer), se devuelve el fichero tal
 * cual: el servidor decide. Nunca es motivo para no poder registrar una comida.
 */
export async function shrinkImage(file: File, maxSide = 1600, quality = 0.85): Promise<Blob> {
  if (typeof createImageBitmap !== "function" || typeof document === "undefined") return file;
  let bitmap: ImageBitmap;
  try {
    // `from-image`: respeta la orientación del EXIF, que es como el móvil dice que la foto
    // está en vertical.
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    return file;
  }
  try {
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    // Ya es pequeña y es un JPEG: recomprimirla solo la empeoraría.
    if (scale === 1 && file.type === "image/jpeg" && file.size < 1_500_000) return file;
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const context = canvas.getContext("2d");
    if (!context) return file;
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", quality),
    );
    return blob && blob.size > 0 ? blob : file;
  } finally {
    bitmap.close();
  }
}
