import { Leaf } from "lucide-react";

/** Marca de MyFood: una hoja sobre un degradado verde-turquesa. */
export function Logo({ size = 36, showName = true }: { size?: number; showName?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <span
        aria-hidden="true"
        className="grid place-items-center rounded-xl bg-gradient-to-br from-teal-600 to-emerald-400 text-white shadow-sm"
        style={{ width: size, height: size }}
      >
        <Leaf size={Math.round(size * 0.56)} strokeWidth={2.4} />
      </span>
      {showName && <span className="text-lg font-extrabold tracking-tight">MyFood</span>}
    </span>
  );
}
