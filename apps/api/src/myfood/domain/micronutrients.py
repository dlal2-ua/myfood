"""Micronutrientes completos (Fase 7): valores de referencia poblacionales
(EFSA Dietary Reference Values, adulto) para los 17 micronutrientes que ya
trae el catálogo (`etl/transform/nutrient_map.py`: `USDA_MICRO_IDS` /
`CIQUAL_MICRO_HEADERS` / `OFF_MICRO_KEYS` / `BEDCA_MICRO_EUR_NAMES`).

Mismo criterio que el resto de valores de referencia del proyecto (agua,
macros): son estimaciones poblacionales, no personalizadas — se presentan
como orientativas (R7), nunca como objetivo médico individual. Donde EFSA
diferencia por sexo de forma relevante (hierro, sobre todo) se usa el valor
correspondiente; para `sex is None` (perfil incompleto) se usa la media.
"""

MicroReference = dict[str, float]

_REFERENCE_MALE: MicroReference = {
    "vitamin_a_ug": 750,
    "vitamin_c_mg": 110,
    "vitamin_d_ug": 15,
    "vitamin_e_mg": 13,
    "vitamin_k_ug": 70,
    "thiamin_mg": 1.2,
    "riboflavin_mg": 1.6,
    "niacin_mg": 17,
    "vitamin_b6_mg": 1.7,
    "folate_ug": 330,
    "vitamin_b12_ug": 4,
    "calcium_mg": 950,
    "iron_mg": 11,
    "magnesium_mg": 350,
    "phosphorus_mg": 550,
    "potassium_mg": 3500,
    "zinc_mg": 9.4,
}

_REFERENCE_FEMALE: MicroReference = {
    **_REFERENCE_MALE,
    "vitamin_a_ug": 650,
    "vitamin_c_mg": 95,
    "vitamin_e_mg": 11,
    "vitamin_k_ug": 60,
    "thiamin_mg": 1.1,
    "niacin_mg": 13,
    "vitamin_b6_mg": 1.6,
    "iron_mg": 16,  # premenopáusica — EFSA da un rango amplio, se usa el techo
    "magnesium_mg": 300,
    "zinc_mg": 7.5,
}

NUTRIENT_LABELS: dict[str, str] = {
    "vitamin_a_ug": "Vitamina A",
    "vitamin_c_mg": "Vitamina C",
    "vitamin_d_ug": "Vitamina D",
    "vitamin_e_mg": "Vitamina E",
    "vitamin_k_ug": "Vitamina K",
    "thiamin_mg": "Tiamina (B1)",
    "riboflavin_mg": "Riboflavina (B2)",
    "niacin_mg": "Niacina (B3)",
    "vitamin_b6_mg": "Vitamina B6",
    "folate_ug": "Folato (B9)",
    "vitamin_b12_ug": "Vitamina B12",
    "calcium_mg": "Calcio",
    "iron_mg": "Hierro",
    "magnesium_mg": "Magnesio",
    "phosphorus_mg": "Fósforo",
    "potassium_mg": "Potasio",
    "zinc_mg": "Zinc",
}


def reference_for_sex(sex: str | None) -> MicroReference:
    if sex == "male":
        return _REFERENCE_MALE
    if sex == "female":
        return _REFERENCE_FEMALE
    # Perfil incompleto: media de ambas referencias, mejor que no mostrar nada.
    return {
        key: round((_REFERENCE_MALE[key] + _REFERENCE_FEMALE[key]) / 2, 2)
        for key in _REFERENCE_MALE
    }


def sum_micros(entries_micros: list[dict]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for micros in entries_micros:
        for key, value in micros.items():
            totals[key] = totals.get(key, 0.0) + float(value)
    return {key: round(value, 3) for key, value in totals.items()}
