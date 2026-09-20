# Backup de MyFood

Copia nocturna al NAS Cochera (`/mnt/cochera/backups/myfood/`), independiente del
`backup-al-cochera.sh` general del servidor (que solo cubre Nextcloud e Immich).

| Qué | Dónde | Retención |
|---|---|---|
| `pg_dump` completo (formato custom) | `daily/myfood_AAAA-MM-DD_HHMM.dump` | 14 días |
| Copia de los domingos | `weekly/` | 90 días |
| `infra/.env` (ENCRYPTION_KEY, SECRET_KEY, contraseñas) y `data/config` | `config/` | 90 días |

**Sin el `.env` el volcado no sirve:** el perfil de salud, las medidas y el token de iafood
están cifrados en la BD con `ENCRYPTION_KEY`. Por eso se copia también (0600). Si no quieres
esa clave en el NAS, guárdala en tu gestor de contraseñas y quita la copia del script.

## Instalar

```bash
sudo install -m 750 infra/backup/backup-myfood.sh /usr/local/bin/backup-myfood.sh
# crontab de root:
30 3 * * * /usr/local/bin/backup-myfood.sh
```

Log: `/var/log/backup-myfood.log`. Un fallo sale con código ≠ 0 y una línea `ERROR:` en el log.

## Restaurar (probado el día que se creó)

```bash
# 1. BD nueva y restauración
docker exec infra-postgres-1 psql -U myfood -d myfood -c "CREATE DATABASE myfood_restore OWNER myfood;"
docker exec -i infra-postgres-1 pg_restore -U myfood -d myfood_restore --no-owner --role=myfood \
  < /mnt/cochera/backups/myfood/daily/myfood_AAAA-MM-DD_HHMM.dump
# 2. Recuperar infra/.env de config/ (mismo ENCRYPTION_KEY) antes de arrancar la app
# 3. Apuntar POSTGRES_DB a la base restaurada (o renombrarla) y `docker compose up -d`
```
