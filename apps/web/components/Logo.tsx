/** Marca de MyFood: los tres rombos entrelazados sobre una ficha blanca (el dibujo tiene trazos
 * oscuros que no se leerían sobre el tema oscuro). */
export function Logo({ size = 36, showName = true }: { size?: number; showName?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <span
        aria-hidden="true"
        className="grid shrink-0 place-items-center rounded-xl bg-white p-1 shadow-sm ring-1 ring-black/10"
        style={{ height: size, width: Math.round(size * 1.25) }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- imagen estática de marca, ya optimizada */}
        <img src="/brand/logo-mark.png" alt="" width={256} height={195} className="h-full w-full object-contain" />
      </span>
      {showName && <span className="text-lg font-extrabold tracking-tight">MyFood</span>}
    </span>
  );
}
