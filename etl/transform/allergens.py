# ruff: noqa: E501  (listas de palabras clave: son datos, partirlas en líneas de 100 las haría ilegibles)
"""Alérgenos por alimento (documento 2, sección 6.3 `food_allergens`).

Dos orígenes, guardados en `food_allergens.origin`:

- `declared` / `trace`: etiquetas `allergens_tags` / `traces_tags` que Open Food
  Facts publica para cada producto de marca (dato declarado por el
  fabricante en la etiqueta). Se cargan tal cual con `OFF_TAG_TO_CODE`.
- `inferred`: los alimentos genéricos (USDA, CIQUAL, BEDCA) no traen etiquetas
  de alérgenos, así que se INFIEREN por nombre y categoría con reglas de
  palabras clave en español, inglés y francés (los nombres de USDA están en
  inglés, los de CIQUAL en francés y los de BEDCA en español). Es una
  heurística y se diseña para errar por exceso: un falso positivo solo quita
  un alimento de las opciones de quien tiene esa restricción, un falso
  negativo lo pone en su plato. Nunca es un dato verificado de laboratorio —
  la interfaz lo dice ("orientativo, revisa siempre la etiqueta").

Los códigos son los 14 alérgenos de declaración obligatoria de la UE, tal como
están sembrados en `allergens` (migración 0005).
"""

from __future__ import annotations

import re
import unicodedata

OFF_TAG_TO_CODE: dict[str, str] = {
    "en:gluten": "gluten",
    "en:milk": "lacteos",
    "en:eggs": "huevos",
    "en:fish": "pescado",
    "en:crustaceans": "crustaceos",
    "en:molluscs": "moluscos",
    "en:peanuts": "cacahuetes",
    "en:nuts": "frutos_de_cascara",
    "en:soybeans": "soja",
    "en:celery": "apio",
    "en:mustard": "mostaza",
    "en:sesame-seeds": "sesamo",
    "en:sulphur-dioxide-and-sulphites": "sulfitos",
    "en:lupin": "altramuces",
}

ALL_CODES = frozenset(OFF_TAG_TO_CODE.values())


def off_tags_to_codes(tags: list[str] | None) -> set[str]:
    """Etiquetas de OFF (`en:gluten`...) -> códigos propios. Las que no están
    entre los 14 alérgenos de la UE (p. ej. `en:none`) se ignoran."""
    return {OFF_TAG_TO_CODE[t] for t in (tags or []) if t in OFF_TAG_TO_CODE}


