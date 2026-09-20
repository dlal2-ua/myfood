"""Panel de privacidad (Fase 7, documento 2 sección 17 — "ver, exportar y
solicitar el borrado" de los propios datos de salud, RGPD art. 15/17/20).

Tres piezas:
- `GET /privacy/summary`: lo que hay, sin descargar nada todavía ("ver").
- `GET /privacy/export`: volcado JSON completo del histórico del usuario
  ("exportar" — RGPD art. 20, portabilidad).
- `POST /privacy/delete-account`: borrado real e irreversible de la cuenta
  y todo lo asociado ("solicitar el borrado" — RGPD art. 17). Se aplica a
  la cuenta entera, no solo a los datos de salud: dejar el perfil de salud
  vacío pero la cuenta viva es un estado a medias que no resuelve el
  derecho al olvido y no tiene un caso de uso real en una app personal/
  familiar autoalojada. Exige repetir la contraseña — es irreversible.

Todo pasa por los modelos ORM, nunca por SQL crudo directo a las tablas: es
la única forma de que las columnas cifradas (perfil, medidas — R4) salgan
descifradas en el export en vez de como texto cifrado ilegible.
"""

import csv
import io
import json
import zipfile
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import delete, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import (
    BodyMeasurement,
    ChatMessage,
    Consent,
    DietPlan,
    FastingWindow,
    FoodLog,
    NotificationRule,
    PantryItem,
    PlanDay,
    PlanItem,
    PlanItemAlternative,
    PlanMeal,
    Profile,
    Recipe,
    RecipeIngredient,
    ShoppingListItem,
    Supplement,
    SupplementLog,
    SupplementSchedule,
    SupplementStock,
    TdeeEstimate,
    User,
    UserFavoriteFood,
    UserRestriction,
    WaterLog,
    WaterSettings,
)
from myfood.deps import get_current_user_id, get_db
from myfood.errors import AppError
from myfood.ratelimit import guard, password_confirm_rules, record_failure, reset
from myfood.security import SESSION_COOKIE_NAME, destroy_session, verify_password

router = APIRouter(prefix="/privacy", tags=["privacy"])

# Nunca deben salir en un export ni contarse como "datos del usuario" en el
# sentido de la sección 17 — son credenciales/identificadores internos, no
# historial de salud/uso.
_EXCLUDED_COLUMNS = {"password_hash"}


def _row_to_dict(obj) -> dict:
    mapper = inspect(obj).mapper
    return {
        column.key: getattr(obj, column.key)
        for column in mapper.columns
        if column.key not in _EXCLUDED_COLUMNS
    }


async def _all_for_user(session: AsyncSession, model, user_id: UUID) -> list:
    return list(await session.scalars(select(model).where(model.user_id == user_id)))


class PrivacySummary(BaseModel):
    account_created_at: str
    measurements_count: int
    food_log_entries: int
    water_log_entries: int
    supplements_count: int
    diet_plans_count: int
    recipes_count: int


