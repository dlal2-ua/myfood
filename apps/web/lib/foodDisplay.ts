/** La marca de OFF es una lista («Hacendado, MERCADONA»): para mostrar, la primera etiqueta. Si es
 * el nombre del propio supermercado no se repite. */
export function brandLabel(brand: string | null | undefined, supermarket?: string | null): string | null {
  const first = brand?.split(",")[0]?.trim();
  if (!first) return null;
  if (supermarket && first.toLowerCase() === supermarket.toLowerCase()) return null;
  return first;
}

/** «23 g» sin decimales inútiles: 23, 3.6, 0.5. */
export function grams(value: number | null | undefined): string {
  if (value == null) return "—";
  const rounded = Math.round(value * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded : rounded.toFixed(1)} g`;
}
