/** Las cuatro fórmulas de metabolismo basal que ofrece el perfil, explicadas, y cuál le
 * conviene a cada persona según los datos que tenga registrados.
 *
 * El cálculo en sí vive en el API (`domain/formulas.py`, R1: los números nunca los pone el
 * frontend). Aquí solo está lo que hay que contarle al usuario para que elija con criterio:
 * qué mide cada fórmula, qué datos le hacen falta y cuál da la estimación más fiable con lo
 * que ya tiene. «Recomendada» significa la más precisa según la literatura para ese caso,
 * no un consejo médico.
 */

export type BmrFormulaKey = "mifflin" | "katch" | "cunningham" | "harris";

export interface BmrFormulaInfo {
  key: BmrFormulaKey;
  label: string;
  /** Qué hace, en una frase. */
  description: string;
  /** Qué datos necesita para poder calcularse. */
  needs: string;
  /** Necesita el %grasa corporal, que solo está si se ha medido. */
  needsBodyFat: boolean;
}

export const BMR_FORMULAS: BmrFormulaInfo[] = [
  {
    key: "mifflin",
    label: "Mifflin-St Jeor",
    description:
      "Estima el gasto en reposo a partir de peso, estatura, edad y sexo. Es la fórmula " +
      "general más contrastada y la que menos se desvía en la mayoría de personas.",
    needs: "Peso, estatura, edad y sexo.",
    needsBodyFat: false,
  },
  {
    key: "katch",
    label: "Katch-McArdle",
    description:
      "Calcula el gasto a partir de la masa magra, no del peso total, así que distingue " +
      "entre dos personas del mismo peso con distinta composición corporal.",
    needs: "Peso y %grasa corporal medido.",
    needsBodyFat: true,
  },
  {
    key: "cunningham",
    label: "Cunningham",
    description:
      "También parte de la masa magra, pero da cifras algo más altas que Katch-McArdle. " +
      "Se usa sobre todo con deportistas de mucho entrenamiento.",
    needs: "Peso y %grasa corporal medido.",
    needsBodyFat: true,
  },
  {
    key: "harris",
    label: "Harris-Benedict",
    description:
      "La fórmula clásica, de 1919 y revisada en 1984. Se mantiene por comparar con datos " +
      "antiguos: tiende a estimar un poco por encima de las demás.",
    needs: "Peso, estatura, edad y sexo.",
    needsBodyFat: false,
  },
];

export function formulaInfo(key: BmrFormulaKey): BmrFormulaInfo {
  return BMR_FORMULAS.find((f) => f.key === key) ?? BMR_FORMULAS[0];
}

/** La fórmula que mejor estima con los datos que hay registrados.
 *
 * Con el %grasa corporal medido, las basadas en masa magra afinan más porque separan el
 * músculo de la grasa; se elige Katch-McArdle y no Cunningham porque esta última está
 * ajustada a deportistas y en el resto de casos se va por arriba. Sin ese dato, la masa
 * magra habría que inventarla, así que la mejor es Mifflin-St Jeor. */
export function recommendedFormula(hasBodyFatPct: boolean): BmrFormulaKey {
  return hasBodyFatPct ? "katch" : "mifflin";
}

/** Por qué se recomienda esa, en una frase para la pantalla. */
export function recommendationReason(hasBodyFatPct: boolean): string {
  return hasBodyFatPct
    ? "Tienes tu %grasa corporal registrado, así que se puede calcular sobre tu masa magra: " +
        "es la estimación más ajustada a tu caso."
    : "Es la más fiable sin tener tu %grasa corporal. Si lo mides y lo registras en Medidas, " +
        "Katch-McArdle afinará más.";
}

/** `true` si la fórmula elegida no se puede calcular con los datos registrados: el API
 * respondería 422 y el usuario solo vería un error al pulsar «Calcular». */
export function isUnavailable(key: BmrFormulaKey, hasBodyFatPct: boolean): boolean {
  return formulaInfo(key).needsBodyFat && !hasBodyFatPct;
}
