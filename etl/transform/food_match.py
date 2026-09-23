"""Empareja el nombre de un ingrediente de receta con un alimento del catálogo.

La primera importación de TheMealDB dejó 86 ingredientes sin equivalente, y al mirarlos uno a
uno casi todos eran el MISMO alimento en plural: «Berenjenas», «Boniatos», «Calabacines». El
catálogo guarda «Berenjena» y el emparejado se hacía con un `ILIKE '%Berenjenas%'`, que no
encuentra nada. Los acentos sumaban lo suyo: «calabacines» tampoco encuentra «calabacín».

Por eso el emparejado se hace aquí, en Python, y no en SQL: los alimentos genéricos son unos
diez mil, caben de sobra en memoria, y así se pueden probar varias formas del nombre y ordenar
las respuestas por lo buenas que son sin escribir una consulta por intento. El plural español
es ambiguo —«tomates» puede venir de «tomate» o de «tomat»— así que no se adivina: se generan
las dos formas y gana la que exista de verdad en el catálogo.

El orden de preferencia importa tanto como el emparejado. Para «cebolla» queremos «Cebolla,
cruda» y no «Cebolla deshidratada en polvo, enriquecida», así que primero se prueba el nombre
exacto, después que el alimento EMPIECE por lo que buscamos, después que lo contenga entero, y
solo al final se cae en el trozo de texto suelto.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Palabras que no distinguen un alimento de otro: «aceite de oliva» y «aceite oliva» son el
# mismo. Se quitan de la consulta para que el emparejado por palabras no falle por un «de».
STOPWORDS = frozenset(
    {
        "de", "del", "la", "el", "los", "las", "un", "una", "y", "o",
        "con", "en", "a", "al", "sin", "para", "tipo",
    }  # fmt: skip
)

# Por debajo de esto una palabra no identifica nada: «ajo» sí, «ah» no.
MIN_TOKEN_LEN = 3

_NON_WORD_RE = re.compile(r"[^a-z0-9ñ]+")

# La virgulilla suelta que la descomposición Unicode separa de la ene.
TILDE = "\u0303"


def normalize(text: str) -> str:
    """Minúsculas, sin acentos y con un solo espacio entre palabras.

    La eñe se conserva: en español distingue palabras («caña» y «cana» no son lo mismo),
    mientras que la tilde casi nunca lo hace en nombres de alimentos. Por eso se descompone el
    texto y se tiran todos los signos MENOS la virgulilla que va encima de una ene."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    kept: list[str] = []
    for char in decomposed:
        if unicodedata.category(char) != "Mn":
            kept.append(char)
        elif char == TILDE and kept and kept[-1] == "n":
            kept.append(char)
    return _NON_WORD_RE.sub(" ", unicodedata.normalize("NFC", "".join(kept))).strip()


def singular_forms(word: str) -> list[str]:
    """Las formas singulares plausibles de una palabra, sin decidir cuál es la buena.

    El plural español no se puede deshacer sin saber la palabra: lo que acaba en vocal añade
    «-s» («tomate» → «tomates») y lo que acaba en consonante añade «-es» («calabacín» →
    «calabacines»). Desde el plural las dos reglas son posibles, así que se devuelven ambas y
    ya se verá cuál está en el catálogo; la que no exista no encontrará nada."""
    forms: list[str] = []
    if word.endswith("ces") and len(word) > 4:
        forms.append(word[:-3] + "z")  # nueces -> nuez
    if word.endswith("es") and len(word) > 4:
        forms.append(word[:-2])  # calabacines -> calabacin
    if word.endswith("s") and len(word) > 3:
        forms.append(word[:-1])  # berenjenas -> berenjena
    return forms


def _phrase_variants(phrase: str) -> list[str]:
    """La frase tal cual y la misma con cada palabra en singular."""
    words = phrase.split()
    if not words:
        return []
    variants = [phrase]
    singular = " ".join(singular_forms(w)[0] if singular_forms(w) else w for w in words)
    if singular != phrase:
        variants.append(singular)
    # La otra lectura del plural, por si la primera regla no era la buena.
    alternative = " ".join(singular_forms(w)[-1] if singular_forms(w) else w for w in words)
    if alternative not in variants:
        variants.append(alternative)
    return variants


