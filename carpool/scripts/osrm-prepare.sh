#!/usr/bin/env bash
# Descarga y preprocesa un extracto de OpenStreetMap para OSRM.
# Uso:  ./scripts/osrm-prepare.sh [url-del-extracto]
# Por defecto: Cataluña (~250 MB de descarga, ~10-20 min de proceso).
set -euo pipefail

URL="${1:-https://download.geofabrik.de/europe/spain/cataluna-latest.osm.pbf}"
DIR="$(cd "$(dirname "$0")/.." && pwd)/osrm-data"
IMG="ghcr.io/project-osrm/osrm-backend:latest"

mkdir -p "$DIR"
FILE="$(basename "$URL")"
BASE="${FILE%.osm.pbf}"

if [ ! -f "$DIR/$FILE" ]; then
  echo ">> Descargando $FILE"
  curl -L --fail -o "$DIR/$FILE" "$URL"
fi

echo ">> osrm-extract (necesita RAM: cuenta ~2-3 GB para Cataluña)"
docker run --rm -v "$DIR:/data" "$IMG" osrm-extract -p /opt/car.lua "/data/$FILE"
echo ">> osrm-partition"
docker run --rm -v "$DIR:/data" "$IMG" osrm-partition "/data/$BASE.osrm"
echo ">> osrm-customize"
docker run --rm -v "$DIR:/data" "$IMG" osrm-customize "/data/$BASE.osrm"

echo
echo "Listo. Pon esto en tu .env:"
echo "OSM_BASE=$BASE"
