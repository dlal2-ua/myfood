#!/usr/bin/env bash
# Imprime un código de invitación nuevo para que los guiones de `apps/web/e2e` puedan
# registrar su cuenta desechable con la instancia en «solo con invitación».
#
#   INVITE_CODE=$(scripts/e2e-invite.sh) node apps/web/e2e/foods.cjs
#
# Cada código sirve una sola vez, así que hace falta uno por ejecución. Se inserta
# directamente en la base de datos a propósito: generarlo por el API exigiría la sesión del
# administrador real, que los guiones no deben usar nunca.
set -euo pipefail

DB="${DB:-myfood}"
# `head -c` cierra la tubería y mata a `tr` con SIGPIPE, que con `pipefail` aborta el guion:
# se lee un bloque de una vez y se recorta en bash.
RAW="$(LC_ALL=C tr -dc 'ABCDEFGHJKMNPQRSTUVWXYZ23456789' < <(dd if=/dev/urandom bs=512 count=1 2>/dev/null))"
CODE="${RAW:0:5}-${RAW:5:5}"

sudo docker exec infra-postgres-1 psql -U myfood -d "$DB" -q -t -A \
  -c "INSERT INTO invites (code, note) VALUES ('$CODE', 'e2e');" >/dev/null

echo "$CODE"
