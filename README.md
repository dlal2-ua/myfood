# MyFood

App de nutrición, dieta, suplementación e hidratación autohospedada. Gemela nutricional de openGym.

- **Especificación completa:** ver la página de Notion "🥗 MyFood — Plan de Actuación" (el qué) y "📘 MyFood (instrucciones para Claude)" (el cómo — fuente de verdad ante cualquier duda de implementación).
- **Estado:** las fases 0–8 están implementadas y desplegadas en `develop` (catálogo y escaneo, registro diario y PWA sin conexión, suplementos e hidratación con recordatorios, motor de dietas determinista, iafood, Samsung Health, TDEE adaptativo / despensa / recetas / privacidad / 2FA y chat conversacional). Lo que queda por hacer está en la sección «Auditoría» de la página de Notion.
- **Rama de trabajo:** `dani`. Flujo: `dani` → PR → `develop` → verificación en servidor → PR → `main` → tag. Por ahora no se promociona a `main`.

## Desarrollo local

```bash
cd infra
cp .env.example .env   # rellenar secretos
docker compose up -d
docker compose exec api alembic upgrade head
docker compose ps
```

## Tests

```bash
scripts/test-api.sh                  # API: usa una BD desechable (`myfood_test`), nunca la de producción
cd apps/web && pnpm test             # frontend (vitest)
uv run pytest etl/tests              # ETL
```

Ver `docs/ARCHITECTURE.md` para las decisiones de stack y `docs/SAFETY.md` para las reglas de seguridad e IA (R1-R11).