def _normalize(text: str) -> str:
    """Minúsculas y sin diacríticos: 'Mejillón' y 'mejillon' casan igual."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


# Frases que contienen una palabra clave pero NO el alérgeno (leches vegetales,
# mantequilla de cacao...), se quitan antes de buscar.
_NOT_MILK = re.compile(
    r"\b(?:coconut|almond|soy|soya|soja|rice|oat|hazelnut|cashew|hemp|pea)\s+(?:milk|cream|butter|yogh?urt|cheese)\b"
    r"|\b(?:milk|cream|butter|yogh?urt|cheese)\s+(?:of\s+)?(?:coconut|almond|soy|soya|rice|oat)\b"
    r"|\b(?:leche|lait|crema|mantequilla|beurre|yogur|yaourt|queso|fromage)\s+(?:de\s+)?"
    r"(?:coco|almendra?s?|soja|arroz|avena|noix\s+de\s+coco|amande|riz|avoine|cacao|cacahuete?s?|cacahuete)\b"
    r"|\b(?:cocoa|cacao|shea|karite|peanut|nut)\s+butter\b"
    r"|\bbebida\s+vegetal\b|\bboisson\s+vegetale\b|\bplant[- ]based\s+(?:milk|drink)\b|\bnon[- ]dairy\b"
    r"|\bmilk\s+substitute\b|\bsin\s+lactosa\b"
)
_NOT_NUT = re.compile(
    # USDA titula "Nuts, coconut meat", "Nuts, chestnuts": se quita la frase entera,
    # o quedaría suelto el "Nuts" genérico.
    r"\bnuts?[, ]+(?:coconut|chestnuts?|pine\s+nuts?|water\s+chestnuts?|ginkgo|kola)\b"
    r"|\bnutmeg\b|\bnuez\s+moscada\b|\bnoix\s+de\s+muscade\b|\bcoconut\b|\bcoco\b|\bnoix\s+de\s+coco\b"
    r"|\bchestnuts?\b|\bcastanas?\b|\bchataigne\b|\bpine\s+nuts?\b|\bpinones?\b|\bpignons?\b"
    r"|\bbutternut\b|\bdoughnuts?\b|\bdonuts?\b|\bwater\s+chestnuts?\b|\bkola\s+nut\b|\bginkgo\b"
)
_NOT_EGG = re.compile(r"\beggplants?\b|\bberenjenas?\b|\baubergines?\b")
_NOT_FISH = re.compile(
    r"\bfish\s+oil\b|\baceite\s+de\s+pescado\b|\bcatfish\s+\(imitation\)\b|\bstarfish\b|\bjellyfish\b"
)
_NOT_GLUTEN = re.compile(
    r"\bpan[- ](?:fried|broiled|browned|frying|seared|roasted|grilled|cooked|dressing|fry)\b"
    r"|\bfrying\s+pan\b|\bpanfried\b|\bcream\s+of\s+tartar\b"
    r"|\b(?:rice|corn|maize|potato|tapioca|cassava|chickpea|almond|coconut|buckwheat|sorghum|quinoa|"
    r"amaranth|millet|arroz|maiz|patata|garbanzo|almendra|coco|trigo\s+sarraceno|sarrasin|"
    r"mais|riz|pomme\s+de\s+terre|gluten[- ]free|sin\s+gluten|sans\s+gluten)\s+"
    r"(?:flour|starch|cereal|pasta|bread|noodles?|crackers?|harina|almidon|fecula|pan|pates?|farine|amidon)\b"
)

# Cada alérgeno: patrones de palabras clave ya SIN diacríticos (se normaliza el
# texto antes). `\b` evita casar dentro de otra palabra ('pan' en 'panela').
_RULES: dict[str, re.Pattern[str]] = {
    "gluten": re.compile(
        r"\b(?:wheat|trigo|ble|froment|barley|cebada|orge|malt|malta|rye|centeno|seigle|oats?|avena|avoine|"
        r"spelt|espelta|epeautre|kamut|triticale|semolina?|semola|semoule|couscous|cous\s*cous|bulgur|bulgar|"
        r"seitan|farro|flour|harina|farine|bread|breads|pan|pain|baguette|pasta|pastas|pates|macaroni|"
        r"spaghetti|noodles?|fideos?|tallarines|lasagn?a|ravioli|tortellini|gnocchi|cannelloni|"
        r"biscuits?|galletas?|cookies?|crackers?|pretzels?|croissants?|muffins?|cakes?|pasteles|pastel|"
        r"bizcochos?|magdalenas?|donuts?|doughnuts?|waffles?|gofres?|pancakes?|crepes?|pizza|"
        r"hojaldre|empanadas?|empanadillas?|rebozad[oa]s?|breaded|batter|tempura|bollos?|bollycao|"
        r"regana|picos?|rosquillas?|torta|tostadas?|toast|rusk|biscotte|granola|muesli|cereals?|cereales|"
        r"cereales|beer|cerveza|biere|bulgur|stuffing|dumplings?|sandwich(?:es)?|hamburguesa\s+con\s+pan|"
        r"pan\s+rallado|breadcrumbs?|chapata|focaccia|pita|naan|tortillas?\s+de\s+trigo|wrap|"
        r"\w*burgers?|hot\s*dogs?|burritos?|tacos?|enchiladas?|buns?|bagels?|scones?|strudel|danish|pies?|"
        r"tarts?|brioche|cornbread|shortcake|brownies?|cupcakes?|nuggets?|fritters?|pierogi|wontons?)\b"
    ),
    "lacteos": re.compile(
        r"\b(?:\w*cheese\w*|milk|milks|leche|lait|queso|quesos|fromage|yogh?urts?|yogur(?:es)?|yaourts?|"
        r"butter|mantequilla|beurre|cream|creams|nata|creme|whey|suero|lactose|lactosa|casein|caseina|"
        r"kefir|cuajada|requeson|ricotta|mozzarella|parmesan|parmigiano|cheddar|gouda|brie|camembert|"
        r"feta|edam|emmental|manchego|roquefort|gruyere|mascarpone|burrata|flan|custard|natillas?|"
        r"ice\s+cream|helados?|glace|dairy|lacteos?|laitier|margarin[ae]s?|margarine|ghee|curds?|"
        r"cottage|buttermilk|yoghourt|milkshake|batido|cuajo|puddings?|budines?|caramel\s+sauce|"
        r"chocolate\s+con\s+leche|milk\s+chocolate|condensed\s+milk|leche\s+condensada)\b"
    ),
    "huevos": re.compile(
        r"\b(?:eggs?|huevos?|oeufs?|omelett?es?|tortilla\s+(?:de\s+patatas?|espanola|francesa)|"
        r"mayonnaise|mayonesa|mahonesa|meringue|merengue|albumin|albumina|egg\s+white|clara\s+de\s+huevo|"
        r"yema|yolk|eggnog|quiche|tiramisu|flan|custard|natillas?|aioli|alioli|hollandaise|bearnesa|"
        r"ovoproducto|scrambled|fried\s+egg|huevo\s+frito)\b"
    ),
    "pescado": re.compile(
        r"\b(?:fish|fishes|pescados?|poissons?|salmon|saumon|tuna|atun|thon|cod|bacalao|cabillaud|morue|"
        r"hake|merluza|colin|sardines?|sardinas?|anchov(?:y|ies)|anchoas?|anchois|mackerel|caballa|"
        r"maquereau|trout|truchas?|truite|herring|arenques?|hareng|haddock|eglefin|sole|lenguados?|"
        r"sea\s+bass|lubina|dorada|daurade|bream|swordfish|pez\s+espada|espadon|halibut|fletan|"
        r"tilapia|pollock|carp|carpa|eel|anguila|anguille|surimi|kanikama|caviar|roe|huevas?|"
        r"fish\s+sauce|salsa\s+de\s+pescado|monkfish|rape|rodaballo|turbot|mullet|salmonete|rouget|"
        r"bonito|sushi|sashimi|perch|perca|pike|lucio|snapper|pargo|grouper|mero|jurel|sable|"
        r"finfish|smoked\s+salmon|salmon\s+ahumado|bacalao|pescadilla|gado|lomo\s+de\s+atun|"
        r"escabeche\s+de\s+pescado|boquerones?|pilchard|whiting|whitebait|shad|sturgeon|esturion|"
        r"trucha|caballa|pez|caviar|dogfish|cazon|marrajo|tintorera|shark|tiburon|raya|skate|ray)\b"
    ),
    "crustaceos": re.compile(
        r"\b(?:shrimps?|prawns?|gambas?|langostinos?|crabs?|cangrejos?|crabe|lobsters?|bogavantes?|"
        r"langostas?|homard|langoustines?|cigalas?|crayfish|crawfish|cangrejo\s+de\s+rio|krill|centollos?|"
        r"percebes?|barnacles?|crevettes?|crustac[a-z]*|nephrops|santiaguinos?|camarones?|carabineros?|"
        r"quisquillas?|buey\s+de\s+mar|txangurro|langostino)\b"
    ),
    "moluscos": re.compile(
        r"\b(?:mussels?|mejillon(?:es)?|moules?|clams?|almejas?|palourdes?|oysters?|ostras?|huitres?|"
        r"squids?|calamar(?:es)?|calmars?|octopus|pulpo|poulpe|cuttlefish|sepia|chipiron(?:es)?|"
        r"snails?|caracol(?:es)?|escargots?|scallops?|vieiras?|coquilles?|whelks?|bulots?|abalone|"
        r"cockles?|berberechos?|razor\s+clams?|navajas?|mollus[a-z]*|moluscos?|zamburinas?|"
        r"chocos?|potas?|volandeiras?|coquillage|seafood|mariscos?|fruits\s+de\s+mer|paella\s+de\s+marisco|"
        r"gulas?|angulas?|pepitona|coquina|coquinas|bigaro|bigaros|caracola|lapas?|limpets?|"
        r"periwinkles?|whelk)\b"
    ),
    "cacahuetes": re.compile(
        r"\b(?:peanuts?|cacahuetes?|cacahuates?|mani|arachides?|cacahuetes?|groundnuts?|"
        r"peanut\s+butter|mantequilla\s+de\s+cacahuete|satay|arachide)\b"
    ),
    "frutos_de_cascara": re.compile(
        r"\b(?:almonds?|almendras?|amandes?|walnuts?|nueces|nuez|noix|hazelnuts?|avellanas?|noisettes?|"
        r"cashews?|anacardos?|noix\s+de\s+cajou|pistachios?|pistachos?|pistaches?|pecans?|pacanas?|"
        r"macadamias?|brazil\s+nuts?|nueces\s+de\s+brasil|marzipan|mazapan|massepain|turron|praline|"
        r"pralin|nougat|nutella|gianduja|nuts?|frutos\s+secos|fruits\s+a\s+coque|orgeat|horchata\s+de\s+almendra|"
        r"nocilla|crema\s+de\s+avellanas|pate\s+de\s+almendra|almond\s+paste|mixed\s+nuts?|"
        r"trail\s+mix|frutos\s+de\s+cascara|cascara)\b"
    ),
    "soja": re.compile(
        r"\b(?:soy|soya|soja|soybeans?|tofu|tempeh|miso|edamame|natto|shoyu|tamari|soy\s+sauce|"
        r"salsa\s+de\s+soja|sauce\s+soja|yuba|okara|textured\s+vegetable\s+protein|tvp|proteina\s+de\s+soja|"
        r"soybean\s+oil|lecithin|lecitina|lecithine|germinados\s+de\s+soja|brotes\s+de\s+soja|"
        r"soy\s+milk|leche\s+de\s+soja|bebida\s+de\s+soja|lait\s+de\s+soja)\b"
    ),
    "apio": re.compile(
        r"\b(?:celery|celeriac|apio|apio\s+nabo|celeri|celeri[- ]rave|celery\s+salt|sal\s+de\s+apio)\b"
    ),
    "mostaza": re.compile(r"\b(?:mustard|mostaza|moutarde|dijon)\b"),
    "sesamo": re.compile(
        r"\b(?:sesame|sesamo|tahini|tahina|tahin|gomasio|halva|halvah|jalva|sesame\s+seeds?|"
        r"semillas\s+de\s+sesamo|graines\s+de\s+sesame|pan\s+de\s+sesamo|hummus|humus|hummous)\b"
    ),
    "sulfitos": re.compile(
        r"\b(?:sulfit[a-z]*|sulphit[a-z]*|sulfured|sulphured|sulfurado|sulphur\s+dioxide|"
        r"sulfur\s+dioxide|dioxido\s+de\s+azufre|anhydride\s+sulfureux|wine|wines|vino|vinos|vin|"
        r"champagne|cava|vermouth|vermut|sherry|jerez|port\s+wine|vinagre\s+de\s+vino|wine\s+vinegar|"
        r"e22[0-8]|dried\s+apricots?|orejones|albaricoques?\s+secos?|abricots?\s+secs?|"
        r"sidra|cider|cidre)\b"
    ),
    "altramuces": re.compile(r"\b(?:lupins?|lupines?|lupini|altramuz|altramuces|tarwi)\b"),
}


def _strip_false_friends(normalized: str, code: str) -> str:
    if code == "lacteos":
        return _NOT_MILK.sub(" ", normalized)
    if code == "frutos_de_cascara":
        return _NOT_NUT.sub(" ", normalized)
    if code == "huevos":
        return _NOT_EGG.sub(" ", normalized)
    if code == "pescado":
        return _NOT_FISH.sub(" ", normalized)
    if code == "gluten":
        return _NOT_GLUTEN.sub(" ", normalized)
    return normalized


# Categorías que por sí solas ya implican un alérgeno (USDA en inglés, BEDCA en
# español), siempre además de las palabras clave del nombre.
_CATEGORY_HINTS: tuple[tuple[re.Pattern[str], frozenset[str]], ...] = (
    (re.compile(r"\blacteos\b|\bdairy\b"), frozenset({"lacteos"})),
    (re.compile(r"\bhuevos\b"), frozenset({"huevos"})),
    (re.compile(r"\bpescados?\b|\bfinfish\b|\bshellfish\b|\bmariscos?\b"), frozenset({"pescado"})),
    (re.compile(r"\bbaked\s+products\b|\bbolleria\b|\breposteria\b|\bpasta\b|\bfast\s+foods\b"), frozenset({"gluten"})),
    (re.compile(r"\bsoups?,\s+sauces\b|\bsalsas?\b|\bsopas?\b"), frozenset({"gluten"})),
)


def classify_generic(
    name_es: str | None, name_en: str | None = None, category: str | None = None
) -> set[str]:
    """Códigos de alérgeno inferidos para un alimento genérico. Ver el aviso del
    módulo: heurística que prefiere errar por exceso."""
    found: set[str] = set()
    for text in (name_es, name_en):
        if not text:
            continue
        normalized = _normalize(text)
        for code, pattern in _RULES.items():
            if code in found:
                continue
            if pattern.search(_strip_false_friends(normalized, code)):
                found.add(code)
    if category:
        normalized_category = _normalize(category)
        for pattern, codes in _CATEGORY_HINTS:
            if pattern.search(normalized_category):
                # "Dairy and Egg Products" mezcla lácteos y huevos: solo se añade
                # la pista de lácteos si el nombre no dice que es un huevo.
                if codes == {"lacteos"} and "huevos" in found and "lacteos" not in found:
                    continue
                found |= codes
    return found