# Ingredientes que una receta española escribe a secas y que el catálogo solo tiene con
# apellido. Sin esto «harina» acaba en «Harina de mijo» y «leche» en «Leche de coco», que son
# alimentos distintos: la palabra a secas tiene un significado por defecto y hay que decirlo,
# porque ningún criterio automático puede deducirlo del nombre.
ALIAS = {
    "harina": "harina de trigo blanca",
    "leche": "leche entera",
    "nuez": "nueces de nogal comun",
    "nueces": "nueces de nogal comun",
    "azucar": "azucares granulado",
    "nata": "nata liquida",
    "aceite": "aceite de oliva",
    "arroz": "arroz blanco",
}


def variant_tiers(name: str) -> list[list[str]]:
    """Las formas del nombre agrupadas por lo fiables que son.

    Primer grupo: el nombre por defecto, si la palabra tiene uno («harina» es de trigo).
    Segundo: la frase entera y sus singulares. Tercero: solo la primera palabra.
    Los grupos se agotan por completo antes de pasar al siguiente, y eso es justo lo que
    evita el error más feo que tenía la primera importación: «pechuga de pollo» se quedaba en
    «Pechuga de pavo» porque la búsqueda por la cabeza «pechuga» corría antes de que la frase
    entera hubiera terminado de intentarlo."""
    base = normalize(name)
    if not base:
        return []
    # El alias va en su propio grupo y por delante, no mezclado con la palabra suelta: si
    # «leche» significa «leche entera», buscar las dos a la vez es justo lo que trae el
    # camembert de leche cruda. Como grupo aparte, la palabra suelta sigue estando ahí para
    # cuando el catálogo no tenga el alias.
    alias = ALIAS.get(base)
    alias_variants = _phrase_variants(alias) if alias is not None else []
    frase = _phrase_variants(base)

    words = [w for w in base.split() if w not in STOPWORDS]
    cabeza: list[str] = []
    if len(words) > 1:
        cabeza = [
            v
            for v in _phrase_variants(words[0])
            if v not in frase and len(v) >= MIN_TOKEN_LEN
        ]
    return [grupo for grupo in (alias_variants, frase, cabeza) if grupo]


def name_variants(name: str) -> list[str]:
    """Todas las formas del nombre, en orden, sin agrupar."""
    return [variant for tier in variant_tiers(name) for variant in tier]


@dataclass(frozen=True)
class Food:
    id: str
    name: str
    category: str | None
    normalized: str = ""
    tokens: tuple[str, ...] = ()
    # Las mismas palabras sin las de relleno. Comparar por aquí es lo que hace que «caldo de
    # pollo» encuentre «Caldo de pollo»: el «de» está en el nombre pero no en la consulta, y
    # comparándolos en crudo el prefijo nunca cuadraba.
    key_tokens: tuple[str, ...] = ()

    @staticmethod
    def build(id: str, name: str, category: str | None) -> Food:
        normalized = normalize(name)
        tokens = tuple(normalized.split())
        return Food(
            id=id,
            name=name,
            category=category,
            normalized=normalized,
            tokens=tokens,
            key_tokens=tuple(t for t in tokens if t not in STOPWORDS),
        )


@dataclass
class Index:
    """Los alimentos ya normalizados, con los atajos para no recorrerlos enteros cada vez.

    Las listas llegan en el orden de calidad del catálogo, pero ese orden no basta para
    elegir: entre «Zanahoria, deshidratada» y «Zanahoria, cruda» la buena para una receta es
    la segunda aunque la fuente ponga antes la primera. Quedarse con el primero que cumpla es
    precisamente el error que tenía la primera importación, así que `_best` puntúa todos los
    candidatos y este orden solo sirve de desempate."""

    foods: list[Food] = field(default_factory=list)
    exact: dict[str, Food] = field(default_factory=dict)
    by_head: dict[str, list[Food]] = field(default_factory=dict)
    by_token: dict[str, list[Food]] = field(default_factory=dict)
    # Posición con la que llegó cada alimento: es el desempate final, y así la calidad que
    # decidió la fuente no se pierde al reordenar por estado y por longitud.
    orden: dict[str, int] = field(default_factory=dict)


