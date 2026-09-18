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

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import delete, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import (
    BodyMeasurement,
    Consent,
    DietPlan,
    FoodLog,
    NotificationRule,
    PantryItem,
    Profile,
    Recipe,
    RecipeIngredient,
    ShoppingListItem,
    Supplement,
    SupplementLog,
    SupplementSchedule,
    TdeeEstimate,
    User,
    UserFavoriteFood,
    WaterLog,
    WaterSettings,
)
from myfood.deps import get_current_user_id, get_db
from myfood.errors import AppError
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


@router.get("/export")
async def export_data(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    user = await session.get(User, user_id)
    if user is None:
        raise AppError("NOT_AUTHENTICATED", "Se requiere iniciar sesión.", status_code=401)

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
    if supplement_ids:
        schedules = await session.scalars(
            select(SupplementSchedule).where(SupplementSchedule.supplement_id.in_(supplement_ids))
        )
        for schedule in schedules:
            schedules_by_supplement[str(schedule.supplement_id)].append(_row_to_dict(schedule))

    export = {
        "account": {
            "email": user.email,
            "display_name": user.display_name,
            "locale": user.locale,
            "timezone": user.timezone,
            "created_at": user.created_at,
        },
        "profile": _row_to_dict(profile) if profile else None,
        "body_measurements": [_row_to_dict(m) for m in await _all_for_user(
            session, BodyMeasurement, user_id
        )],
        "food_log": [_row_to_dict(e) for e in await _all_for_user(session, FoodLog, user_id)],
        "water_settings": _row_to_dict(water_settings) if water_settings else None,
        "water_log": [_row_to_dict(e) for e in await _all_for_user(session, WaterLog, user_id)],
        "supplements": [
            {**_row_to_dict(s), "schedules": schedules_by_supplement[str(s.id)]}
            for s in supplements
        ],
        "supplement_log": [
            _row_to_dict(e) for e in await _all_for_user(session, SupplementLog, user_id)
        ],
        "diet_plans": [_row_to_dict(p) for p in await _all_for_user(session, DietPlan, user_id)],
        "recipes": [
            {**_row_to_dict(r), "ingredients": ingredients_by_recipe[str(r.id)]} for r in recipes
        ],
        "pantry_items": [
            _row_to_dict(i) for i in await _all_for_user(session, PantryItem, user_id)
        ],
        "shopping_list_items": [
            _row_to_dict(i) for i in await _all_for_user(session, ShoppingListItem, user_id)
        ],
        "favorite_foods": [
            _row_to_dict(f) for f in await _all_for_user(session, UserFavoriteFood, user_id)
        ],
        "tdee_estimates": [
            _row_to_dict(e) for e in await _all_for_user(session, TdeeEstimate, user_id)
        ],
        "notification_rules": [
            _row_to_dict(r) for r in await _all_for_user(session, NotificationRule, user_id)
        ],
        "consents": [_row_to_dict(c) for c in await _all_for_user(session, Consent, user_id)],
    }

    content = jsonable_encoder(export)
    return JSONResponse(
        content=content,
        headers={
            "Content-Disposition": f'attachment; filename="myfood-export-{user_id}.json"'
        },
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
    user = await session.get(User, user_id)
    if user is None or not verify_password(body.password, user.password_hash):
        raise AppError("INVALID_CREDENTIALS", "Contraseña incorrecta.", status_code=401)

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
