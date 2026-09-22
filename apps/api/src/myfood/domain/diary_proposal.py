"""Lo que el chat propone apuntar en el diario, y cómo se aplica al aceptarlo.

El chat no escribe nunca directamente (R1): describe lo que ha entendido y deja una propuesta
pendiente. Esta capa la construye con los números ya calculados, para que la confirmación diga
exactamente qué se va a guardar — petición, calorías y macros — antes de tocar nada.

Un plato compuesto («tostada de tomate con queso manchego») se descompone en ingredientes:
- el que existe en el catálogo entra por su alias, y sus valores salen del dato oficial con
  los gramos resueltos por `quantity_text`, los mismos que en cualquier otro registro;
- el que no existe entra con los valores que pone el modelo, marcado como estimación
  (`entry_source='ai_estimate'`), para que se vea siempre qué parte de los números del día no
  viene de una fuente oficial.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Food, FoodLog, FoodNutrient, ShoppingListItem, WaterLog
from myfood.domain.diet_engine import CandidateFood
from myfood.domain.quantity_text import resolve_grams
from myfood.errors import AppError

AI_ESTIMATE_SOURCE = "ai_estimate"
CHAT_SOURCE = "chat"

MAX_ITEMS = 20
MAX_GRAMS = 5000
# Por encima de esto no es un alimento: es un error de interpretación (el aceite, lo más
# calórico que se come, ronda las 900 kcal/100 g).
MAX_KCAL_100G = 900
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
        else:
            items.append(_from_estimate(entry))

    if not items:
        raise AppError("NO_ITEMS", "No hay nada que apuntar.", 422)

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


async def materialize(session: AsyncSession, user_id: UUID, payload: dict) -> int:
    """Aplica TODO lo que el usuario acaba de aceptar: lo que se apunta, lo que se corrige o
    se borra, el agua y la lista de la compra. Devuelve cuántas líneas se apuntaron.

    Se guarda el snapshot ya calculado en la propuesta, no se recalcula: el usuario aceptó
    unos números concretos y son esos los que tienen que quedar."""
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
    for item in payload["items"]:
        rows.append(
            FoodLog(
                user_id=user_id,
                log_date=day,
                meal_type=meal_type,
                food_id=uuid.UUID(item["food_id"]) if item.get("food_id") else None,
                custom_name=None if item.get("food_id") else item["name"],
                grams=item["grams"],
                entry_source=AI_ESTIMATE_SOURCE if item.get("estimated") else CHAT_SOURCE,
                kcal=item["kcal"],
                protein_g=item["protein_g"],
                fat_g=item["fat_g"],
                carbs_g=item["carbs_g"],
                micros={},
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
