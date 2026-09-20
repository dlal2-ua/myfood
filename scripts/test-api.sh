#!/usr/bin/env bash
# Corre la suite de la API contra una BASE DE DATOS DESECHABLE, nunca contra la de
# producción (mismo Postgres, otra base). Uso, desde cualquier sitio del repo:
#
#   scripts/test-api.sh                  # suite completa
#   scripts/test-api.sh tests/test_chat.py -k voice
#
# Crea `myfood_test` (la vacía si existe), aplica las migraciones, ejecuta pytest y
# la borra. Lee las credenciales de infra/.env (con sudo, es 0600 de root) y las
# vuelca a un fichero temporal 0600 que se borra siempre al salir.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="myfood_test"
ENV_TMP="$(mktemp)"
trap 'rm -f "$ENV_TMP"; curl -s -o /dev/null -X DELETE -H "Authorization: Bearer ${MEILI_MASTER_KEY:-}" "${MEILI_URL:-http://127.0.0.1:1}/indexes/foods_test"; sudo docker exec infra-postgres-1 psql -U myfood -d myfood -q -c "DROP DATABASE IF EXISTS ${DB};" >/dev/null 2>&1 || true' EXIT

sudo install -m 600 -o "$(id -un)" "$ROOT/infra/.env" "$ENV_TMP"
container_ip() { sudo docker inspect "$1" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'; }

sudo docker exec infra-postgres-1 psql -U myfood -d myfood -q \
  -c "DROP DATABASE IF EXISTS ${DB};" -c "CREATE DATABASE ${DB} OWNER myfood;"

set -a
# shellcheck disable=SC1090
source "$ENV_TMP"
set +a
export POSTGRES_HOST="$(container_ip infra-postgres-1)" POSTGRES_DB="$DB"
export REDIS_URL="redis://$(container_ip infra-redis-1):6379/0"
export MEILI_URL="http://$(container_ip infra-meilisearch-1):7700"
# Índice propio: los tests indexan y borran alimentos, no deben tocar el de producción.
export MEILI_INDEX="foods_test"

cd "$ROOT/apps/api"
uv run alembic upgrade head >/dev/null
uv run pytest -q "$@"