@router.get("/summary")
async def get_summary(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> PrivacySummary:
    user = await session.get(User, user_id)
    if user is None:
        raise AppError("NOT_AUTHENTICATED", "Se requiere iniciar sesión.", status_code=401)

    async def _count(model) -> int:
        return len(await _all_for_user(session, model, user_id))

    return PrivacySummary(
        account_created_at=user.created_at.isoformat(),
        measurements_count=await _count(BodyMeasurement),
        food_log_entries=await _count(FoodLog),
        water_log_entries=await _count(WaterLog),
        supplements_count=await _count(Supplement),
        diet_plans_count=await _count(DietPlan),
        recipes_count=await _count(Recipe),
    )


async def _diet_plans_with_content(session: AsyncSession, user_id: UUID) -> list[dict]:
    """Cada plan con sus días, comidas, elementos y alternativas — antes solo salía la fila del plan
    y el contenido (lo que de verdad importa de un plan) se quedaba fuera del export."""
    plans = await _all_for_user(session, DietPlan, user_id)
    if not plans:
        return []
    plan_ids = [p.id for p in plans]
    days = list(await session.scalars(select(PlanDay).where(PlanDay.plan_id.in_(plan_ids))))
    day_ids = [d.id for d in days]
    meals = (
        list(await session.scalars(select(PlanMeal).where(PlanMeal.plan_day_id.in_(day_ids))))
        if day_ids
        else []
    )
    meal_ids = [m.id for m in meals]
    items = (
        list(await session.scalars(select(PlanItem).where(PlanItem.plan_meal_id.in_(meal_ids))))
        if meal_ids
        else []
    )
    item_ids = [i.id for i in items]
    alternatives = (
        list(
            await session.scalars(
                select(PlanItemAlternative).where(PlanItemAlternative.plan_item_id.in_(item_ids))
            )
        )
        if item_ids
        else []
    )

    alternatives_by_item: dict[UUID, list[dict]] = {}
    for alternative in alternatives:
        alternatives_by_item.setdefault(alternative.plan_item_id, []).append(
            _row_to_dict(alternative)
        )
    items_by_meal: dict[UUID, list[dict]] = {}
    for item in items:
        items_by_meal.setdefault(item.plan_meal_id, []).append(
            {**_row_to_dict(item), "alternatives": alternatives_by_item.get(item.id, [])}
        )
    meals_by_day: dict[UUID, list[dict]] = {}
    for meal in sorted(meals, key=lambda m: m.sort_order):
        meals_by_day.setdefault(meal.plan_day_id, []).append(
            {**_row_to_dict(meal), "items": items_by_meal.get(meal.id, [])}
        )
    days_by_plan: dict[UUID, list[dict]] = {}
    for day in sorted(days, key=lambda d: d.day_index):
        days_by_plan.setdefault(day.plan_id, []).append(
            {**_row_to_dict(day), "meals": meals_by_day.get(day.id, [])}
        )
    return [{**_row_to_dict(p), "days": days_by_plan.get(p.id, [])} for p in plans]


async def _build_export(session: AsyncSession, user_id: UUID, user: User) -> dict:
    profile = await session.get(Profile, user_id)
    water_settings = await session.get(WaterSettings, user_id)

    recipes = await _all_for_user(session, Recipe, user_id)
    recipe_ids = [r.id for r in recipes]
    ingredients_by_recipe: dict[str, list] = {str(rid): [] for rid in recipe_ids}
    if recipe_ids:
        ingredients = await session.scalars(
            select(RecipeIngredient).where(RecipeIngredient.recipe_id.in_(recipe_ids))
        )
        for ingredient in ingredients:
            ingredients_by_recipe[str(ingredient.recipe_id)].append(_row_to_dict(ingredient))

    supplements = await _all_for_user(session, Supplement, user_id)
    supplement_ids = [s.id for s in supplements]
    schedules_by_supplement: dict[str, list] = {str(sid): [] for sid in supplement_ids}
    stock_rows: list[dict] = []
    if supplement_ids:
        schedules = await session.scalars(
            select(SupplementSchedule).where(SupplementSchedule.supplement_id.in_(supplement_ids))
        )
        for schedule in schedules:
            schedules_by_supplement[str(schedule.supplement_id)].append(_row_to_dict(schedule))
        stock_rows = [
            _row_to_dict(stock)
            for stock in await session.scalars(
                select(SupplementStock).where(SupplementStock.supplement_id.in_(supplement_ids))
            )
        ]

    async def rows(model) -> list[dict]:
        return [_row_to_dict(row) for row in await _all_for_user(session, model, user_id)]

    return {
        "account": {
            "email": user.email,
            "display_name": user.display_name,
            "locale": user.locale,
            "timezone": user.timezone,
            "created_at": user.created_at,
        },
        "profile": _row_to_dict(profile) if profile else None,
        "restrictions": await rows(UserRestriction),
        "body_measurements": await rows(BodyMeasurement),
        "food_log": await rows(FoodLog),
        "water_settings": _row_to_dict(water_settings) if water_settings else None,
        "water_log": await rows(WaterLog),
        "fasting_windows": await rows(FastingWindow),
        "supplements": [
            {**_row_to_dict(s), "schedules": schedules_by_supplement[str(s.id)]}
            for s in supplements
        ],
        "supplement_stock": stock_rows,
        "supplement_log": await rows(SupplementLog),
        "diet_plans": await _diet_plans_with_content(session, user_id),
        "recipes": [
            {**_row_to_dict(r), "ingredients": ingredients_by_recipe[str(r.id)]} for r in recipes
        ],
        "pantry_items": await rows(PantryItem),
        "shopping_list_items": await rows(ShoppingListItem),
        "favorite_foods": await rows(UserFavoriteFood),
        "tdee_estimates": await rows(TdeeEstimate),
        "notification_rules": await rows(NotificationRule),
        "chat_messages": await rows(ChatMessage),
        "consents": await rows(Consent),
    }


def _csv_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _to_csv(rows: list[dict]) -> str:
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_csv_cell(row.get(column)) for column in columns])
    return buffer.getvalue()


