/** Raciones en la pantalla de registro: «2 huevos», «1 vaso», «150 g».
 *
 * Los gramos de cada ración los da el servidor (`GET /foods/{id}` → `portions`), nunca esta
 * capa: aquí solo se multiplica por la cantidad que escribe el usuario y se redondea para
 * enseñarlo. Así el mismo alimento pesa lo mismo se registre por donde se registre.
 */

export interface Portion {
  key: string;
  label: string;
  /** Lo que pesa UNA de estas raciones. Para la opción «gramos» vale 1. */
  grams: number;
}

export const GRAMS_KEY = "g";

/** Gramos que se van a registrar. Se redondea a un decimal: el API acepta decimales, pero
 * «112.49999999 g» en pantalla no ayuda a nadie. */
export function toGrams(quantity: number, portion: Portion): number {
  if (!Number.isFinite(quantity) || quantity <= 0) return 0;
  return Math.round(quantity * portion.grams * 10) / 10;
}

/** Cuántas raciones son unos gramos dados — para no perder la cantidad al cambiar de medida.
 * Al pasar a gramos sueltos, la cantidad pasa a ser el propio gramaje. */
export function toQuantity(grams: number, portion: Portion): number {
  if (portion.grams <= 0) return grams;
  return Math.round((grams / portion.grams) * 100) / 100;
}

/** Cómo se lee la cantidad elegida: «2 huevos (120 g)», «150 g». */
export function describeAmount(quantity: number, portion: Portion): string {
  const grams = toGrams(quantity, portion);
  if (portion.key === GRAMS_KEY) return `${formatNumber(grams)} g`;
  const plural = quantity === 1 ? portion.label : pluralize(portion.label);
  return `${formatNumber(quantity)} ${plural} (${formatNumber(grams)} g)`;
}

/** Plural español de las medidas que se usan aquí (vaso→vasos, cucharada→cucharadas). */
export function pluralize(label: string): string {
  if (!label) return label;
  const last = label[label.length - 1].toLowerCase();
  if ("aeiou".includes(last)) return `${label}s`;
  if (last === "z") return `${label.slice(0, -1)}ces`;
  return `${label}es`;
}

/** Hasta dos decimales, sin ceros de relleno y con la coma decimal española. */
export function formatNumber(value: number): string {
  return String(Math.round(value * 100) / 100).replace(".", ",");
}

/** Tope que acepta el API por entrada (`grams: le=5000`). */
export const MAX_GRAMS = 5000;

/** Qué le pasa a la cantidad elegida, o `null` si está bien.
 *
 * Existe porque con medidas caseras es fácil escribir en la casilla de cantidad un número
 * pensado en gramos: «150» con la medida «filete» son 22,5 kg. Antes eso solo se descubría
 * al guardar, con un «Error 422» del servidor que no explicaba nada. */
export function amountProblem(grams: number): string | null {
  if (!Number.isFinite(grams) || grams <= 0) return "Pon una cantidad mayor que cero.";
  if (grams > MAX_GRAMS) {
    return `Son ${formatNumber(grams)} g, más de los ${MAX_GRAMS} g que admite una entrada. ` +
      "¿Querías esa cantidad en gramos? Cambia la medida a «gramos».";
  }
  return null;
}

export interface Per100g {
  kcal_100g: number | null;
  protein_100g: number | null;
  carbs_100g: number | null;
  fat_100g: number | null;
}

export interface MacroAmounts {
  kcal: number;
  protein: number;
  carbs: number;
  fat: number;
}

/** Lo que aportan unos gramos concretos. Es la MISMA cuenta que hace el API al guardar
 * (valor por 100 g × gramos ÷ 100), solo que aquí sirve para verlo antes de confirmar: lo
 * que se guarda siempre lo calcula el servidor. */
export function macrosFor(per100g: Per100g, grams: number): MacroAmounts {
  const scale = grams / 100;
  const at = (value: number | null) => Math.round((value ?? 0) * scale * 10) / 10;
  return {
    kcal: Math.round((per100g.kcal_100g ?? 0) * scale),
    protein: at(per100g.protein_100g),
    carbs: at(per100g.carbs_100g),
    fat: at(per100g.fat_100g),
  };
}

/** La ración que hay que preseleccionar para unos gramos ya elegidos (al editar una entrada
 * existente): la que dé una cantidad redonda, y gramos si ninguna encaja. */
export function portionForGrams(portions: Portion[], grams: number): Portion {
  const fallback = portions.find((p) => p.key === GRAMS_KEY) ?? portions[portions.length - 1];
  if (!fallback) return { key: GRAMS_KEY, label: "gramos", grams: 1 };
  const exact = portions.find(
    (p) => p.key !== GRAMS_KEY && p.grams > 0 && Math.abs((grams / p.grams) % 1) < 0.01,
  );
  return exact ?? fallback;
}
