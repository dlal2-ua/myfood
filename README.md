# MyFood

App de nutrición, dieta, suplementación e hidratación autohospedada. Gemela nutricional de openGym.

- **Especificación completa:** ver la página de Notion "🥗 MyFood — Plan de Actuación" (el qué) y "📘 MyFood (instrucciones para Claude)" (el cómo — fuente de verdad ante cualquier duda de implementación).
- **Estado:** en desarrollo — Fase 0 (Fundaciones).
- **Rama de trabajo:** `dani`. Flujo: `dani` → PR → `develop` → verificación en servidor → PR → `main` → tag.

## Desarrollo local

```bash
cd infra
cp .env.example .env   # rellenar secretos
docker compose up -d
docker compose exec api alembic upgrade head
docker compose ps
```

Ver `docs/ARCHITECTURE.md` para las decisiones de stack y `docs/SAFETY.md` para las reglas de seguridad e IA (R1-R11).
