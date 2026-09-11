from fastapi import FastAPI

from myfood.errors import AppError, app_error_handler, unhandled_exception_handler
from myfood.routers import auth, health

app = FastAPI(title="MyFood API", version="0.1.0")

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
