"""Vector nutricional normalizado por 100g para similitud de alimentos
(sección "Alimentos similares (sustituciones)"). Funciones puras, sin
acceso a BD — igual que `domain/formulas.py`.

## Por qué 6 dimensiones y no 5

`food_vectors.vec` (migración 0001) es `vector(6)`, pero el texto de la
especificación solo nombra 5 nutrientes: kcal, proteína, grasa,
carbohidratos, fibra. Se añade `salt_100g` (sal) como 6ª dimensión en vez
de azúcares o grasa saturada porque estos dos ya son subtipos de
dimensiones existentes (azúcares está incluido en carbohidratos, grasa
saturada en grasa total) y apenas añadirían información nueva a una
distancia L2 — la sal, en cambio, es una magnitud nutricional
independiente de las otras cinco. Además tiene mejor cobertura real en el
catálogo: comprobado contra los 21.801 alimentos reales de la BD
(2026-09-12), `salt_100g` es NOT NULL en ~97% de las filas, frente a ~87%
de `sugars_100g` y solo ~65% de `fiber_100g` (que aun así se mantiene
porque el propio enunciado la pide).

## Por qué escalado fijo y no z-score

Con z-score (media/desviación del catálogo) las distancias entre dos
alimentos cambiarían cada vez que el ETL añade filas nuevas — habría que
recalcular TODOS los vectores existentes para que las comparaciones
siguieran siendo consistentes entre sí. En su lugar se usa un escalado
fijo con cotas razonables: son cantidades "por 100g" ya acotadas por su
propia naturaleza (nadie tiene 300g de proteína en 100g de alimento), así
que cada vector se puede calcular de forma independiente, sin depender de
ninguna estadística global que cambie con el tiempo.

Sin este escalado, kcal_100g (rango real ~0-900) dominaría por completo
una distancia L2 frente a fiber_100g (rango real ~0-50): un frasco de
aceite y una lechuga podrían parecer "más distintos" solo por la
diferencia de kcal, aunque su fibra fuera idéntica. El escalado fijo mete
las 6 dimensiones en una escala comparable ~[0,1].
"""

# 900 kcal/100g ~ cota superior real (grasa pura, ~9 kcal/g * 100g).
KCAL_SCALE = 900.0
# El resto son gramos por 100g de alimento — cota natural en 100.
GRAMS_SCALE = 100.0

VECTOR_DIMENSIONS = 6


def normalize_food_vector(
    kcal_100g: float,
    protein_100g: float,
    fat_100g: float,
    carbs_100g: float,
    fiber_100g: float | None,
    salt_100g: float | None,
) -> list[float]:
    """Vector normalizado de 6 dimensiones, en el mismo orden que se
    documenta aquí y se usa en `scripts/build_food_vectors.py`:
    [kcal, proteína, grasa, carbohidratos, fibra, sal].

    `fiber_100g`/`salt_100g` pueden ser `NULL` en `food_nutrients` (no
    todas las fuentes del ETL los reportan) — se tratan como 0, igual que
    ya hace el resto del código con otros nutrientes opcionales.

    Se recorta (clamp) a [0, 1] por si algún dato real superase la cota
    de escalado (defensivo — no se espera en la práctica con datos de
    alimentos reales).
    """
    return [
        _clamp((kcal_100g or 0) / KCAL_SCALE),
        _clamp((protein_100g or 0) / GRAMS_SCALE),
        _clamp((fat_100g or 0) / GRAMS_SCALE),
        _clamp((carbs_100g or 0) / GRAMS_SCALE),
        _clamp((fiber_100g or 0) / GRAMS_SCALE),
        _clamp((salt_100g or 0) / GRAMS_SCALE),
    ]


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
