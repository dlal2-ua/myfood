#!/usr/bin/env bash
# Fusiona un PR de `dani` a `develop` cuando el CI está en verde, sincroniza `dani`,
# reconstruye los servicios indicados, aplica migraciones y despliega.
#
#   scripts/ship.sh <nº de PR> [servicio ...]     # por defecto: api worker web
#
# Solo para el Servidor Principal (docker compose en infra/).
set -euo pipefail

PR="${1:?uso: scripts/ship.sh <nº de PR> [servicio ...]}"
shift || true
SERVICES=("$@")
[ ${#SERVICES[@]} -gt 0 ] || SERVICES=(api worker web)
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== esperando al CI del PR #$PR =="
for _ in $(seq 1 40); do
  out="$(gh pr checks "$PR" 2>&1 || true)"
  if ! grep -q "pending" <<<"$out"; then break; fi
  sleep 15
done
echo "$out"
if grep -qE "fail" <<<"$out"; then echo "CI EN ROJO: no se fusiona"; exit 1; fi
if grep -q "pending" <<<"$out"; then echo "CI sin terminar tras 10 min: no se fusiona"; exit 1; fi

gh pr merge "$PR" --merge
gh pr view "$PR" --json state --jq .state
git fetch origin -q && git checkout dani -q && git merge origin/develop --ff-only | tail -1

cd infra
sudo docker compose build "${SERVICES[@]}" 2>&1 | tail -3
sudo docker compose up -d "${SERVICES[@]}" 2>&1 | tail -8
if printf '%s\n' "${SERVICES[@]}" | grep -qx api; then
  for _ in $(seq 1 30); do
    [ "$(sudo docker inspect infra-api-1 --format '{{.State.Health.Status}}' 2>/dev/null)" = healthy ] && break
    sleep 5
  done
  sudo docker compose exec -T api alembic upgrade head 2>&1 | tail -3
fi
sudo docker compose ps --format '{{.Name}}\t{{.Status}}' | sort
echo "SHIP DONE"