def build_index(rows: list[tuple[str, str, str | None]]) -> Index:
    """`rows` son `(id, nombre, categoría)` YA ordenados por preferencia."""
    index = Index()
    for food_id, name, category in rows:
        food = Food.build(food_id, name, category)
        if not food.tokens:
            continue
        index.orden[food.id] = len(index.foods)
        index.foods.append(food)
        index.exact.setdefault(food.normalized, food)
        if food.key_tokens:
            index.by_head.setdefault(food.key_tokens[0], []).append(food)
        for token in set(food.key_tokens):
            index.by_token.setdefault(token, []).append(food)
    return index


ESTADO_CRUDO = 0
ESTADO_NORMAL = 1
ESTADO_COCINADO = 2
ESTADO_PROCESADO = 3

# Una receta parte del alimento crudo y ya lo cocina ella. Coger el deshidratado en vez del
# fresco no es un matiz: el tomate seco tiene cinco veces las calorías del tomate crudo, así
# que la elección entre dos alimentos con el mismo nombre decide si la receta miente o no.
PALABRAS_CRUDO = frozenset(
    {"crudo", "cruda", "crudos", "crudas", "fresco", "fresca", "frescos", "frescas"}
)
PALABRAS_COCINADO = frozenset(
    {
        "cocido", "cocida", "cocidos", "cocidas", "hervido", "hervida", "asado", "asada",
        "frito", "frita", "fritos", "fritas", "horneado", "horneada", "estofado", "guisado",
        "cocinado", "cocinada", "vapor", "parrilla", "plancha", "tostado", "tostada",
    }
)  # fmt: skip
PALABRAS_PROCESADO = frozenset(
    {
        "deshidratado", "deshidratada", "deshidratados", "deshidratadas", "polvo", "seco",
        "seca", "secos", "secas", "conserva", "enlatado", "enlatada", "congelado", "congelada",
        "confitado", "confitada", "glaseado", "glaseada", "liofilizado", "almibar", "salmuera",
        "ahumado", "ahumada", "encurtido", "encurtida", "concentrado", "concentrada",
        "extracto", "jarabe", "sirope", "instantaneo",
        "precocinado", "precocinada", "preenvasada", "preenvasado", "pasteurizada",
    }
)  # fmt: skip


def estado(food: Food) -> int:
    """Cómo de cerca está del alimento tal cual, que es lo que pide una receta.

    Se mira cada palabra y también su singular, porque el catálogo escribe «Nueces, glaseadas»
    y «Nuez, glaseada» según le convenga y las dos cosas son lo mismo."""
    palabras = set(food.key_tokens)
    palabras.update(forma for token in food.key_tokens for forma in singular_forms(token))
    if palabras & PALABRAS_PROCESADO:
        return ESTADO_PROCESADO
    if palabras & PALABRAS_CRUDO:
        return ESTADO_CRUDO
    if palabras & PALABRAS_COCINADO:
        return ESTADO_COCINADO
    return ESTADO_NORMAL


def _query_tokens(variant: str) -> list[str]:
    tokens = [t for t in variant.split() if t not in STOPWORDS and len(t) >= MIN_TOKEN_LEN]
    return tokens or [t for t in variant.split() if len(t) >= MIN_TOKEN_LEN]


def _exact(variant: str, index: Index) -> list[Food]:
    food = index.exact.get(variant)
    return [food] if food is not None else []


def _starts_with(variant: str, index: Index) -> list[Food]:
    """«Cebolla, cruda» para «cebolla»: el alimento empieza por lo que se busca."""
    tokens = _query_tokens(variant)
    if not tokens:
        return []
    wanted = tuple(tokens)
    return [
        food
        for food in index.by_head.get(tokens[0], ())
        if food.key_tokens[: len(wanted)] == wanted
    ]


