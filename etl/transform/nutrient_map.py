"""Tabla de equivalencias de nutrientes (documento 2, sección 11.2).

Mapeo explícito por ID (USDA) o por cabecera exacta (CIQUAL), nunca por
coincidencia de nombre. Verificado contra los dumps reales el 2026-09-11:
- USDA: `FoodData_Central_foundation_food_json_*` / `..._sr_legacy_food_json_*`
- CIQUAL: tabla Excel 2020 (data.gouv.fr, hoja "compo")
"""

# --- USDA (Foundation + SR Legacy) ------------------------------------------
# USDA usa IDs numéricos de nutriente (campo `nutrient.id`, no `nutrient.number`).
USDA_MACRO_IDS: dict[int, str] = {
    1008: "kcal_100g",  # Energy (kcal) — NUNCA 1062 (kJ)
    1003: "protein_100g",
    1004: "fat_100g",
    1258: "saturated_100g",
    1005: "carbs_100g",
    1079: "fiber_100g",
}

# Dos IDs de azúcar total coexisten en el dump ("Sugars, Total" y "Total
# Sugars" — NLEA); se prueban en este orden y se usa el primero presente.
USDA_SUGARS_ID_PRIORITY: tuple[int, ...] = (2000, 1063)

# Sodio en mg -> sal en g (factor NaCl/Na = 2.5), no viene directo en USDA.
USDA_SODIUM_ID = 1093

# Micronutrientes curados para el JSONB `micros` (sección 6.3). Subconjunto
# común y estable entre Foundation y SR Legacy — no es la lista completa de
# ~150 nutrientes que trae USDA, solo los relevantes para MyFood.
USDA_MICRO_IDS: dict[int, str] = {
    1106: "vitamin_a_ug",  # RAE, preferido sobre 1104 (IU, unidad no comparable)
    1162: "vitamin_c_mg",
    1114: "vitamin_d_ug",
    1109: "vitamin_e_mg",
    1185: "vitamin_k_ug",
    1165: "thiamin_mg",
    1166: "riboflavin_mg",
    1167: "niacin_mg",
    1175: "vitamin_b6_mg",
    1177: "folate_ug",
    1178: "vitamin_b12_ug",
    1087: "calcium_mg",
    1089: "iron_mg",
    1090: "magnesium_mg",
    1091: "phosphorus_mg",
    1092: "potassium_mg",
    1095: "zinc_mg",
}

# --- CIQUAL (ANSES, Francia — refuerzo europeo) -----------------------------
# Cabeceras exactas de la hoja "compo" del Excel 2020. CIQUAL da la sal
# directamente en g/100g (no hace falta convertir desde sodio, a diferencia
# de USDA). Cuando existen dos columnas para el mismo nutriente (p. ej. dos
# métodos de cálculo de energía o proteína), se usa la primera de la tabla
# — el propio orden de CIQUAL las lista con su método de referencia primero.
CIQUAL_MACRO_HEADERS: dict[str, str] = {
    "Energie, Règlement UE N° 1169/2011 (kcal/100 g)": "kcal_100g",
    "Protéines, N x facteur de Jones (g/100 g)": "protein_100g",
    "Lipides (g/100 g)": "fat_100g",
    "AG saturés (g/100 g)": "saturated_100g",
    "Glucides (g/100 g)": "carbs_100g",
    "Sucres (g/100 g)": "sugars_100g",
    "Fibres alimentaires (g/100 g)": "fiber_100g",
    "Sel chlorure de sodium (g/100 g)": "salt_100g",
}

CIQUAL_MICRO_HEADERS: dict[str, str] = {
    "Calcium (mg/100 g)": "calcium_mg",
    "Fer (mg/100 g)": "iron_mg",
    "Magnésium (mg/100 g)": "magnesium_mg",
    "Phosphore (mg/100 g)": "phosphorus_mg",
    "Potassium (mg/100 g)": "potassium_mg",
    "Zinc (mg/100 g)": "zinc_mg",
    "Vitamine D (µg/100 g)": "vitamin_d_ug",
    "Vitamine E (mg/100 g)": "vitamin_e_mg",
    "Vitamine C (mg/100 g)": "vitamin_c_mg",
    "Vitamine B1 ou Thiamine (mg/100 g)": "thiamin_mg",
    "Vitamine B2 ou Riboflavine (mg/100 g)": "riboflavin_mg",
    "Vitamine B3 ou PP ou Niacine (mg/100 g)": "niacin_mg",
    "Vitamine B6 (mg/100 g)": "vitamin_b6_mg",
    "Vitamine B9 ou Folates totaux (µg/100 g)": "folate_ug",
    "Vitamine B12 (µg/100 g)": "vitamin_b12_ug",
    # Rétinol puro, no el RAE combinado (retinol + betacaroteno) de USDA —
    # CIQUAL no publica un RAE ya calculado y no nos corresponde inventarlo.
    "Rétinol (µg/100 g)": "vitamin_a_ug",
}
