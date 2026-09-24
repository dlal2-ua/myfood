import type { FoodOrigin, QuantityKind, SmartLogItem } from "@/lib/types";

/** Compartido por el registro por texto y el de por foto: los dos enseñan lo mismo, porque
 * detrás es el mismo resolutor. */

export const ORIGIN_LABELS: Record<FoodOrigin, string> = {
  casero: "casero",
  envasado: "de paquete",
  restaurante: "de restaurante",
  desconocido: "origen sin determinar",
};

const QUANTITY_LABELS: Partial<Record<QuantityKind, string>> = {
  porcion: "porción",
  racion: "ración",
  punado: "puñado",
  cucharadita: "cucharadita",
};

/** «porción grande» — lo que el modelo entendió, para poder juzgar el gramaje de un vistazo en
 * vez de aceptar un número a ciegas. */
export function describeInterpretation(item: SmartLogItem): string | null {
  if (!item.tipo_cantidad) return null;
  const unit = QUANTITY_LABELS[item.tipo_cantidad] ?? item.tipo_cantidad;
  if (!item.tamano || item.tamano === "mediano") return unit;
  return `${unit} ${item.tamano === "grande" ? "grande" : "pequeña"}`;
}
