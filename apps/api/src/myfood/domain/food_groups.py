# ruff: noqa: E501
"""Grupo alimentario de un alimento, para que el motor de dietas arme comidas con sentido
(Fase 4) y para que las alternativas sean del mismo tipo de alimento (sección 9.1: «capa de
sentido común», pollo por pollo y no por queso curado aunque los macros cuadren).

El catálogo no trae una taxonomía común: cada fuente usa la suya (BEDCA en español, Open Food
Facts con etiquetas en inglés, USDA en inglés, CIQUAL en francés) y las categorías de OFF son
miles. Por eso el grupo se deduce del nombre y la categoría con reglas explícitas; lo que no
encaja en ninguna regla queda en `other` y el motor NO lo usa (nunca se inventa un grupo, R9).

Las reglas se evalúan en orden y gana la primera que coincide: primero las exclusiones (dulces,
bebidas, platos preparados…), después los grupos que se usan para armar comidas. Se miran antes
el nombre y solo si no dice nada, la categoría.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MEAT = "meat"
PROCESSED_MEAT = "processed_meat"
FISH = "fish"
EGG = "egg"
DAIRY = "dairy"
CHEESE = "cheese"
LEGUME = "legume"
NUTS = "nuts"
VEGETABLE = "vegetable"
FRUIT = "fruit"
GRAIN = "grain"
CEREAL = "cereal"  # cereales de desayuno, copos, muesli: solo para desayunos y meriendas
BREAD = "bread"
OIL_FAT = "oil_fat"
# Grupos que el motor no usa para armar comidas.
SWEET = "sweet"
BEVERAGE = "beverage"
SNACK = "snack"
PREPARED = "prepared"
OTHER = "other"

PLANNABLE_GROUPS = frozenset(
    {MEAT, PROCESSED_MEAT, FISH, EGG, DAIRY, CHEESE, LEGUME, NUTS, VEGETABLE, FRUIT, GRAIN, CEREAL,
     BREAD, OIL_FAT}
)


def _normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in stripped if not unicodedata.combining(c))


def _rx(*alternatives: str) -> re.Pattern[str]:
    return re.compile("|".join(alternatives))


# (grupo, patrón) en orden de prioridad. Los patrones van sobre texto sin acentos y en minúscula.
_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        OTHER,
        _rx(
            r"\bbebe\b", r"infantil", r"papilla", r"potito", r"\binfant", r"\bbaby\b", r"formula",
            r"complemento alimenticio", r"suplemento", r"proteina en polvo", r"whey",
            r"\bcoco\b", r"leche de coco", r"levadura", r"gelatina", r"colorante", r"\baroma\b",
            r"aceitunas?", r"\bolives?\b", r"\bharinas?\b", r"\bflour\b", r"almidon", r"maicena", r"\bsesos\b", r"\bcorazon\b", r"rinon", r"\blengua\b", r"callos", r"molleja", r"\btripa", r"visceras", r"\bhigado", r"\bliver\b", r"huevo de (pato|pavo|codorniz|oca|avestruz)", r"\bnata\b", r"\bcream\b", r"\bcrema\b",
        ),
    ),
    # Los cereales de desayuno llevan miel o azúcar, pero son la base de un desayuno normal.
    (CEREAL, _rx(r"cereales? (de )?desayuno", r"cereales? de desayuno", r"breakfast cereal", r"corn flakes", r"\bmuesli\b", r"copos de avena")),
    (
        SWEET,
        _rx(
            r"azucar", r"cacao", r"bombon", r"galleta", r"biscuit", r"cookie",
            r"madalena", r"madeleine", r"magdalena", r"bolleria", r"croissant", r"donut",
            r"napolitana", r"caramel", r"golosina", r"mermelada", r"confitura", r"\bjams?\b",
            r"\bmiel\b", r"digestive", r"chocolat", r"helado", r"turron", r"mazapan", r"polvoron", r"pastel", r"tarta",
            r"bizcocho", r"sirope", r"dulce", r"crema de avellana", r"hazelnut spread",
            r"barrita", r"cereal bar", r"filled cereal", r"cereales? rellen", r"flan\b",
            r"natilla", r"gominola", r"\bpalmera\b", r"ensaimada", r"crepe", r"gofre",
            r"sweetened", r"edulcorante", r"sacarina", r"stevia", r"regaliz", r"chicle",
            r"batido", r"milkshake", r"condensada", r"ice cream", r"postre", r"mousse", r"sorbete", r"yogur helado",
        ),
    ),
    (
        BEVERAGE,
        _rx(
            r"\bagua\b", r"\bwater\b", r"refresco", r"\bcola\b", r"zumo", r"juice", r"nectar",
            r"cerveza", r"\bvino\b", r"licor", r"whisky", r"\bron\b", r"ginebra", r"vodka",
            r"\bcafe\b", r"\bte\b", r"infusion", r"isotonic", r"energy drink", r"caldo",
            r"\bsidra\b", r"tonica", r"gaseosa", r"\bsoda\b", r"beverages?", r"\btea\b", r"ice tea", r"limonada", r"lemonade", r"smoothie", r"\bthe (verde|negro|rojo)",
        ),
    ),
    (PREPARED, _rx(r"\bsalsa", r"\bsauce", r"tsatsiki", r"tzatziki")),
    (
        DAIRY,
        _rx(
            r"\bleche", r"\bllet\b", r"iogurt", r"bifidus", r"\bgriego\b", r"\bpetit\b", r"\bmilk", r"yogur", r"yogurt", r"kefir", r"petit suisse", r"skyr",
            r"bebida (de |vegetal de )?(avena|soja|almendra|arroz|avellana)", r"oat based",
            r"soy (drink|milk)", r"almond (drink|milk)", r"lacteo", r"dairy",
        ),
    ),
    (BEVERAGE, _rx(r"bebida", r"drink")),
    (
        SNACK,
        _rx(
            r"patatas? fritas", r"crisps", r"\bsnacks?\b", r"aperitivo", r"ganchito", r"nachos",
            r"corn chips", r"palomitas", r"popcorn", r"\bchips\b", r"tortitas? de", r"cortezas",
            r"salty snack", r"llardons",
        ),
    ),
    (
        PREPARED,
        _rx(
            r"plato preparado", r"prepared meal", r"pizza", r"lasana", r"lasagna", r"canelon",
            r"croqueta", r"empanad", r"tortilla (de|espanola)", r"omelet", r"\bsopa\b", r"\bsoup",
            r"\bsalsa", r"sauce", r"gazpacho", r"salmorejo", r"potaje", r"guiso", r"ensaladilla",
            r"hamburguesa", r"burger", r"nuggets", r"precocina", r"sandwich", r"bocadill",
            r"kebab", r"burrito", r"\btaco", r"sushi", r"paella", r"fabada", r"puchero",
            r"rebozad", r"\bfrit[oa]s? (de|en)\b", r"relleno", r"hummus", r"humus", r"ketchup",
            r"mayonesa", r"vinagre", r"aliño", r"alino", r"pisto", r"tempura", r"san jacobo",
            r"cordon bleu", r"canapé", r"canape", r"masa (de|para)", r"rollito", r"dumpling",
            r"\bwok\b", r"burguer", r"pesto", r"focaccia", r"descatalogado", r"parrillada", r"ready meal", r"salteado", r"ravioli", r"gnocchi", r"tortellini", r"cannelloni", r"tomate frito", r"varitas", r"finger", r"palitos de", r"cocido (madrileno|gallego|completo)",
        ),
    ),
    (
        PROCESSED_MEAT,
        _rx(
            r"jamon", r"\bham\b", r"chorizo", r"salchichon", r"\bfuet\b", r"lomo embuchado",
            r"mortadela", r"salchicha", r"sausage", r"\bbacon\b", r"beicon", r"panceta",
            r"morcilla", r"butifarra", r"\bpate\b", r"foie", r"fiambre", r"cold cuts",
            r"prepared meats", r"charcut", r"embutido", r"sobrasada", r"cecina", r"pastrami",
            r"cooked turkey", r"pernil", r"\bpernil", r"pavo (cocido|en lonchas|loncheado)", r"pechuga de pavo cocida",
            r"york", r"luncheon", r"hot ?dog", r"frankfurt", r"cabeza de jabali", r"chopped",
        ),
    ),
    (OIL_FAT, _rx(r"^aceite", r"^oil\b", r"^mantequilla", r"^butter\b", r"^margarina")),
    # Antes de `legume`: las judías verdes son verdura, no legumbre.
    (VEGETABLE, _rx(r"judias verdes", r"green beans?", r"guisantes?,? (congelad|fresc|tierno|en conserva|hervid|al natural)")),
    (CEREAL, _rx(r"\bavena\b", r"\boats?\b", r"\bmuesli\b", r"\bcopos\b", r"\bgranola\b")),
    (
        GRAIN,
        _rx(
            r"\bpasta\b", r"espagueti", r"spaghetti", r"macarron", r"fideo", r"tallarin", r"noodle",
            r"\bpenne\b", r"fusilli", r"\bplumas\b", r"tagliatelle", r"\bnidos?\b", r"\blazos\b",
            r"\bcodos\b", r"\bhelices\b", r"rigatoni", r"farfalle",
        ),
    ),
    (NUTS, _rx(r"castana", r"cacahuete", r"almendra", r"avellana", r"pistacho", r"anacardo", r"\bnueces\b", r"\bnuez\b")),
    (
        BREAD,
        _rx(
            r"\bpan\b", r"\bpa\b", r"\bpan de", r"\bbread", r"tostada", r"\btoasts?\b", r"biscote", r"baguette",
            r"\bpicos\b", r"panecillo", r"\bbuns?\b", r"pan molde", r"regana", r"chapata",
            r"colines", r"\bwrap", r"\bpitas?\b", r"barra de pan", r"pan integral", r"pan de molde",
        ),
    ),
    (
        FISH,
        _rx(
            r"pescad", r"tonyina", r"sardinet", r"sardinilla", r"\bfish", r"salmon", r"\batun\b", r"\btuna\b", r"merluza", r"bacalao",
            r"lubina", r"dorada", r"sardina", r"caballa", r"anchoa", r"boqueron", r"trucha",
            r"\brape\b", r"gamba", r"langostino", r"marisco", r"mejillon", r"calamar", r"pulpo",
            r"sepia", r"almeja", r"bonito", r"pescadilla", r"lenguado", r"rodaballo", r"jurel",
            r"besugo", r"\bmero\b", r"emperador", r"panga", r"tilapia", r"surimi", r"seafood",
            r"shrimp", r"crustaceo", r"molusco", r"cigala", r"berberecho", r"chipiron", r"anguila",
            r"halibut", r"caviar", r"\bcod\b", r"haddock", r"mackerel", r"sardine", r"trout",
        ),
    ),
    (EGG, _rx(r"\bhuevos?\b", r"\beggs?\b", r"\bous\b")),
    (
        CHEESE,
        _rx(
            r"queso", r"formatge", r"cheese", r"requeson", r"mozzarella", r"\bfeta\b", r"parmes", r"cheddar",
            r"\bbrie\b", r"camembert", r"mascarpone", r"gouda", r"emmental", r"roquefort",
            r"manchego", r"ricotta", r"\bcuajada\b",
        ),
    ),
    (
        LEGUME,
        _rx(
            r"lenteja", r"garbanzo", r"judia", r"alubia", r"\bhabas?\b", r"guisante", r"\bsoja\b",
            r"\bsoy", r"chickpea", r"lentil", r"\bbeans?\b", r"\bpeas?\b", r"edamame", r"tofu",
            r"tempeh", r"frijol", r"legum", r"altramuz", r"lupin", r"pochas",
        ),
    ),
    (
        NUTS,
        _rx(
            r"\bnuez", r"nueces", r"almendra", r"avellana", r"pistacho", r"anacardo", r"cacahuete",
            r"peanut", r"\bnuts?\b", r"semilla", r"\bseeds?\b", r"pipas", r"\bchia\b", r"\blino\b",
            r"sesamo", r"\bpinones", r"frutos secos", r"castana", r"macadamia", r"\bpecan",
        ),
    ),
    (OIL_FAT, _rx(r"aceite", r"\boils?\b", r"mantequilla", r"\bbutter\b", r"margarina", r"manteca")),
    (
        GRAIN,
        _rx(
            r"\barroz\b", r"\brice\b", r"\bpasta", r"espagueti", r"spaghetti", r"macarron",
            r"fideo", r"noodle", r"cereal", r"\btrigo\b", r"wheat",
            r"centeno", r"cebada", r"quinoa", r"cuscus", r"couscous", r"harina", r"flour",
            r"semola", r"polenta", r"\bpatata", r"\bpapa\b", r"potato", r"boniato", r"batata",
            r"tapioca", r"\bmijo\b", r"bulgur", r"tallarin", r"penne", r"fusilli",
            r"\bmaiz\b (grano|hervido)", r"cereales y derivados",
        ),
    ),
    (
        VEGETABLE,
        _rx(
            r"verdura", r"hortaliza", r"vegetable", r"lechuga", r"tomate", r"cebolla", r"zanahoria",
            r"pimiento", r"calabacin", r"berenjena", r"espinaca", r"acelga", r"brocoli", r"broccoli",
            r"coliflor", r"\bcol\b", r"repollo", r"pepino", r"puerro", r"champinon", r"\bsetas?\b",
            r"esparrago", r"alcachofa", r"\bapio\b", r"remolacha", r"calabaza", r"\bnabo",
            r"rabano", r"endibia", r"escarola", r"rucula", r"canonigo", r"berro", r"ensalada",
            r"\bsalads?\b", r"maiz dulce", r"sweet corn", r"\bajo\b", r"cebolleta", r"coles de bruselas",
            r"pak choi", r"judias", r"verduras",
        ),
    ),
    (
        FRUIT,
        _rx(
            r"\bfruta", r"\bfruit", r"manzana", r"\bpera\b", r"platano", r"banana", r"naranja",
            r"mandarina", r"limon", r"fresa", r"melocoton", r"albaricoque", r"ciruela", r"cereza",
            r"\buvas?\b", r"sandia", r"melon", r"\bpina\b", r"kiwi", r"mango", r"papaya",
            r"aguacate", r"\bhigos?\b", r"granada", r"frambuesa", r"arandano", r"\bmora", r"pomelo",
            r"nectarina", r"datil", r"chirimoya", r"caqui", r"membrillo", r"compota", r"fresas",
            r"\bapple", r"\bpear\b", r"orange", r"strawberr", r"grape", r"peach", r"cherr",
        ),
    ),
    (
        MEAT,
        _rx(
            r"pollo", r"chicken", r"ternera", r"\bbeef\b", r"cerdo", r"\bpork\b", r"cordero",
            r"\blamb\b", r"pavo", r"turkey", r"conejo", r"rabbit", r"\bbuey\b", r"vacuno",
            r"\bcarne", r"\bmeats?\b", r"solomillo", r"\blomo\b", r"filete", r"entrecot",
            r"pechuga", r"muslo", r"higado", r"\bliver\b", r"\bpato\b", r"\bduck\b", r"codorniz",
            r"cabrito", r"jabali", r"\bcaza\b", r"cardos", r"chuleta", r"costilla", r"picadillo",
            r"\bpernil", r"\bpaleta", r"\bcinta de lomo",
        ),
    ),
]


# Categorías que descartan un alimento aunque su nombre suene a otro grupo («Triángulos de maíz
# sabor queso» está en «corn chips»; «Nata» en «ice creams»).
_EXCLUDING_CATEGORIES: list[tuple[str, re.Pattern[str]]] = [
    (SNACK, _rx(r"chips", r"crisps", r"snack", r"aperitiv", r"nachos", r"palomitas")),
    (BEVERAGE, _rx(r"juices?\b", r"nectars?\b", r"zumos?", r"lemonade", r"limonada", r"\bteas?\b", r"thes ", r"beverages?")),
    (
        SWEET,
        _rx(
            r"ice cream", r"helado", r"biscuit", r"cookie", r"galleta", r"chocolate", r"candy",
            r"candies", r"caramel", r"confectioner", r"\bjams?\b", r"mermelada", r"dessert",
            r"postre", r"pastr", r"bolleria", r"cakes?\b", r"madeleine", r"spreads? (of )?cocoa",
            r"cocoa and hazelnut", r"filled cereal",
        ),
    ),
    (
        PREPARED,
        _rx(
            r"prepared (meals|dishes)", r"ready meals", r"plato", r"pizza", r"\bsoups?\b",
            r"sauces?\b", r"salsa", r"sandwich", r"\bmeals?\b", r"omelet",
        ),
    ),
]


# «Agua» y «water» aparecen constantemente en los nombres como MEDIO en el que viene el
# alimento, no como lo que el alimento es: «Atún, enlatado, en agua», «Cerdo, curado, jamón con
# agua añadida», «canned in water», «Garbanzos cocidos en agua y sal». Sin quitar esas frases,
# la regla de bebidas se quedaba con el atún, con el jamón y con los garbanzos — y el grupo no
# es solo una etiqueta de filtro: decide el tamaño de ración por defecto (`_BOUNDS`,
# `UNIT_GRAMS_BY_GROUP`), así que a un jamón se le aplicaba la ración de una bebida.
# Se quita solo la frase, no la palabra: «Agua mineral natural» sigue siendo una bebida.
_COOKING_MEDIUM = re.compile(
    r"\b(?:en|con|al|sin|de)\s+agua(?:\s+anadida)?\b"
    r"|\bagua\s+anadida\b"
    r"|\b(?:in|with|packed\s+in|canned\s+in)\s+water\b"
    r"|\b(?:water\s+added|added\s+water)\b"
)


def classify_food(name: str | None, category: str | None = None) -> str:
    """Grupo alimentario deducido del nombre y, si este no basta, de la categoría."""
    for text in (name, category):
        if not text:
            continue
        normalized = _COOKING_MEDIUM.sub(" ", _normalize(text))
        for group, pattern in _RULES:
            if pattern.search(normalized):
                if group in PLANNABLE_GROUPS and category:
                    normalized_category = _normalize(category)
                    for excluded, excl_pattern in _EXCLUDING_CATEGORIES:
                        if excl_pattern.search(normalized_category):
                            return excluded
                return group
    return OTHER


# --- Cantidades realistas por grupo -----------------------------------------------------


@dataclass(frozen=True)
class GramBounds:
    min_g: float
    max_g: float


# Alimentos en seco (más de ~250 kcal/100 g: arroz, pasta, legumbre o cereal crudos) se comen en
# mucha menos cantidad que los ya cocinados, así que tienen sus propios límites.
_DRY_KCAL_100G = {LEGUME: 250.0, GRAIN: 250.0, FRUIT: 150.0}

_BOUNDS: dict[str, GramBounds] = {
    MEAT: GramBounds(100, 220),
    PROCESSED_MEAT: GramBounds(30, 80),
    FISH: GramBounds(100, 220),
    EGG: GramBounds(60, 180),
    DAIRY: GramBounds(100, 250),
    CHEESE: GramBounds(30, 80),
    LEGUME: GramBounds(150, 250),
    NUTS: GramBounds(20, 50),
    VEGETABLE: GramBounds(80, 200),
    FRUIT: GramBounds(80, 200),
    GRAIN: GramBounds(150, 300),
    CEREAL: GramBounds(25, 80),
    BREAD: GramBounds(30, 100),
    OIL_FAT: GramBounds(5, 20),
}
_DRY_BOUNDS: dict[str, GramBounds] = {
    LEGUME: GramBounds(50, 90),
    GRAIN: GramBounds(50, 100),
    FRUIT: GramBounds(20, 60),
}
_DEFAULT_BOUNDS = GramBounds(20, 400)


def gram_bounds(group: str | None, kcal_100g: float) -> GramBounds:
    """Cantidad mínima y máxima razonable de un alimento del grupo en una comida."""
    if group is None:
        return _DEFAULT_BOUNDS
    if group in _DRY_BOUNDS and kcal_100g > _DRY_KCAL_100G[group]:
        return _DRY_BOUNDS[group]
    return _BOUNDS.get(group, _DEFAULT_BOUNDS)


# --- Qué grupos entran en cada comida ---------------------------------------------------


@dataclass(frozen=True)
class MealTemplate:
    """Grupos permitidos en una comida (con cuántos alimentos de cada uno como máximo) y qué
    grupos debe cubrir al menos: `required` es una lista de conjuntos y de cada conjunto tiene
    que haber al menos un alimento."""

    caps: dict[str, int]
    required: tuple[frozenset[str], ...]
    max_items: int
    # Máximo de alimentos entre varios grupos a la vez (p. ej. un solo plato principal de
    # carne, pescado o huevo aunque cada grupo admita uno por separado).
    union_caps: tuple[tuple[frozenset[str], int], ...] = ()


_MAIN_DISH = frozenset({MEAT, FISH, EGG})
_PROTEIN_MAIN = _MAIN_DISH | {LEGUME}
_DESSERT = frozenset({FRUIT, DAIRY})

# Comida y cena: un plato principal (carne, pescado o huevo), verdura, un acompañamiento de
# hidrato (arroz, pasta, patata o pan) y, si acaso, un postre (fruta o lácteo) y un poco de aceite.
_MAIN_MEAL = MealTemplate(
    caps={
        MEAT: 1, FISH: 1, EGG: 1, LEGUME: 1, VEGETABLE: 2, GRAIN: 1, BREAD: 1, FRUIT: 1,
        DAIRY: 1, OIL_FAT: 1,
    },
    required=(_PROTEIN_MAIN, frozenset({VEGETABLE})),
    max_items=5,
    union_caps=((_MAIN_DISH, 1), (frozenset({GRAIN, BREAD}), 1), (_DESSERT, 1)),
)
_DINNER = MealTemplate(
    caps={**_MAIN_MEAL.caps, PROCESSED_MEAT: 1, CHEESE: 1},
    required=(_PROTEIN_MAIN | {PROCESSED_MEAT, CHEESE}, frozenset({VEGETABLE})),
    max_items=5,
    union_caps=((_MAIN_DISH | {PROCESSED_MEAT, CHEESE}, 1), (frozenset({GRAIN, BREAD}), 1), (_DESSERT, 1)),
)
_BREAKFAST = MealTemplate(
    caps={BREAD: 1, CEREAL: 1, DAIRY: 1, EGG: 1, FRUIT: 1, NUTS: 1, CHEESE: 1, PROCESSED_MEAT: 1},
    required=(frozenset({BREAD, CEREAL}), frozenset({DAIRY, EGG, CHEESE})),
    max_items=4,
    union_caps=((frozenset({BREAD, CEREAL}), 1), (frozenset({DAIRY, EGG, CHEESE, PROCESSED_MEAT}), 2)),
)
_SNACK = MealTemplate(
    caps={FRUIT: 1, DAIRY: 1, NUTS: 1, BREAD: 1, CHEESE: 1, CEREAL: 1},
    required=(frozenset({FRUIT, DAIRY, NUTS}),),
    max_items=2,
)
_SUPPER = MealTemplate(
    caps={DAIRY: 1, FRUIT: 1, NUTS: 1, BREAD: 1, CEREAL: 1},
    required=(frozenset({DAIRY, FRUIT}),),
    max_items=2,
)

MEAL_TEMPLATES: dict[str, MealTemplate] = {
    "breakfast": _BREAKFAST,
    "morning_snack": _SNACK,
    "lunch": _MAIN_MEAL,
    "afternoon_snack": _SNACK,
    "dinner": _DINNER,
    "supper": _SUPPER,
}

# Reparto de las kcal del día entre las comidas según cuántas hace el usuario.
MEAL_KCAL_SHARES: dict[int, dict[str, float]] = {
    1: {"lunch": 1.0},
    2: {"lunch": 0.55, "dinner": 0.45},
    3: {"breakfast": 0.25, "lunch": 0.40, "dinner": 0.35},
    4: {"breakfast": 0.25, "lunch": 0.35, "afternoon_snack": 0.10, "dinner": 0.30},
    5: {
        "breakfast": 0.22, "morning_snack": 0.10, "lunch": 0.33, "afternoon_snack": 0.10,
        "dinner": 0.25,
    },
    6: {
        "breakfast": 0.20, "morning_snack": 0.10, "lunch": 0.30, "afternoon_snack": 0.10,
        "dinner": 0.25, "supper": 0.05,
    },
}


# --- Alimentos «de diario» ----------------------------------------------------------------
# El catálogo mezcla lo que se come cada día (pollo, merluza, tomate, arroz…) con lo exótico o
# muy específico (bogavante, trufa, cebollino, arenque salado). Sin una preferencia, un solver que
# solo mira los macros elige lo que mejor cuadra, y salen menús que nadie cocinaría. Estos
# patrones marcan lo de diario en cada grupo; el motor los prefiere al armar el pool de un día.
_STAPLES: dict[str, re.Pattern[str]] = {
    MEAT: _rx(r"\bpollo", r"\bpavo", r"ternera", r"vacuno", r"cerdo", r"cordero", r"conejo", r"solomillo", r"\blomo", r"pechuga", r"muslo", r"contramuslo"),
    PROCESSED_MEAT: _rx(r"jamon (cocido|serrano|york)", r"pechuga de pavo", r"lomo", r"fiambre de pavo"),
    FISH: _rx(r"merluza", r"salmon", r"\batun", r"bacalao", r"lubina", r"dorada", r"sardina", r"caballa", r"gamba", r"langostino", r"pescadilla", r"trucha", r"lenguado", r"\brape\b", r"mejillon", r"calamar", r"pulpo", r"bonito", r"pez espada", r"emperador", r"rodaballo"),
    EGG: _rx(r"^huevos? de gallina", r"^huevos?$", r"^huevos? (fresco|camper|de suelo|l\b|m\b|xl\b|grande|mediano|ecolog|bio)"),
    DAIRY: _rx(r"leche (entera|semidesnatada|desnatada|sin lactosa)", r"yogur(t)? (natural|desnatado|griego|sin azucar)", r"\byogur\b$", r"\byogur natural", r"kefir", r"bebida de (avena|soja|almendra)"),
    CHEESE: _rx(r"queso (fresco|de burgos|burgos|mozzarella|cottage|requeson|feta|manchego|semicurado|tierno|light)", r"requeson", r"mozzarella", r"cottage"),
    LEGUME: _rx(r"lenteja", r"garbanzo", r"alubia", r"judias? (blancas|pintas|rojas)", r"\bhabas?\b", r"guisante", r"\bsoja\b", r"tofu", r"chickpea", r"lentil"),
    NUTS: _rx(r"\bnueces\b", r"\bnuez\b", r"almendra", r"avellana", r"pistacho", r"anacardo", r"cacahuete"),
    VEGETABLE: _rx(r"tomate", r"lechuga", r"zanahoria", r"brocoli", r"espinaca", r"calabacin", r"pimiento", r"cebolla", r"judias verdes", r"coliflor", r"pepino", r"champinon", r"berenjena", r"esparrago", r"alcachofa", r"calabaza", r"puerro", r"\bcol\b", r"acelga", r"repollo", r"\bapio\b", r"remolacha", r"rucula", r"ensalada mixta", r"canonigo", r"endibia", r"escarola"),
    FRUIT: _rx(r"manzana", r"\bpera\b", r"platano", r"banana", r"naranja", r"mandarina", r"fresa", r"melocoton", r"sandia", r"melon", r"kiwi", r"\buvas?\b", r"\bpina\b", r"ciruela", r"cereza", r"albaricoque", r"mango", r"aguacate", r"arandano", r"pomelo", r"nectarina", r"\bhigos?\b"),
    GRAIN: _rx(r"\barroz", r"\bpasta\b", r"espagueti", r"spaghetti", r"macarron", r"fideo", r"quinoa", r"cuscus", r"patata", r"boniato", r"\bpenne\b"),
    CEREAL: _rx(r"\bavena\b", r"copos de avena", r"cereales? (integral|de desayuno|desayuno)", r"muesli", r"corn flakes"),
    BREAD: _rx(r"\bpan\b", r"pan (integral|de molde|blanco|de barra)", r"tostada", r"barra de pan"),
    OIL_FAT: _rx(r"aceite de oliva", r"mantequilla"),
}


# En fruta, verdura y lácteos la fruta o la verdura tiene que ser lo que da nombre al alimento
# («Fresa», «Tomate, maduro, crudo»), no un ingrediente de otra cosa («L. Casei sabor fresa»).
_ANCHORED = frozenset({FRUIT, VEGETABLE, DAIRY})


def is_staple(group: str | None, name: str | None) -> bool:
    """¿Es un alimento de diario de su grupo? (ver `_STAPLES`)."""
    if group is None or not name:
        return False
    pattern = _STAPLES.get(group)
    if pattern is None:
        return False
    normalized = _normalize(name)
    if group in _ANCHORED:
        return pattern.match(normalized) is not None
    return pattern.search(normalized) is not None