_README = (
    "Exportación de tus datos de MyFood (RGPD art. 20).\n\n"
    "- myfood-export.json: todo el histórico con su estructura completa (planes con sus días, "
    "comidas y elementos; recetas con sus ingredientes; suplementos con sus horarios).\n"
    "- csv/: una hoja por cada tabla con filas (registro de comidas, medidas, agua, ayunos, "
    "suplementos, chat...) para abrir en una hoja de cálculo. Las columnas con estructura "
    "(por ejemplo los días de un plan) van como JSON dentro de la celda.\n"
    "Las contraseñas, las credenciales y las suscripciones push no se incluyen.\n"
)


@router.get("/export")
async def export_data(
    format: Literal["json", "zip"] = Query(default="json"),
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Volcado de todo el histórico del usuario: JSON (por defecto) o un zip con el JSON y un CSV
    por cada tabla con filas."""
    user = await session.get(User, user_id)
    if user is None:
        raise AppError("NOT_AUTHENTICATED", "Se requiere iniciar sesión.", status_code=401)

    content = jsonable_encoder(await _build_export(session, user_id, user))
    if format == "json":
        return JSONResponse(
            content=content,
            headers={"Content-Disposition": f'attachment; filename="myfood-export-{user_id}.json"'},
        )

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("LEEME.txt", _README)
        zf.writestr("myfood-export.json", json.dumps(content, ensure_ascii=False, indent=2))
        for name, value in content.items():
            if isinstance(value, list) and value and all(isinstance(r, dict) for r in value):
                zf.writestr(f"csv/{name}.csv", _to_csv(value))
    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="myfood-export-{user_id}.zip"'},
    )


class DeleteAccountRequest(BaseModel):
    password: str


@router.post("/delete-account", status_code=204)
async def delete_account(
    body: DeleteAccountRequest,
    request: Request,
    response: Response,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    rules = password_confirm_rules("delete-account", user_id)
    await guard(*rules)
    user = await session.get(User, user_id)
    if user is None or not verify_password(body.password, user.password_hash):
        await record_failure(*rules)
        raise AppError("INVALID_CREDENTIALS", "Contraseña incorrecta.", status_code=401)
    await reset(*rules)

    # DELETE en SQL directo, no `session.delete(user)`: el ORM intentaría
    # gestionar la relación `User.profile` a mano (poner NULL en una PK, lo
    # que revienta) en vez de dejar que el ON DELETE CASCADE de cada tabla
    # con user_id (sección 6) borre el resto — perfil, medidas, registro,
    # planes, recetas, etc. — directamente en Postgres.
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()

    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        await destroy_session(token)
    response.delete_cookie(SESSION_COOKIE_NAME)
