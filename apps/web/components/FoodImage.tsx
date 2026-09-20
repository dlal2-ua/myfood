/** Miniatura de un alimento. `/api/foods/{id}/image` sirve siempre algo (la imagen
 * cacheada o el placeholder de su categoría, con 200 OK), así que nunca hay un hueco
 * roto; `loading="lazy"` evita pedir las de los alimentos que no se ven. */
export function FoodImage({
  foodId,
  size = 100,
  px = 40,
  className = "",
}: {
  foodId: string;
  size?: 100 | 200 | 400;
  /** Lado en píxeles CSS con el que se pinta. */
  px?: number;
  className?: string;
}) {
  return (
    // eslint-disable-next-line @next/next/no-img-element -- el proxy ya entrega WebP redimensionado y cacheado
    <img
      src={`/api/foods/${foodId}/image?type=front&size=${size}`}
      alt=""
      width={px}
      height={px}
      loading="lazy"
      decoding="async"
      className={`shrink-0 rounded-lg bg-neutral-100 object-cover dark:bg-neutral-800 ${className}`}
      style={{ width: px, height: px }}
    />
  );
}
