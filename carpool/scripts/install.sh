#!/usr/bin/env bash
# Instalador de Carpool.
#
#   Instalacion nueva:   bash install.sh
#   Desde un clon ya hecho:  cd carpool && bash scripts/install.sh
#
# Se puede pasar la URL de otro extracto de OpenStreetMap:
#   bash install.sh https://download.geofabrik.de/europe/spain-latest.osm.pbf
set -euo pipefail

REPO="https://github.com/daveIT-ES/carpool.git"
EXTRACTO="${1:-}"

fallo() { echo; echo "ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------- requisitos
for orden in git docker openssl curl; do
  command -v "$orden" >/dev/null 2>&1 || fallo "falta '$orden'. Instalalo y repite."
done
docker compose version >/dev/null 2>&1 \
  || fallo "falta el plugin 'docker compose'. Instala docker-compose-plugin."
docker info >/dev/null 2>&1 \
  || fallo "tu usuario no puede usar docker. Ejecuta: sudo usermod -aG docker \$USER, cierra la sesion y vuelve a entrar."

# ---------------------------------------------------------------- ubicacion
# Si ya estamos dentro del proyecto (clon previo), se usa tal cual.
# Si no, se clona en ~/carpool.
BASE_DIR=""
for candidato in "$PWD" "$PWD/carpool" "$(dirname "$0")/.." "$(dirname "$0")/../carpool"; do
  if [ -f "$candidato/docker-compose.yml" ]; then
    BASE_DIR="$(cd "$candidato" && pwd)"
    break
  fi
done

if [ -n "$BASE_DIR" ]; then
  echo ">> Usando el proyecto que ya tienes en $BASE_DIR"
  cd "$BASE_DIR"
else
  DESTINO="$HOME/carpool"
  [ -e "$DESTINO" ] && fallo "$DESTINO ya existe. Borralo o ejecuta el script dentro de el."
  echo ">> Clonando el repositorio en $DESTINO"
  git clone --quiet "$REPO" "$DESTINO"
  cd "$DESTINO"
  [ -f docker-compose.yml ] || cd carpool
  [ -f docker-compose.yml ] || fallo "no encuentro docker-compose.yml en el repositorio."
fi

chmod +x scripts/*.sh 2>/dev/null || true
mkdir -p osrm-data

# ---------------------------------------------------------------- .env
if [ -f .env ]; then
  echo ">> Ya existe un .env: se conserva tal cual (no toco tus contrasenas)."
  ADMMAIL=$(grep '^ADMIN_EMAIL=' .env | cut -d= -f2-)
  ADMPASS="(la que ya tenias en .env)"
  TOKEN=$(grep '^TUNNEL_TOKEN=' .env | cut -d= -f2- || true)
else
  if   [ -f env.env ];      then cp env.env .env
  elif [ -f .env.example ]; then cp .env.example .env
  else fallo "no encuentro la plantilla de configuracion (env.env o .env.example)."
  fi

  read -rp "Correo del administrador: " ADMMAIL
  ADMMAIL=${ADMMAIL:-admin@ejemplo.com}

  IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  echo
  echo "La aplicacion escuchara en el puerto 8080 de esta maquina."
  echo "Si ya tienes un tunel de Cloudflare, apunta el public hostname a:"
  echo "    http://${IP:-IP_DE_ESTA_MAQUINA}:8080"
  echo
  echo "Si NO tienes tunel y quieres levantarlo desde este compose, pega su"
  echo "token (Zero Trust > Networks > Tunnels). Si ya tienes uno, deja el"
  echo "campo vacio y pulsa Enter."
  read -rp "TUNNEL_TOKEN (opcional): " TOKEN

  SECRET=$(openssl rand -hex 32)
  DBPASS=$(openssl rand -hex 16)
  ADMPASS=$(openssl rand -hex 8)

  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET|"               .env
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$DBPASS|" .env
  sed -i "s|^ADMIN_EMAIL=.*|ADMIN_EMAIL=$ADMMAIL|"            .env
  sed -i "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=$ADMPASS|"      .env
  sed -i "s|^TUNNEL_TOKEN=.*|TUNNEL_TOKEN=$TOKEN|"            .env
  sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+psycopg2://carpool:$DBPASS@db:5432/carpool|" .env
fi

# ---------------------------------------------------------------- datos OSM
if ls osrm-data/*.osrm.* >/dev/null 2>&1; then
  echo ">> Los datos de rutas ya estan preparados, no los vuelvo a generar."
else
  echo ">> Preparando datos de rutas. Tarda 10-20 minutos, no cierres la sesion."
  if [ -n "$EXTRACTO" ]; then ./scripts/osrm-prepare.sh "$EXTRACTO"
  else                        ./scripts/osrm-prepare.sh
  fi
fi

# El nombre real de los ficheros generados manda sobre lo que diga la plantilla
OSM_BASE=$(ls osrm-data/*.osrm.* 2>/dev/null | head -1 | xargs -r basename \
           | sed 's/\.osrm\..*$//')
[ -n "$OSM_BASE" ] || fallo "no se han generado los datos de rutas. Revisa la salida anterior."
sed -i "s|^OSM_BASE=.*|OSM_BASE=$OSM_BASE|" .env
echo ">> OSM_BASE=$OSM_BASE"

# ---------------------------------------------------------------- arranque
echo ">> Construyendo y levantando contenedores"
if [ -n "${TOKEN:-}" ]; then
  docker compose --profile tunnel up -d --build
else
  docker compose up -d --build
fi

# Si la base ya existia de una version anterior, anade las columnas nuevas
if [ -x scripts/migrar.sh ]; then
  ./scripts/migrar.sh >/dev/null 2>&1 || true
fi

echo ">> Esperando a que responda la aplicacion"
for _ in $(seq 1 30); do
  if [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/login || true)" = "200" ]; then
    LISTA=si; break
  fi
  sleep 2
done

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo
echo "==================================================="
if [ "${LISTA:-no}" = "si" ]; then
  echo " LISTO"
else
  echo " ATENCION: la web no responde todavia."
  echo " Revisa:  docker compose logs --tail=40 app"
fi
echo "---------------------------------------------------"
echo " Direccion LAN:  http://${IP:-IP_DE_ESTA_MAQUINA}:8080"
echo " Usuario:        $ADMMAIL"
echo " Password:       $ADMPASS"
echo "---------------------------------------------------"
echo " Apunta ahi tu tunel de Cloudflare. La ubicacion del"
echo " movil solo funciona por HTTPS, o sea via tunel."
echo " Configuracion: $(pwd)/.env"
echo " Manual:        OPERACIONES.md"
echo "==================================================="
