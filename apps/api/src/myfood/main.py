from fastapi import FastAPI

from myfood.errors import AppError, app_error_handler, unhandled_exception_handler
from myfood.routers import (
    admin,
    ai,
    auth,
    calc,
    consents,
    diet_plans,
    favorites,
    foods,
    health,
    log,
    notification_rules,
    profile,
    push,
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
app.include_router(supplements.router, prefix="/api")
app.include_router(water.router, prefix="/api")
app.include_router(push.router, prefix="/api")
app.include_router(notification_rules.router, prefix="/api")
app.include_router(diet_plans.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
