from fastapi import FastAPI

from myfood.chat import router as chat
from myfood.errors import AppError, app_error_handler, unhandled_exception_handler
from myfood.routers import (
    admin,
    ai,
    auth,
    calc,
    consents,
    diet_plans,
    fasting,
    favorites,
    foods,
    gamification,
    health,
    household,
    log,
    notification_rules,
    pantry,
    privacy,
    profile,
    progress,
    push,
    receipts,
    recipes,
    restrictions,
    shopping_list,
    supplements,
    water,
)

app = FastAPI(title="MyFood API", version="0.1.0")

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(consents.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(calc.router, prefix="/api")
app.include_router(foods.router, prefix="/api")
app.include_router(log.router, prefix="/api")
app.include_router(favorites.router, prefix="/api")
app.include_router(restrictions.router, prefix="/api")
app.include_router(shopping_list.router, prefix="/api")
app.include_router(pantry.router, prefix="/api")
app.include_router(household.router, prefix="/api")
app.include_router(gamification.router, prefix="/api")
app.include_router(progress.router, prefix="/api")
app.include_router(fasting.router, prefix="/api")
app.include_router(privacy.router, prefix="/api")
app.include_router(supplements.router, prefix="/api")
app.include_router(water.router, prefix="/api")
app.include_router(push.router, prefix="/api")
app.include_router(notification_rules.router, prefix="/api")
app.include_router(diet_plans.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(recipes.router, prefix="/api")
app.include_router(receipts.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
