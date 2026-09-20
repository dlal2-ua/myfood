/** Etiquetas y unidades de los micronutrientes de `foods.micros` (clave = `<nombre>_<unidad>`). */
export const MICRO_LABELS: Record<string, string> = {
  vitamin_a_ug: "Vitamina A",
  vitamin_c_mg: "Vitamina C",
  vitamin_d_ug: "Vitamina D",
  vitamin_e_mg: "Vitamina E",
  vitamin_k_ug: "Vitamina K",
  thiamin_mg: "Tiamina (B1)",
  riboflavin_mg: "Riboflavina (B2)",
  niacin_mg: "Niacina (B3)",
  vitamin_b6_mg: "Vitamina B6",
  folate_ug: "Folato (B9)",
  vitamin_b12_ug: "Vitamina B12",
  calcium_mg: "Calcio",
  iron_mg: "Hierro",
  magnesium_mg: "Magnesio",
  phosphorus_mg: "Fósforo",
  potassium_mg: "Potasio",
  zinc_mg: "Zinc",
};

export function microUnit(key: string): string {
  const unit = key.slice(key.lastIndexOf("_") + 1);
  return unit === "ug" ? "µg" : unit;
}
