"""Lo que el chat y el registro por texto proponen apuntar en el diario, y cómo se aplica.

Ninguno de los dos escribe directamente: describen lo que han entendido y dejan una propuesta
pendiente. Esta capa la construye con los números ya resueltos, para que la confirmación diga
exactamente qué se va a guardar — petición, calorías y macros — antes de tocar nada.

Lo normal es que cada línea sea un PLATO entero estimado por el modelo («marinera», «bocadillo
de pastrami»), con su desglose al lado y marcado como estimación
(`entry_source='ai_estimate'`): la app nunca lo enseña como dato oficial. Tres variantes:
- cada parte del plato se contrasta con los genéricos del catálogo
  (`domain/catalog_refine.py`) y, si hay uno que encaja, sus valores por 100 g sustituyen a
  los del modelo y aportan los micronutrientes; los gramos siguen siendo los estimados;
- si ese plato ya está guardado en el catálogo (`domain/estimated_dishes.py`), se usan los
  números guardados en vez de los que diga el modelo esta vez: la misma marinera pesa lo mismo
  todos los días;
- si el usuario nombró un producto concreto y el chat lo buscó, entra por su alias y sus
  valores salen del catálogo, con los gramos resueltos por `quantity_text`;
- el formato anterior (valores por 100 g que pone el modelo) lo sigue usando el respaldo web
  del registro por foto.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Food, FoodLog, FoodNutrient, ShoppingListItem, WaterLog
from myfood.domain import catalog_refine, estimated_dishes
from myfood.domain.diet_engine import CandidateFood
from myfood.domain.estimated_dishes import SavedDish
from myfood.domain.quantity_text import resolve_grams
from myfood.errors import AppError

AI_ESTIMATE_SOURCE = "ai_estimate"
CHAT_SOURCE = "chat"

MAX_ITEMS = 20
MAX_GRAMS = 5000
# Por encima de esto no es un alimento: es un error de interpretación (el aceite, lo más
# calórico que se come, ronda las 900 kcal/100 g).
MAX_KCAL_100G = 900
MAX_QUANTITY = 20
MAX_COMPONENTS = 8
# El chat apunta lo que ya has comido, así que no escribe en el futuro (decisión del usuario).
MAX_DAYS_BACK = 366

MEAL_TYPES = {"breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner", "supper"}


@dataclass
class ProposedItem:
    """Una línea de la confirmación, con sus números ya resueltos."""

    name: str
    grams: float
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    # `None` cuando el alimento no está en el catálogo y los valores los puso el modelo.
    food_id: str | None
    estimated: bool
    # De dónde salió el número cuando vino de una búsqueda web. Se enseña al usuario: si un
    # dato no viene del ETL, que se vea de dónde viene (R9).
    source_url: str | None = None
    # Cuántas unidades o raciones; `grams`, `kcal` y los macros ya son el total de todas.
    quantity: float = 1.0
    # De qué se compone el plato, por el total de lo comido: `[{name, grams, kcal}]`.
    components: list[dict] = field(default_factory=list)
    # La comida de ESTA línea cuando el mensaje reparte entre varias («desayuné… y cené…»).
    meal_type: str | None = None
    # El plato ya estaba guardado en el catálogo y se han usado sus números.
    from_catalog: bool = False
    # Micronutrientes de las partes que el catálogo ha confirmado (ya por el total comido).
    # Es una cota inferior: lo que no se confirma no aporta ninguno.
    micros: dict = field(default_factory=dict)
    # Un alimento simple («una manzana») confirmado entero: el del catálogo que lo confirma.
    catalog: str | None = None


def _round(value: float, digits: int = 1) -> float:
    return round(float(value), digits)


def validate_date(raw: str, *, today: date) -> date:
    """El chat apunta lo que ya se ha comido: hoy y días pasados, nunca el futuro."""
    try:
        day = date.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise AppError(
            "INVALID_DATE", f"No entendí la fecha «{raw}».", status_code=422
        ) from exc
    if day > today:
        raise AppError(
            "FUTURE_DATE",
            "Solo puedo apuntar lo que ya has comido, no días que aún no han llegado.",
            status_code=422,
        )
    if day < today - timedelta(days=MAX_DAYS_BACK):
        raise AppError("DATE_TOO_OLD", "Esa fecha queda demasiado atrás.", status_code=422)
    return day


def _scaled(per_100g: float, grams: float) -> float:
    return _round(per_100g * grams / 100)


async def _from_catalog(
    session: AsyncSession, candidate: CandidateFood, quantity_text: str
) -> ProposedItem:
    """Los gramos y los macros salen del catálogo, nunca del modelo (R1)."""
    food = await session.get(Food, uuid.UUID(candidate.id))
    nutrients = await session.get(FoodNutrient, uuid.UUID(candidate.id))
    if food is None or nutrients is None:
        raise AppError("FOOD_NOT_FOUND", "Ese alimento ya no está en el catálogo.", 422)

    grams = resolve_grams(
        quantity_text or "",
        float(food.serving_size_g) if food.serving_size_g else None,
        food_name=food.name_es,
        category=food.category,
    )
    grams = max(1.0, min(float(grams), MAX_GRAMS))
    return ProposedItem(
        name=food.name_es,
        grams=_round(grams),
        kcal=_scaled(float(nutrients.kcal_100g), grams),
        protein_g=_scaled(float(nutrients.protein_100g), grams),
        fat_g=_scaled(float(nutrients.fat_100g), grams),
        carbs_g=_scaled(float(nutrients.carbs_100g), grams),
        food_id=candidate.id,
        estimated=False,
    )


def _from_estimate(entry: dict) -> ProposedItem:
    """Ingrediente que no está en el catálogo: los valores por 100 g los pone el modelo y la
    línea queda marcada como estimación. Se acotan para que un error de interpretación no
    meta un número imposible en el histórico."""
    name = str(entry.get("name") or "").strip()
    if not name:
        raise AppError("MISSING_NAME", "Falta el nombre de un ingrediente.", 422)
    try:
        grams = float(entry.get("grams"))
        kcal_100g = float(entry.get("kcal_100g"))
    except (TypeError, ValueError) as exc:
        raise AppError(
            "INVALID_ESTIMATE", f"No entendí las cantidades de «{name}».", 422
        ) from exc
    if not 0 < grams <= MAX_GRAMS or not 0 <= kcal_100g <= MAX_KCAL_100G:
        raise AppError(
            "IMPLAUSIBLE_ESTIMATE",
            f"Los valores que salen para «{name}» no son plausibles.",
            422,
        )

    def macro(key: str) -> float:
        try:
            value = float(entry.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(value, 100.0))

    return ProposedItem(
        name=name,
        grams=_round(grams),
        kcal=_scaled(kcal_100g, grams),
        protein_g=_scaled(macro("protein_100g"), grams),
        fat_g=_scaled(macro("fat_100g"), grams),
        carbs_g=_scaled(macro("carbs_100g"), grams),
        food_id=None,
        estimated=True,
        source_url=str(entry.get("source_url") or "") or None,
    )


def _number(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _is_dish(entry: dict) -> bool:
    """Una línea con el formato de plato estimado (`ai/tools.py::DISH_PROPERTIES`)."""
    return "nombre" in entry


def _display_name(name: str) -> str:
    return name[:1].upper() + name[1:]


def _item_meal_type(entry: dict) -> str | None:
    meal_type = entry.get("comida")
    return meal_type if meal_type in MEAL_TYPES else None


def _from_saved_dish(dish: SavedDish, quantity: float, entry: dict) -> ProposedItem:
    """Plato que ya está en el catálogo: mandan sus números, no los que diga hoy el modelo."""
    return ProposedItem(
        name=dish.name,
        grams=_round(dish.grams * quantity),
        kcal=_round(dish.kcal * quantity),
        protein_g=_round(dish.protein_g * quantity),
        fat_g=_round(dish.fat_g * quantity),
        carbs_g=_round(dish.carbs_g * quantity),
        food_id=dish.food_id,
        estimated=True,
        quantity=quantity,
        components=[
            {
                "name": c["name"],
                "grams": _round(c["grams"] * quantity) if c.get("grams") is not None else None,
                "kcal": _round(c["kcal"] * quantity) if c.get("kcal") is not None else None,
            }
            for c in dish.components
        ],
        meal_type=_item_meal_type(entry),
        from_catalog=True,
        micros={key: round(value * quantity, 4) for key, value in (dish.micros or {}).items()},
    )


async def _from_dish(
    session: AsyncSession, entry: dict, saved: dict[str, SavedDish]
) -> ProposedItem:
    """Un plato tal y como se comió: lo estima entero el modelo y lo afina el catálogo.

    Los valores llegan por UNA unidad y aquí se multiplican por `cantidad`. Cada parte del
    desglose se contrasta con los genéricos del catálogo (`domain/catalog_refine.py`): la que
    encaja toma de ahí sus calorías, sus macros y sus micronutrientes; la que no, se queda con
    lo que estimó el modelo. Un alimento simple sin desglose («una manzana») es su única parte.

    Las calorías del plato son la suma de sus partes: así lo que se enseña debajo cuadra
    siempre con el total, que es justo lo que el usuario va a mirar. Todo se acota, igual que
    en `_from_estimate`, para que un error de interpretación no meta un número imposible."""
    name = str(entry.get("nombre") or "").strip()
    if not name:
        raise AppError("MISSING_NAME", "Falta el nombre de un plato.", 422)
    quantity = _number(entry.get("cantidad")) or 1.0
    quantity = max(0.1, min(quantity, MAX_QUANTITY))

    dish = saved.get(estimated_dishes.normalize_name(name))
    if dish is not None:
        return _from_saved_dish(dish, quantity, entry)

    grams = _number(entry.get("gramos"))
    kcal = _number(entry.get("kcal"))
    parts = []
    for raw in (entry.get("componentes") or [])[:MAX_COMPONENTS]:
        if not isinstance(raw, dict) or not str(raw.get("nombre") or "").strip():
            continue
        parts.append(
            {
                "name": str(raw["nombre"]).strip(),
                "grams": _number(raw.get("gramos")),
                "kcal": _number(raw.get("kcal")),
                "protein_g": _number(raw.get("proteina_g")),
                "fat_g": _number(raw.get("grasa_g")),
                "carbs_g": _number(raw.get("carbos_g")),
            }
        )

    def dish_macro(key: str) -> float | None:
        return _number(entry.get(key))

    macros = {
        "protein_g": dish_macro("proteina_g"),
        "fat_g": dish_macro("grasa_g"),
        "carbs_g": dish_macro("carbos_g"),
    }
    catalog_name: str | None = None
    if parts:
        micros = await catalog_refine.refine_parts(session, parts)
        if all(p["kcal"] is not None and p["kcal"] >= 0 for p in parts):
            kcal = sum(p["kcal"] for p in parts)
        for key in macros:
            # Los macros salen de las partes cuando todas los traen (del catálogo o del
            # modelo); si alguna no, vale lo que el modelo dijo del plato entero.
            if all(p[key] is not None for p in parts) or macros[key] is None:
                macros[key] = sum(p[key] or 0.0 for p in parts)
    else:
        whole = {"name": name, "grams": grams, "kcal": kcal, **macros}
        micros = await catalog_refine.refine_parts(session, [whole])
        if whole.get("catalog"):
            catalog_name = whole["catalog"]
            kcal = whole["kcal"]
            macros = {key: whole[key] for key in macros}

    if grams is None or kcal is None:
        raise AppError("INVALID_ESTIMATE", f"No entendí las cantidades de «{name}».", 422)
    if (
        not 0 < grams * quantity <= MAX_GRAMS
        or kcal < 0
        or kcal / grams * 100 > MAX_KCAL_100G
    ):
        raise AppError(
            "IMPLAUSIBLE_ESTIMATE", f"Los valores que salen para «{name}» no son plausibles.", 422
        )

    def bounded(value: float | None) -> float:
        # Ningún macro puede pesar más que el propio plato.
        return max(0.0, min(value or 0.0, grams))

    return ProposedItem(
        name=_display_name(name),
        grams=_round(grams * quantity),
        kcal=_round(kcal * quantity),
        protein_g=_round(bounded(macros["protein_g"]) * quantity),
        fat_g=_round(bounded(macros["fat_g"]) * quantity),
        carbs_g=_round(bounded(macros["carbs_g"]) * quantity),
        food_id=None,
        estimated=True,
        quantity=quantity,
        components=[
            {
                "name": p["name"],
                "grams": _round(p["grams"] * quantity) if p["grams"] is not None else None,
                "kcal": _round(p["kcal"] * quantity) if p["kcal"] is not None else None,
                # El alimento del catálogo que confirma esta parte, si lo hay.
                **({"catalog": p["catalog"]} if p.get("catalog") else {}),
            }
            for p in parts
        ],
        meal_type=_item_meal_type(entry),
        micros={key: round(value * quantity, 4) for key, value in micros.items()},
        catalog=catalog_name,
    )


async def build_payload(
    session: AsyncSession,
    args: dict,
    *,
    alias_to_candidate: dict[str, CandidateFood],
    today: date,
) -> dict:
    """Payload de la propuesta: qué se pidió, qué líneas salen y cuánto suma todo.

    Es lo que ve el usuario antes de aceptar, así que aquí ya no queda nada por calcular."""
    day = validate_date(str(args.get("date") or today.isoformat()), today=today)
    meal_type = str(args.get("meal_type") or "")
    if meal_type not in MEAL_TYPES:
        raise AppError("INVALID_MEAL_TYPE", "No entendí en qué comida apuntarlo.", 422)

    raw_items = args.get("items") or []
    if not isinstance(raw_items, list) or not raw_items:
        raise AppError("NO_ITEMS", "No hay nada que apuntar.", 422)
    if len(raw_items) > MAX_ITEMS:
        raise AppError("TOO_MANY_ITEMS", "Son demasiados alimentos de una vez.", 422)

    # Solo se cargan si hay algún plato estimado: una propuesta hecha entera con alias del
    # catálogo no los necesita.
    saved: dict[str, SavedDish] | None = None
    items: list[ProposedItem] = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        alias = entry.get("alias")
        candidate = alias_to_candidate.get(alias) if alias else None
        if candidate is not None:
            items.append(
                await _from_catalog(session, candidate, str(entry.get("quantity_text") or ""))
            )
        elif _is_dish(entry):
            if saved is None:
                saved = await estimated_dishes.load_saved(session)
            items.append(await _from_dish(session, entry, saved))
        else:
            items.append(_from_estimate(entry))

    if not items:
        raise AppError("NO_ITEMS", "No hay nada que apuntar.", 422)

    for item in items:
        item.meal_type = item.meal_type or meal_type

    return {
        "date": day.isoformat(),
        "meal_type": meal_type,
        "request": str(args.get("request") or "").strip() or None,
        "items": [item.__dict__ for item in items],
        "totals": {
            "kcal": _round(sum(i.kcal for i in items)),
            "protein_g": _round(sum(i.protein_g for i in items)),
            "fat_g": _round(sum(i.fat_g for i in items)),
            "carbs_g": _round(sum(i.carbs_g for i in items)),
        },
        "has_estimates": any(i.estimated for i in items),
    }


def summary_text(payload: dict) -> str | None:
    """La propuesta contada con palabras: el total y una línea por plato con su desglose.

    Es lo que queda escrito en la conversación. Sale de los mismos números que la tarjeta de
    confirmación —y no de lo que redacte el modelo— para que no puedan decir cosas distintas,
    y para que el siguiente mensaje («el bocadillo era la mitad») tenga a qué referirse."""
    items = payload.get("items") or []
    if not items:
        return None
    lines = []
    for item in items:
        prefix = "aprox. " if item.get("estimated") else ""
        line = f"• {item['name']}"
        if (item.get("quantity") or 1) != 1:
            line += f" ×{_round(item['quantity']):g}"
        line += f": {prefix}{round(item['kcal'])} kcal"
        parts = [
            f"{c['name']} {round(c['grams'])} g" if c.get("grams") else c["name"]
            for c in item.get("components") or []
        ]
        if parts:
            line += f" ({', '.join(parts)})"
        lines.append(line)
    approx = "Aprox. " if payload.get("has_estimates") else ""
    total = f"{approx}{round(payload['totals']['kcal'])} kcal en total".capitalize()
    text = f"{total}:\n" + "\n".join(lines)
    if payload.get("has_estimates"):
        text += "\nEs una estimación orientativa, no una medición."
    return text


async def materialize(
    session: AsyncSession,
    user_id: UUID,
    payload: dict,
    *,
    save_to_catalog: Collection[int] = (),
    saved_food_ids: list[uuid.UUID] | None = None,
) -> int:
    """Aplica TODO lo que el usuario acaba de aceptar: lo que se apunta, lo que se corrige o
    se borra, el agua y la lista de la compra. Devuelve cuántas líneas se apuntaron.

    Se guarda el snapshot ya calculado en la propuesta, no se recalcula: el usuario aceptó
    unos números concretos y son esos los que tienen que quedar.

    `save_to_catalog` son las posiciones de las líneas estimadas que el usuario ha pedido
    guardar como plato del catálogo; sus ids se añaden a `saved_food_ids` para que quien llama
    pueda indexarlos en el buscador una vez confirmada la transacción."""
    if payload.get("edits"):
        await materialize_edits(session, user_id, payload["edits"])
    if payload.get("water"):
        materialize_water(session, user_id, payload["water"])
    if payload.get("shopping"):
        materialize_shopping(session, user_id, payload["shopping"])
    if not payload.get("items"):
        await session.flush()
        return 0

    day = date.fromisoformat(payload["date"])
    meal_type = payload["meal_type"]
    rows = []
    for index, item in enumerate(payload["items"]):
        food_id = uuid.UUID(item["food_id"]) if item.get("food_id") else None
        if food_id is None and item.get("estimated") and index in save_to_catalog:
            food_id = await estimated_dishes.save_dish(session, user_id, item)
            if saved_food_ids is not None:
                saved_food_ids.append(food_id)
        rows.append(
            FoodLog(
                user_id=user_id,
                log_date=day,
                meal_type=item.get("meal_type") or meal_type,
                food_id=food_id,
                custom_name=None if food_id else item["name"],
                components=item.get("components") or None,
                grams=item["grams"],
                entry_source=AI_ESTIMATE_SOURCE if item.get("estimated") else CHAT_SOURCE,
                kcal=item["kcal"],
                protein_g=item["protein_g"],
                fat_g=item["fat_g"],
                carbs_g=item["carbs_g"],
                micros=item.get("micros") or {},
            )
        )
    session.add_all(rows)
    await session.flush()
    return len(rows)


async def read_day(session: AsyncSession, user_id: UUID, day: date) -> list[dict]:
    """Lo que el usuario tiene apuntado ese día, para que el chat pueda responder sobre él y
    referirse a una entrada concreta al corregirla o borrarla."""
    entries = list(
        await session.scalars(
            select(FoodLog)
            .where(FoodLog.user_id == user_id, FoodLog.log_date == day)
            .order_by(FoodLog.logged_at)
        )
    )
    food_ids = {e.food_id for e in entries if e.food_id is not None}
    names: dict[uuid.UUID, str] = {}
    if food_ids:
        names = {
            f.id: f.name_es
            for f in await session.scalars(select(Food).where(Food.id.in_(food_ids)))
        }
    return [
        {
            "entry_id": str(e.id),
            "meal_type": e.meal_type,
            "name": e.custom_name or (names.get(e.food_id) if e.food_id else None) or "Alimento",
            "grams": float(e.grams),
            "kcal": float(e.kcal),
            "protein_g": float(e.protein_g),
            "fat_g": float(e.fat_g),
            "carbs_g": float(e.carbs_g),
            "estimated": e.entry_source == AI_ESTIMATE_SOURCE,
        }
        for e in entries
    ]


MAX_WATER_ML = 5000


async def build_edits_payload(
    session: AsyncSession, user_id: UUID, args: dict
) -> list[dict]:
    """Correcciones y borrados sobre entradas que YA están en el diario.

    Cada cambio se resuelve contra la entrada real: si el modelo se inventa un identificador o
    apunta a algo que no es del usuario, la propuesta no llega a existir. Al cambiar los
    gramos, los macros se reescalan desde el snapshot guardado, que es lo que se aceptó en su
    día, y no desde el catálogo, que puede haber cambiado."""
    changes = args.get("changes") or []
    if not isinstance(changes, list) or not changes:
        raise AppError("NO_CHANGES", "No hay nada que cambiar.", 422)

    out: list[dict] = []
    for change in changes[:MAX_ITEMS]:
        if not isinstance(change, dict):
            continue
        try:
            entry_id = uuid.UUID(str(change.get("entry_id")))
        except ValueError as exc:
            raise AppError("INVALID_ENTRY", "No reconozco esa entrada del diario.", 422) from exc
        entry = await session.get(FoodLog, entry_id)
        if entry is None or entry.user_id != user_id:
            raise AppError("INVALID_ENTRY", "Esa entrada del diario ya no existe.", 422)

        action = change.get("action")
        if action == "delete":
            out.append({"entry_id": str(entry_id), "action": "delete", "name": _entry_name(entry)})
            continue
        if action != "update":
            raise AppError("INVALID_ACTION", "No entendí qué hacer con esa entrada.", 422)

        old_grams = float(entry.grams)
        new_grams = float(change.get("grams") or old_grams)
        if not 0 < new_grams <= MAX_GRAMS:
            raise AppError("IMPLAUSIBLE_ESTIMATE", "Esa cantidad no es plausible.", 422)
        factor = new_grams / old_grams if old_grams else 1.0
        out.append(
            {
                "entry_id": str(entry_id),
                "action": "update",
                "name": _entry_name(entry),
                "grams": _round(new_grams),
                "meal_type": change.get("meal_type") or entry.meal_type,
                "kcal": _round(float(entry.kcal) * factor),
                "protein_g": _round(float(entry.protein_g) * factor),
                "fat_g": _round(float(entry.fat_g) * factor),
                "carbs_g": _round(float(entry.carbs_g) * factor),
            }
        )
    if not out:
        raise AppError("NO_CHANGES", "No hay nada que cambiar.", 422)
    return out


def _entry_name(entry: FoodLog) -> str:
    return entry.custom_name or "Alimento"


def build_water_payload(args: dict, *, today: date) -> dict:
    ml = args.get("ml")
    try:
        ml = int(float(ml))
    except (TypeError, ValueError) as exc:
        raise AppError("INVALID_WATER", "No entendí cuánta agua.", 422) from exc
    if not 0 < ml <= MAX_WATER_ML:
        raise AppError("INVALID_WATER", "Esa cantidad de agua no es plausible.", 422)
    day = validate_date(str(args.get("date") or today.isoformat()), today=today)
    return {"date": day.isoformat(), "ml": ml}


def build_shopping_payload(args: dict, *, alias_to_candidate: dict) -> list[dict]:
    items = args.get("items") or []
    if not isinstance(items, list) or not items:
        raise AppError("NO_ITEMS", "No hay nada que añadir a la lista.", 422)
    out = []
    for entry in items[:MAX_ITEMS]:
        if not isinstance(entry, dict):
            continue
        candidate = alias_to_candidate.get(entry.get("alias")) if entry.get("alias") else None
        label = (entry.get("text") or (candidate.name_es if candidate else "")).strip()
        if not label:
            continue
        out.append({"text": label, "food_id": candidate.id if candidate else None})
    if not out:
        raise AppError("NO_ITEMS", "No hay nada que añadir a la lista.", 422)
    return out


async def materialize_edits(session: AsyncSession, user_id: UUID, edits: list[dict]) -> None:
    for change in edits:
        entry = await session.get(FoodLog, uuid.UUID(change["entry_id"]))
        if entry is None or entry.user_id != user_id:
            continue  # se borró entre la propuesta y la confirmación: no es un error
        if change["action"] == "delete":
            await session.delete(entry)
            continue
        entry.grams = change["grams"]
        entry.meal_type = change["meal_type"]
        entry.kcal = change["kcal"]
        entry.protein_g = change["protein_g"]
        entry.fat_g = change["fat_g"]
        entry.carbs_g = change["carbs_g"]


def materialize_water(session: AsyncSession, user_id: UUID, water: dict) -> None:
    session.add(
        WaterLog(user_id=user_id, log_date=date.fromisoformat(water["date"]), ml=water["ml"])
    )


def materialize_shopping(session: AsyncSession, user_id: UUID, items: list[dict]) -> None:
    for item in items:
        session.add(
            ShoppingListItem(
                user_id=user_id,
                food_id=uuid.UUID(item["food_id"]) if item.get("food_id") else None,
                free_text=None if item.get("food_id") else item["text"],
            )
        )
