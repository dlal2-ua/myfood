import type { FoodSearchItem } from "@/lib/types";

/** El nombre que se enseña en una lista.
 *
 * Los nombres de USDA y CIQUAL son fieles a la fuente y, en una lista, ilegibles: «Huevo,
 * entero, crudo, congelado, salado, pasteurizado» se lee truncado y no dice nada. `name_short`
 * lo rellena `etl/short_names.py`; mientras esté vacío se usa el de la fuente, que es lo que
 * pasaba hasta ahora.
 *
 * La ficha del alimento sigue enseñando `name_es`: es el que cita la licencia. */
export function listName(item: Pick<FoodSearchItem, "name_es" | "name_short">): string {
  return item.name_short || item.name_es;
}
