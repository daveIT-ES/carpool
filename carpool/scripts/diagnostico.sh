#!/usr/bin/env bash
# Comprueba que los servicios externos e internos responden.
set -uo pipefail
cd "$(dirname "$0")/.."

echo "=== Contenedores ==="
docker compose ps

echo
echo "=== Web local ==="
printf "  /login -> "
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/login

echo
echo "=== Routing (OSRM) ==="
docker compose exec -T app python -c "
import httpx, os
u = os.environ.get('OSRM_URL','http://osrm:5000')
try:
    r = httpx.get(f'{u}/route/v1/driving/1.2445,41.1189;1.1069,41.1561',
                  params={'overview':'false'}, timeout=10)
    d = r.json()
    print('  ok:', d.get('code'), round(d['routes'][0]['distance']/1000,1), 'km')
except Exception as e:
    print('  ERROR:', type(e).__name__, e)
"

echo
echo "=== Salida a internet desde el contenedor ==="
docker compose exec -T app python -c "
import httpx
for nombre, url in (('photon','https://photon.komoot.io/api?q=Tarragona&limit=1'),
                    ('nominatim','https://nominatim.openstreetmap.org/search?q=Tarragona&format=jsonv2&limit=1')):
    try:
        r = httpx.get(url, timeout=10, headers={'User-Agent':'carpool-diagnostico/1.0'})
        print(f'  {nombre}: HTTP {r.status_code}, {len(r.text)} bytes')
    except Exception as e:
        print(f'  {nombre}: ERROR {type(e).__name__}: {e}')
"

echo
echo "=== DNS ==="
docker compose exec -T app python -c "
import socket
for h in ('photon.komoot.io','nominatim.openstreetmap.org'):
    try: print(f'  {h} -> {socket.gethostbyname(h)}')
    except Exception as e: print(f'  {h} -> ERROR {e}')
"
