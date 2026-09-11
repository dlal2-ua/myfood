"""Suplementación (Fase 3, "Suplementación e hidratación") — catálogo,
horarios, stock y registro de tomas.

Aislamiento multiusuario (R3 + RLS, sección 22): `supplements` y
`supplement_log` tienen `user_id` propio y ya están sujetas a políticas RLS
(migración 0002) — el rol de aplicación nunca ve filas de otro usuario en
esas tablas, ni aunque el código de este router tuviera un bug. `supplement_stock`
también tiene política RLS propia (filtra por `supplement_id IN (SELECT id
FROM supplements WHERE user_id = ...)`, ver la migración). `supplement_schedules`
es la excepción: no está en la lista de tablas RLS de la migración 0002 (no
tiene `user_id` ni una FK indirecta que RLS pueda usar sin ese salto), así que
cada acceso a un horario pasa primero por `_get_supplement` (que sí está
protegido por RLS + comprobación explícita) y solo después se resuelve el
horario comprobando que su `supplement_id` coincide con ese suplemento ya
verificado — es la única barrera para esa tabla, análoga al filtrado manual
`WHERE user_id = ...` que R3 exige para cualquier tabla sin RLS propia.

Elección de diseño para `POST /{id}/restock`: el body es `{doses_added}`
(incremento), no `{doses_remaining}` (valor absoluto) — "restock" se lee
como "añadir un envase nuevo", que es el caso de uso principal, y evita que
el cliente tenga que conocer el valor actual para no pisarlo por accidente.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, time
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Food, Supplement, SupplementLog, SupplementSchedule, SupplementStock
from myfood.deps import get_current_user_id, get_db
from myfood.errors import AppError

router = APIRouter(prefix="/supplements", tags=["supplements"])

LOW_STOCK_DAYS_THRESHOLD = 5


async def _get_supplement(session: AsyncSession, user_id: UUID, supplement_id: UUID) -> Supplement:
    supplement = await session.get(Supplement, supplement_id)
    if supplement is None or supplement.user_id != user_id:
        raise AppError("SUPPLEMENT_NOT_FOUND", "No existe ese suplemento.", status_code=404)
    return supplement


async def _get_schedule(
    session: AsyncSession, supplement_id: UUID, schedule_id: UUID
) -> SupplementSchedule:
    """El llamador debe haber verificado ya la propiedad de `supplement_id`
    con `_get_supplement` — ver docstring del módulo sobre por qué esta tabla
    necesita esta comprobación explícita en vez de apoyarse en RLS."""
    schedule = await session.get(SupplementSchedule, schedule_id)
    if schedule is None or schedule.supplement_id != supplement_id:
        raise AppError("SCHEDULE_NOT_FOUND", "No existe ese horario.", status_code=404)
    return schedule


async def _get_food(session: AsyncSession, food_id: UUID) -> Food:
    food = await session.get(Food, food_id)
    if food is None:
        raise AppError("FOOD_NOT_FOUND", "No existe ese alimento.", status_code=404)
    return food


def _doses_per_day(schedules: list[SupplementSchedule]) -> float:
    """Estimación simple: cada horario aporta una toma en los días que
    cubre — se promedia esa frecuencia semanal a un valor diario. No
    distingue horarios duplicados ni tamaños de dosis distintos entre sí
    (todas las tomas cuentan como 1 dosis, igual que el log)."""
    if not schedules:
        return 0.0
    weekly_doses = sum(len(s.days_of_week) for s in schedules)
    return weekly_doses / 7


def _stock_projection(
    doses_remaining: float | None, schedules: list[SupplementSchedule]
) -> tuple[float | None, bool]:
    if doses_remaining is None:
        return None, False
    doses_per_day = _doses_per_day(schedules)
    if doses_per_day <= 0:
        return None, False
    days_remaining = round(doses_remaining / doses_per_day, 1)
    return days_remaining, days_remaining <= LOW_STOCK_DAYS_THRESHOLD


class SupplementIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: str = Field(min_length=1, max_length=50)
    dose_amount: float = Field(gt=0)
    dose_unit: str = Field(min_length=1, max_length=20)
    doses_per_container: int | None = Field(default=None, gt=0)
    price_per_container: float | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=2000)
    food_id: UUID | None = None


class SupplementPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    type: str | None = Field(default=None, min_length=1, max_length=50)
    dose_amount: float | None = Field(default=None, gt=0)
    dose_unit: str | None = Field(default=None, min_length=1, max_length=20)
    doses_per_container: int | None = Field(default=None, gt=0)
    price_per_container: float | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=2000)
    food_id: UUID | None = None
    is_active: bool | None = None


class ScheduleIn(BaseModel):
    time_of_day: time
    days_of_week: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7])
    with_food: bool = False

    @field_validator("days_of_week")
    @classmethod
    def _valid_days(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("days_of_week no puede estar vacío.")
        if any(d < 1 or d > 7 for d in value):
            raise ValueError("Cada día debe estar entre 1 (lunes) y 7 (domingo).")
        return sorted(set(value))


class RestockIn(BaseModel):
    doses_added: float = Field(gt=0)


class LogDoseIn(BaseModel):
    log_date: date
    skipped: bool = False


class ScheduleOut(BaseModel):
    id: UUID
    time_of_day: str
    days_of_week: list[int]
    with_food: bool


def _schedule_to_out(schedule: SupplementSchedule) -> ScheduleOut:
    return ScheduleOut(
        id=schedule.id,
        time_of_day=schedule.time_of_day.strftime("%H:%M"),
        days_of_week=list(schedule.days_of_week),
        with_food=schedule.with_food,
    )


class SupplementOut(BaseModel):
    id: UUID
    name: str
    type: str
    dose_amount: float
    dose_unit: str
    doses_per_container: int | None
    price_per_container: float | None
    notes: str | None
    is_active: bool
    food_id: UUID | None
    created_at: datetime
    doses_remaining: float | None
    last_restock_at: datetime | None
    days_remaining: float | None
    low_stock: bool


def _to_out(
    supplement: Supplement,
    stock: SupplementStock | None,
    schedules: list[SupplementSchedule],
) -> SupplementOut:
    doses_remaining = float(stock.doses_remaining) if stock is not None else None
    days_remaining, low_stock = _stock_projection(doses_remaining, schedules)
    return SupplementOut(
        id=supplement.id,
        name=supplement.name,
        type=supplement.type,
        dose_amount=float(supplement.dose_amount),
        dose_unit=supplement.dose_unit,
        doses_per_container=supplement.doses_per_container,
        price_per_container=(
            float(supplement.price_per_container)
            if supplement.price_per_container is not None
            else None
        ),
        notes=supplement.notes,
        is_active=supplement.is_active,
        food_id=supplement.food_id,
        created_at=supplement.created_at,
        doses_remaining=doses_remaining,
        last_restock_at=stock.last_restock_at if stock is not None else None,
        days_remaining=days_remaining,
        low_stock=low_stock,
    )


class SupplementDetailOut(SupplementOut):
    schedules: list[ScheduleOut]


class SupplementListOut(BaseModel):
    items: list[SupplementOut]


class SupplementLogEntryOut(BaseModel):
    id: UUID
    supplement_id: UUID
    supplement_name: str
    log_date: date
    taken_at: datetime
    skipped: bool


class SupplementLogDayOut(BaseModel):
    date: date
    entries: list[SupplementLogEntryOut]


@router.post("", status_code=201)
async def create_supplement(
    body: SupplementIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> SupplementOut:
    if body.food_id is not None:
        await _get_food(session, body.food_id)

    supplement = Supplement(
        user_id=user_id,
        name=body.name,
        type=body.type,
        dose_amount=body.dose_amount,
        dose_unit=body.dose_unit,
        doses_per_container=body.doses_per_container,
        price_per_container=body.price_per_container,
        notes=body.notes,
        food_id=body.food_id,
    )
    session.add(supplement)
    await session.flush()  # necesitamos supplement.id para la fila de stock

    stock = None
    if body.doses_per_container is not None:
        # Envase nuevo: se siembra el stock con la capacidad declarada.
        stock = SupplementStock(
            supplement_id=supplement.id, doses_remaining=body.doses_per_container
        )
        session.add(stock)

    await session.commit()
    await session.refresh(supplement)
    if stock is not None:
        await session.refresh(stock)
    return _to_out(supplement, stock, [])


@router.get("")
async def list_supplements(
    include_inactive: bool = Query(default=False),
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> SupplementListOut:
    stmt = select(Supplement).where(Supplement.user_id == user_id)
    if not include_inactive:
        stmt = stmt.where(Supplement.is_active.is_(True))
    supplements = list(await session.scalars(stmt.order_by(Supplement.created_at)))
    if not supplements:
        return SupplementListOut(items=[])

    ids = [s.id for s in supplements]
    stocks = {
        stock.supplement_id: stock
        for stock in await session.scalars(
            select(SupplementStock).where(SupplementStock.supplement_id.in_(ids))
        )
    }
    schedules_by_supplement: dict[UUID, list[SupplementSchedule]] = defaultdict(list)
    for schedule in await session.scalars(
        select(SupplementSchedule).where(SupplementSchedule.supplement_id.in_(ids))
    ):
        schedules_by_supplement[schedule.supplement_id].append(schedule)

    return SupplementListOut(
        items=[
            _to_out(s, stocks.get(s.id), schedules_by_supplement.get(s.id, [])) for s in supplements
        ]
    )


@router.get("/log")
async def get_day_supplement_log(
    date: date,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> SupplementLogDayOut:
    stmt = (
        select(SupplementLog, Supplement.name)
        .join(Supplement, Supplement.id == SupplementLog.supplement_id)
        .where(SupplementLog.user_id == user_id, SupplementLog.log_date == date)
        .order_by(SupplementLog.taken_at)
    )
    rows = (await session.execute(stmt)).all()
    entries = [
        SupplementLogEntryOut(
            id=entry.id,
            supplement_id=entry.supplement_id,
            supplement_name=name,
            log_date=entry.log_date,
            taken_at=entry.taken_at,
            skipped=entry.skipped,
        )
        for entry, name in rows
    ]
    return SupplementLogDayOut(date=date, entries=entries)


@router.delete("/log/{entry_id}", status_code=204)
async def delete_log_entry(
    entry_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    entry = await session.get(SupplementLog, entry_id)
    if entry is None or entry.user_id != user_id:
        raise AppError("SUPPLEMENT_LOG_NOT_FOUND", "No existe ese registro.", status_code=404)

    if not entry.skipped:
        stock = await session.get(SupplementStock, entry.supplement_id)
        if stock is not None:
            # Deshace el descuento hecho al registrar la toma (nunca hubo
            # tope superior al incrementar, solo al decrementar).
            stock.doses_remaining = float(stock.doses_remaining) + 1

    await session.delete(entry)
    await session.commit()


@router.get("/{supplement_id}")
async def get_supplement_detail(
    supplement_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> SupplementDetailOut:
    supplement = await _get_supplement(session, user_id, supplement_id)
    stock = await session.get(SupplementStock, supplement_id)
    schedules = list(
        await session.scalars(
            select(SupplementSchedule)
            .where(SupplementSchedule.supplement_id == supplement_id)
            .order_by(SupplementSchedule.time_of_day)
        )
    )
    base = _to_out(supplement, stock, schedules)
    return SupplementDetailOut(
        **base.model_dump(), schedules=[_schedule_to_out(s) for s in schedules]
    )


@router.patch("/{supplement_id}")
async def update_supplement(
    supplement_id: UUID,
    body: SupplementPatch,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> SupplementOut:
    supplement = await _get_supplement(session, user_id, supplement_id)
    fields_set = body.model_fields_set

    if "food_id" in fields_set and body.food_id is not None:
        await _get_food(session, body.food_id)

    if "name" in fields_set and body.name is not None:
        supplement.name = body.name
    if "type" in fields_set and body.type is not None:
        supplement.type = body.type
    if "dose_amount" in fields_set and body.dose_amount is not None:
        supplement.dose_amount = body.dose_amount
    if "dose_unit" in fields_set and body.dose_unit is not None:
        supplement.dose_unit = body.dose_unit
    if "notes" in fields_set:
        supplement.notes = body.notes
    if "food_id" in fields_set:
        supplement.food_id = body.food_id
    if "price_per_container" in fields_set:
        supplement.price_per_container = body.price_per_container
    if "is_active" in fields_set and body.is_active is not None:
        supplement.is_active = body.is_active

    stock = await session.get(SupplementStock, supplement_id)
    if "doses_per_container" in fields_set:
        supplement.doses_per_container = body.doses_per_container
        if body.doses_per_container is not None and stock is None:
            # No había tamaño de envase (y por tanto no había fila de stock)
            # — al fijarlo ahora se siembra igual que en la creación.
            stock = SupplementStock(
                supplement_id=supplement_id, doses_remaining=body.doses_per_container
            )
            session.add(stock)

    await session.commit()
    await session.refresh(supplement)
    if stock is not None:
        await session.refresh(stock)
    schedules = list(
        await session.scalars(
            select(SupplementSchedule).where(SupplementSchedule.supplement_id == supplement_id)
        )
    )
    return _to_out(supplement, stock, schedules)


@router.delete("/{supplement_id}", status_code=204)
async def delete_supplement(
    supplement_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    supplement = await _get_supplement(session, user_id, supplement_id)
    await session.delete(supplement)
    await session.commit()


@router.post("/{supplement_id}/schedules", status_code=201)
async def add_schedule(
    supplement_id: UUID,
    body: ScheduleIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> ScheduleOut:
    await _get_supplement(session, user_id, supplement_id)
    schedule = SupplementSchedule(
        supplement_id=supplement_id,
        time_of_day=body.time_of_day,
        days_of_week=body.days_of_week,
        with_food=body.with_food,
    )
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    return _schedule_to_out(schedule)


@router.delete("/{supplement_id}/schedules/{schedule_id}", status_code=204)
async def delete_schedule(
    supplement_id: UUID,
    schedule_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    await _get_supplement(session, user_id, supplement_id)
    schedule = await _get_schedule(session, supplement_id, schedule_id)
    await session.delete(schedule)
    await session.commit()


@router.post("/{supplement_id}/restock")
async def restock_supplement(
    supplement_id: UUID,
    body: RestockIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> SupplementOut:
    supplement = await _get_supplement(session, user_id, supplement_id)
    stock = await session.get(SupplementStock, supplement_id)
    now = datetime.now(UTC)
    if stock is None:
        stock = SupplementStock(
            supplement_id=supplement_id, doses_remaining=body.doses_added, last_restock_at=now
        )
        session.add(stock)
    else:
        stock.doses_remaining = float(stock.doses_remaining) + body.doses_added
        stock.last_restock_at = now

    await session.commit()
    await session.refresh(supplement)
    await session.refresh(stock)
    schedules = list(
        await session.scalars(
            select(SupplementSchedule).where(SupplementSchedule.supplement_id == supplement_id)
        )
    )
    return _to_out(supplement, stock, schedules)


@router.post("/{supplement_id}/log", status_code=201)
async def log_dose(
    supplement_id: UUID,
    body: LogDoseIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> SupplementLogEntryOut:
    supplement = await _get_supplement(session, user_id, supplement_id)

    entry = SupplementLog(
        user_id=user_id,
        supplement_id=supplement_id,
        log_date=body.log_date,
        skipped=body.skipped,
    )
    session.add(entry)

    if not body.skipped:
        stock = await session.get(SupplementStock, supplement_id)
        if stock is not None:
            # Nunca por debajo de 0 — el usuario puede haber tomado una
            # dosis comprada aparte antes de registrar un reabastecimiento.
            stock.doses_remaining = max(0.0, float(stock.doses_remaining) - 1)

    await session.commit()
    await session.refresh(entry)
    return SupplementLogEntryOut(
        id=entry.id,
        supplement_id=entry.supplement_id,
        supplement_name=supplement.name,
        log_date=entry.log_date,
        taken_at=entry.taken_at,
        skipped=entry.skipped,
    )
