"""Worker de tareas de fondo. Vacío en la Fase 0 — el ETL, las notificaciones
push y las llamadas a iafood se añaden aquí en fases posteriores; nunca deben
ejecutarse en el hilo que atiende la petición del usuario (sección 19).
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("myfood.worker")


async def main() -> None:
    logger.info("MyFood worker arrancado (sin tareas programadas todavía — Fase 0)")
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
