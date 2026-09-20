#!/bin/bash
# backup-myfood.sh — copia nocturna de MyFood al NAS Cochera (documento 2, sección 18).
#
#   - pg_dump de toda la base (formato custom, comprimido) con verificación de integridad
#   - configuración de iafood (límites) y `infra/.env`  <- SIN ESTO NO SE PUEDE RESTAURAR:
#     el perfil de salud y el token de iafood están cifrados en la BD con ENCRYPTION_KEY,
#     que solo vive en ese fichero
#   - retención: 14 diarias + 12 semanales (domingos)
#   - las imágenes de producto NO se respaldan (caché regenerable); las de usuario
#     (`source='user'`) todavía no existen
#
# Instalación (una vez):  sudo install -m 750 infra/backup/backup-myfood.sh /usr/local/bin/
#   crontab de root:      30 3 * * * /usr/local/bin/backup-myfood.sh
# Restaurar: infra/backup/README.md
set -uo pipefail

NFS_MOUNT="/mnt/cochera"
DEST="$NFS_MOUNT/backups/myfood"
APP_DIR="/var/apps/propias-app/myfood"
LOG="/var/log/backup-myfood.log"
DATE="$(date +%Y-%m-%d)"
STAMP="$(date +%Y-%m-%d_%H%M)"
DAILY_KEEP_DAYS=14
WEEKLY_KEEP_DAYS=90

log() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }
fail() { log "ERROR: $*"; echo "backup-myfood: $*" >&2; exit 1; }

mountpoint -q "$NFS_MOUNT" || fail "NFS no montado en $NFS_MOUNT"
mkdir -p "$DEST/daily" "$DEST/weekly" "$DEST/config" || fail "no se pudo crear $DEST"
umask 077

TMP="$(mktemp -d "$DEST/.tmp.XXXXXX")" || fail "no se pudo crear un directorio temporal en el NAS"
trap 'rm -rf "$TMP"' EXIT

log "Iniciando backup de MyFood ($STAMP)"

# 1) Base de datos
DUMP="$TMP/myfood_${STAMP}.dump"
docker exec infra-postgres-1 pg_dump -U myfood -d myfood -Fc > "$DUMP" 2>>"$LOG" \
  || fail "pg_dump falló"
[ -s "$DUMP" ] || fail "el volcado está vacío"
# Integridad: el índice del volcado debe poder leerse y traer las tablas clave.
docker exec -i infra-postgres-1 pg_restore --list < "$DUMP" > "$TMP/toc.txt" 2>>"$LOG" \
  || fail "el volcado no es legible (pg_restore --list falló)"
for table in users foods food_log diet_plans; do
  grep -q "TABLE DATA public $table " "$TMP/toc.txt" || fail "al volcado le falta la tabla $table"
done
SIZE="$(du -h "$DUMP" | cut -f1)"

# 2) Configuración y secretos necesarios para poder restaurar
cp "$APP_DIR/infra/.env" "$TMP/env" || fail "no se pudo copiar infra/.env"
if [ -d "$APP_DIR/data/config" ]; then
  tar -C "$APP_DIR/data" -czf "$TMP/config.tgz" config || fail "no se pudo empaquetar data/config"
fi

# 3) Publicación atómica: primero al directorio temporal, luego rename
mv "$DUMP" "$DEST/daily/myfood_${STAMP}.dump" || fail "no se pudo publicar el volcado"
cp "$TMP/env" "$DEST/config/env_${DATE}" && chmod 600 "$DEST/config/env_${DATE}"
[ -f "$TMP/config.tgz" ] && cp "$TMP/config.tgz" "$DEST/config/config_${DATE}.tgz"
if [ "$(date +%u)" = "7" ]; then
  cp "$DEST/daily/myfood_${STAMP}.dump" "$DEST/weekly/myfood_${STAMP}.dump"
fi

# 4) Retención
find "$DEST/daily" -name 'myfood_*.dump' -mtime +"$DAILY_KEEP_DAYS" -delete
find "$DEST/weekly" -name 'myfood_*.dump' -mtime +"$WEEKLY_KEEP_DAYS" -delete
find "$DEST/config" -type f -mtime +"$WEEKLY_KEEP_DAYS" -delete

log "Backup completado: myfood_${STAMP}.dump ($SIZE)"