def _contains_all(variant: str, index: Index) -> list[Food]:
    """«Pechuga de pollo, cruda» para «pollo pechuga»: están todas las palabras, en cualquier
    orden. Se arranca por la palabra menos común para mirar la lista más corta."""
    tokens = _query_tokens(variant)
    if not tokens:
        return []
    rarest = min(tokens, key=lambda t: len(index.by_token.get(t, ())))
    wanted = set(tokens)
    return [food for food in index.by_token.get(rarest, ()) if wanted <= set(food.key_tokens)]


def _substring(variant: str, index: Index) -> list[Food]:
    """El último recurso: el nombre aparece como trozo de texto. Encuentra cosas que las
    palabras sueltas no, pero también acierta por casualidad, así que va detrás de todo."""
    if len(variant) < MIN_TOKEN_LEN:
        return []
    tokens = _query_tokens(variant)
    bucket = index.by_token.get(tokens[0], index.foods) if tokens else index.foods
    return [food for food in bucket if variant in food.normalized]


def concrecion(food: Food) -> int:
    """Cuántas palabras del nombre ESTRECHAN de qué alimento se habla.

    «Crudo» y «fresco» no estrechan nada: son el alimento tal cual, que es justo lo que busca
    una receta. «Moscada», «de mijo» o «ahumado» sí, y convierten el resultado en otro
    alimento distinto. Contando solo esas se evita a la vez que «Nueces» acabe en «Nuez
    moscada» y que «Harina» acabe en «Harina de soja, integral»."""
    return len([t for t in food.key_tokens if t not in PALABRAS_CRUDO])


def _best(candidates: list[Food], index: Index) -> Food | None:
    """De todos los que valen, el más parecido a un ingrediente de receta.

    Se mide la distancia a lo que la receta quiso decir, y las dos cosas que alejan cuentan
    igual: cada palabra de más estrecha el alimento a algo que nadie pidió («Harina de soja,
    integral» cuando ponía «harina»), y cada paso de elaboración lo cambia («Salmón ahumado»
    cuando ponía «salmón»). Sumarlas es lo que impide que un nombre corto pero procesado gane
    a uno largo y crudo: «Garbanzo, seco» tiene menos palabras que «Garbanzos, semillas
    maduras, crudos» y aun así es peor respuesta. Desempata el orden del catálogo, que trae la
    calidad que decidió la fuente."""
    if not candidates:
        return None
    return min(candidates, key=lambda f: (concrecion(f) + estado(f), index.orden[f.id]))


def match(name: str, index: Index) -> Food | None:
    """El mejor alimento del catálogo para ese ingrediente, o `None` si no hay ninguno.

    Cada grupo de formas del nombre agota todas las maneras de buscar antes de pasar al
    siguiente: una búsqueda mala de la frase entera sigue siendo mejor que una búsqueda buena
    de solo la primera palabra, porque «pechuga de pollo» no es «pechuga» de lo que sea.

    Lo que sí interrumpe el orden es el estado: un alimento cocinado o conservado no cierra
    la búsqueda aunque sea el que mejor encaja por el nombre. Se guarda de reserva y se sigue
    mirando, porque para una receta «Pollo, pechuga, crudo» vale más que «Pechuga de pollo,
    enrollada, asada al horno» aunque el segundo se parezca más a lo que pone el ingrediente."""
    for tier in variant_tiers(name):
        provisional: Food | None = None
        for finder in (_exact, _starts_with, _contains_all, _substring):
            candidates: list[Food] = []
            for variant in tier:
                candidates.extend(finder(variant, index))
            found = _best(candidates, index)
            if found is None:
                continue
            if estado(found) <= ESTADO_NORMAL:
                return found
            # Cocinado o procesado no cierra la búsqueda, pero solo se sigue buscando DENTRO
            # del mismo grupo: un caldo de pollo deshidratado es peor que uno sin deshidratar,
            # y aun así es mejor que el caldo de pescado que encontraría la palabra suelta.
            provisional = provisional or found
        if provisional is not None:
            return provisional
    return None
