#!/usr/bin/env bash
# Instalador de Carpool. Despliega la aplicacion sin publicar ningun puerto
# en el host: el unico acceso desde internet es el tunel de Cloudflare.
set -euo pipefail

REPO="https://github.com/daveIT-ES/carpool.git"
DIR="$HOME/carpool"

echo ">> Clonando el repositorio"
rm -rf "$DIR"
git clone --quiet "$REPO" "$DIR"
cd "$DIR"
[ -f docker-compose.yml ] || cd carpool

chmod +x scripts/*.sh 2>/dev/null || true
mkdir -p osrm-data

echo ">> Generando configuracion"
if   [ -f env.env ];      then cp env.env .env
elif [ -f .env.example ]; then cp .env.example .env
else echo "ERROR: no encuentro la plantilla de configuracion"; exit 1
fi

SECRET=$(openssl rand -hex 32)
DBPASS=$(openssl rand -hex 16)
ADMPASS=$(openssl rand -hex 8)

read -rp "Correo del administrador: " ADMMAIL
ADMMAIL=${ADMMAIL:-admin@ejemplo.com}

echo
echo "La aplicacion quedara escuchando en el puerto 8080 de esta maquina."
echo "Apunta hacia ahi el tunel de Cloudflare que ya tengas:"
echo "    public hostname  ->  http://$(hostname -I | awk '{print $1}'):8080"
echo
echo "Si NO tienes tunel y quieres levantarlo desde este mismo compose,"
echo "pega aqui su token (Zero Trust > Networks > Tunnels). Si ya tienes"
echo "uno, dejalo vacio y pulsa Enter."
read -rp "TUNNEL_TOKEN (opcional): " TOKEN

sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET|"                              .env
sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$DBPASS|"                .env
sed -i "s|^ADMIN_EMAIL=.*|ADMIN_EMAIL=$ADMMAIL|"                           .env
sed -i "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=$ADMPASS|"                     .env
sed -i "s|^TUNNEL_TOKEN=.*|TUNNEL_TOKEN=$TOKEN|"                           .env
sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+psycopg2://carpool:$DBPASS@db:5432/carpool|" .env

printf '.env\ndata/\nosrm-data/*\n!osrm-data/.gitkeep\n__pycache__/\n*.pyc\n*.db\nbackups/\n' > .gitignore

echo ">> Preparando datos de rutas (10-20 minutos, no cierres la sesion)"
./scripts/osrm-prepare.sh

echo ">> Levantando contenedores"
if [ -n "$TOKEN" ]; then
  docker compose --profile tunnel up -d --build
else
  docker compose up -d --build
fi

echo
echo "==================================================="
echo " LISTO"
echo " Usuario:   $ADMMAIL"
echo " Password:  $ADMPASS"
echo "==================================================="
echo " Accesible en: http://$(hostname -I | awk '{print $1}'):8080"
echo " Apunta ahi tu tunel de Cloudflare (la geolocalizacion del movil"
echo " solo funciona por HTTPS, es decir a traves del tunel)."
echo " Configuracion en: $(pwd)/.env"
echo " Manual de operacion: OPERACIONES.md"
echo "==================================================="
