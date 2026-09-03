#!/usr/bin/env bash
# Añade las columnas nuevas a una base de datos que ya tenía datos.
# Es seguro ejecutarlo varias veces.
set -euo pipefail
cd "$(dirname "$0")/.."

USUARIO=$(grep '^POSTGRES_USER=' .env | cut -d= -f2)
BASE=$(grep '^POSTGRES_DB=' .env | cut -d= -f2)

echo ">> Añadiendo columnas nuevas si faltan"
docker compose exec -T db psql -U "$USUARIO" -d "$BASE" <<'SQL'
ALTER TABLE trips ADD COLUMN IF NOT EXISTS hora_salida     VARCHAR(5);
ALTER TABLE trips ADD COLUMN IF NOT EXISTS nocturno        BOOLEAN       NOT NULL DEFAULT FALSE;
ALTER TABLE trips ADD COLUMN IF NOT EXISTS recargo_pct     NUMERIC(10,2) NOT NULL DEFAULT 0;
ALTER TABLE trips ADD COLUMN IF NOT EXISTS recargo_importe NUMERIC(10,2) NOT NULL DEFAULT 0;
ALTER TABLE trips ADD COLUMN IF NOT EXISTS registrado_por_id INTEGER REFERENCES users(id);
SQL

echo ">> Reiniciando la aplicación"
docker compose restart app
echo "Listo."
