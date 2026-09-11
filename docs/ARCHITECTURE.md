# MyFood — Arquitectura

| Componente | Elección | Versión |
|---|---|---|
| Backend | FastAPI (Python) | 3.12+ target, `uv` como gestor |
| Base de datos | PostgreSQL + pgvector + pg_trgm | 16 (`pgvector/pgvector:pg16`) |
| Buscador | Meilisearch | 1.x |
| Caché / colas | Redis | 7 |
| Frontend | Next.js (React) PWA | Next 15, React 19 |
| App móvil | Capacitor (Fase 6) | 7 |
| LLM | Claude vía Claude Agent SDK + `claude setup-token` | — |
| Auth | Sesiones httpOnly + Redis, multiusuario desde el día 1 | — |
| Despliegue | Docker Compose en `/var/apps/propias-app/myfood/` | — |
| Voz (Fase 8) | faster-whisper autoalojado (GPU local) | única excepción a "sin IA local" |

Regla de oro: la IA nunca calcula números nutricionales. Propone estructura; el backend recalcula todo contra la base de datos propia.

Esquema de base de datos, contrato de API y pseudocódigo normativo de fórmulas: página de Notion "📘 MyFood (instrucciones para Claude)", secciones 6-9.

## Almacenamiento

`data/postgres`, `data/redis` y `data/meili` (bajo `infra/`) viven en el SSD (raíz del sistema, `/dev/mapper/ubuntu--vg-ubuntu--lv`), por velocidad. Las imágenes de alimentos no: `data/images` en `apps/api` (montado en el contenedor `api`) es un **symlink** a `/mnt/hdd1tb/myfood/images`, el HDD de 1 TB del servidor — así el bind mount del `docker-compose.yml` sigue siendo literalmente `/var/apps/propias-app/myfood/data/images:/data/images` (igual que en la especificación), pero el contenido real no ocupa el SSD.

## Monorepo

```
myfood/
├── apps/api/       # FastAPI — backend, motor de dietas, iafood
├── apps/web/       # Next.js PWA
├── apps/mobile/    # Capacitor (Fase 6)
├── packages/shared/
├── etl/            # ingesta de OFF, USDA, BEDCA, CIQUAL
├── infra/          # docker-compose.yml + .env.example
└── docs/
```
