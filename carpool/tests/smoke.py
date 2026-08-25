"""Pruebas de humo. Ejecutar desde la raíz del repo:  python tests/smoke.py"""

import json
import os
import pathlib
import sys
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import unquote

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

DB = pathlib.Path("data/test-smoke.db")
DB.parent.mkdir(exist_ok=True)
DB.unlink(missing_ok=True)

os.environ.update(
    DATABASE_URL=f"sqlite:///./{DB}",
    OSRM_URL="http://127.0.0.1:5999",
    COOKIE_SECURE="false",
    SECRET_KEY="test-secret",
    ADMIN_EMAIL="admin@test.local",
    ADMIN_PASSWORD="admin12345",
    ADMIN_ALIAS="admin",
)

# OSRM simulado: 10 km por cada tramo entre dos puntos consecutivos.
KM_POR_TRAMO = {"valor": 10.0}
ULTIMA_RUTA = {"coords": ""}


class MockOSRM(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        ruta = unquote(self.path.split("?")[0])
        coords = ruta.rsplit("/", 1)[-1]
        ULTIMA_RUTA["coords"] = coords
        tramos = max(1, len(coords.split(";")) - 1)
        cuerpo = json.dumps(
            {
                "code": "Ok",
                "routes": [
                    {
                        "distance": KM_POR_TRAMO["valor"] * 1000 * tramos,
                        "duration": 600 * tramos,
                        "geometry": {"coordinates": [[1.0, 41.0], [1.4, 41.3]]},
                    }
                ],
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *a):
        pass


servidor = HTTPServer(("127.0.0.1", 5999), MockOSRM)
threading.Thread(target=servidor.serve_forever, daemon=True).start()

from fastapi.testclient import TestClient  # noqa: E402

from app.costing import calcular  # noqa: E402
from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import TripStatus  # noqa: E402

init_db()

fallos = []


def check(nombre, condicion, extra=""):
    print(f"{'PASS' if condicion else 'FAIL'}  {nombre} {extra}")
    if not condicion:
        fallos.append(nombre)


# ------------------------------------------------------------ coste puro
P = dict(
    precio_litro=Decimal("1.55"),
    consumo_l100=Decimal("6.5"),
    desgaste_eur_km=Decimal("0.08"),
    umbral_reparto_km=Decimal("40"),
    umbral_prepago=Decimal("10"),
)

c = calcular(km_ida=Decimal("40"), pasajeros=3, **P)
check("40 km justos no reparten", c.reparto_aplicado is False)

c = calcular(km_ida=Decimal("40.5"), pasajeros=3, **P)
check("40,5 km sí reparten", c.reparto_aplicado is True)

c = calcular(km_ida=Decimal("55"), km_vuelta=Decimal("50"), pasajeros=2, **P)
check("la vuelta suma al total", c.km_total == Decimal("105.00"))
check("la vuelta no decide el reparto", c.reparto_aplicado is True)

c = calcular(km_ida=Decimal("30"), km_vuelta=Decimal("30"), pasajeros=3, **P)
check("ida corta no reparte aunque el total sea largo", c.reparto_aplicado is False)

# --- recargo nocturno
from app.costing import es_nocturno  # noqa: E402
check("23:30 es nocturno en 22-06", es_nocturno("23:30", "22:00", "06:00") is True)
check("03:00 es nocturno en 22-06", es_nocturno("03:00", "22:00", "06:00") is True)
check("06:00 ya no es nocturno", es_nocturno("06:00", "22:00", "06:00") is False)
check("14:00 no es nocturno", es_nocturno("14:00", "22:00", "06:00") is False)
check("sin hora no hay recargo", es_nocturno(None, "22:00", "06:00") is False)
check("hora invalida no rompe", es_nocturno("no-es-hora", "22:00", "06:00") is False)

c = calcular(km_ida=Decimal("20"), pasajeros=1, hora_salida="23:30",
             recargo_noche_pct=Decimal("30"), **P)
base_dia = calcular(km_ida=Decimal("20"), pasajeros=1, **P)
check("de noche se cobra mas", c.coste_total > base_dia.coste_total,
      f"{base_dia.coste_total} -> {c.coste_total}")
check("el recargo es el 30% del recorrido",
      c.recargo_importe == (c.coste_recorrido * Decimal("30") / 100).quantize(Decimal("0.01")))
c = calcular(km_ida=Decimal("20"), pasajeros=1, hora_salida="23:30",
             recargo_noche_pct=Decimal("0"), **P)
check("con recargo a 0 no se aplica nada", c.nocturno is False and c.recargo_importe == 0)
c = calcular(km_ida=Decimal("60"), pasajeros=2, hora_salida="23:30",
             recargo_noche_pct=Decimal("50"), **P)
check("el recargo se reparte entre pasajeros",
      c.coste_usuario == (c.coste_total / 2).quantize(Decimal("0.01")))

P10 = dict(P, desgaste_eur_km=Decimal("0"), consumo_l100=Decimal("10"), precio_litro=Decimal("2"))
c = calcular(km_ida=Decimal("50"), pasajeros=1, **P10)
check("10,00 € NO exige prepago", c.estado == TripStatus.PENDIENTE_PAGO, f"→ {c.coste_usuario}")
c = calcular(km_ida=Decimal("50.1"), pasajeros=1, **P10)
check("10,02 € SÍ exige prepago", c.estado == TripStatus.PENDIENTE_PREPAGO, f"→ {c.coste_usuario}")

# ------------------------------------------------------------------ web
cli = TestClient(app, base_url="http://testserver")

r = cli.get("/", follow_redirects=False)
check("sin sesión redirige a login", r.status_code == 303 and r.headers["location"] == "/login")


def csrf(html):
    marca = 'name="csrf" value="'
    i = html.index(marca) + len(marca)
    return html[i : html.index('"', i)]


html = cli.get("/login").text
r = cli.post(
    "/login",
    data={"identificador": "admin@test.local", "password": "admin12345", "csrf": csrf(html)},
    follow_redirects=False,
)
check("login del admin", r.status_code == 303 and r.headers["location"] == "/")

# lugares: 1 Estación, 2 Polígono, 3 Hospital
html = cli.get("/admin/lugares").text
t = csrf(html)
cli.post("/admin/lugares", data={"nombre": "Estación", "lat": 41.10, "lon": 1.20, "csrf": t})
cli.post("/admin/lugares", data={"nombre": "Polígono", "lat": 41.30, "lon": 1.40, "csrf": t})
cli.post("/admin/lugares", data={"nombre": "Hospital", "lat": 41.20, "lon": 1.30, "csrf": t})
check("tres lugares creados", cli.get("/admin/lugares").text.count("<tr>") >= 4)

html = cli.get("/admin/usuarios").text
cli.post("/admin/invitaciones", data={"csrf": csrf(html)})
codigo = cli.get("/admin/usuarios").text.split('class="code">')[1].split("<")[0]

u = TestClient(app, base_url="http://testserver")
html = u.get("/registro").text
r = u.post(
    "/registro",
    data={"alias": "marta", "email": "marta@test.local", "password": "passw0rd123",
          "codigo": codigo, "csrf": csrf(html)},
    follow_redirects=False,
)
check("alta con invitación válida", r.status_code == 303)

u2 = TestClient(app, base_url="http://testserver")
html = u2.get("/registro").text
r = u2.post(
    "/registro",
    data={"alias": "pep", "email": "pep@test.local", "password": "passw0rd123",
          "codigo": codigo, "csrf": csrf(html)},
)
check("código de un solo uso", "no es válido o ya se ha usado" in r.text)

# --- presupuesto: origen por GPS, dos paradas, destino ---
html = u.get("/viajes/nuevo").text
t = csrf(html)
import json as _json

def pts(*coords):
    return _json.dumps([{"nombre": n, "lat": la, "lon": lo} for n, la, lo in coords])

RUTA_2 = pts(("Casa", 41.0, 1.0), ("Trabajo", 41.3, 1.4))
RUTA_4 = pts(("Casa", 41.0, 1.0), ("Estacion", 41.1, 1.2),
             ("Hospital", 41.2, 1.3), ("Trabajo", 41.3, 1.4))
base = {"puntos_json": RUTA_4, "pasajeros": "2"}

r = u.post("/viajes/calcular", data=base)
check("las paradas entran en la ruta", ULTIMA_RUTA["coords"].count(";") == 3,
      f"→ {ULTIMA_RUTA['coords']}")
check("presupuesto sin decidir aún la vuelta", "¿Necesitas la vuelta?" in r.text)
check("no se puede confirmar sin decidir", "data-final" not in r.text)
check("30 km de ida con 2 paradas", "30,0 km" in r.text or "30.0 km" in r.text)
check("usa los nombres enviados por el mapa", "Casa" in r.text and "Trabajo" in r.text)

# validación de datos que llegan del navegador
r = u.post("/viajes/calcular", data={"puntos_json": "no-es-json", "pasajeros": "1"})
check("rechaza JSON inválido", "Vuelve a intentarlo" in r.text)
r = u.post("/viajes/calcular", data={"puntos_json": pts(("X", 999, 1)), "pasajeros": "1"})
check("rechaza un solo punto", "origen y un destino" in r.text)
r = u.post("/viajes/calcular",
           data={"puntos_json": pts(("X", 999, 1), ("Y", 41.0, 1.0)), "pasajeros": "1"})
check("rechaza coordenadas fuera de rango", "fuera de rango" in r.text)
r = u.post("/viajes/calcular",
           data={"puntos_json": pts(("A", 41.0, 1.0), ("B", 41.00001, 1.00001)), "pasajeros": "1"})
check("rechaza origen y destino iguales", "el mismo sitio" in r.text)
r = u.post("/viajes/calcular", data={"puntos_json": pts(
    ("a", 41.0, 1.0), ("b", 41.1, 1.1), ("c", 41.2, 1.2),
    ("d", 41.3, 1.3), ("e", 41.4, 1.4), ("f", 41.5, 1.5), ("g", 41.6, 1.6)),
    "pasajeros": "1"})
check("limita el numero de paradas", "paradas intermedias" in r.text)

# --- decidir solo ida ---
r = u.post("/viajes/calcular", data=dict(base, ida_vuelta="false"))
check("solo ida ya es confirmable", "data-final" in r.text)
check("solo ida no suma vuelta", "Vuelta directa" not in r.text)

# --- decidir ida y vuelta ---
r = u.post("/viajes/calcular", data=dict(base, ida_vuelta="true"))
check("ida y vuelta añade el tramo de regreso", "Vuelta directa" in r.text)
check("vuelta directa = un solo tramo", ULTIMA_RUTA["coords"].count(";") == 1,
      f"→ {ULTIMA_RUTA['coords']}")
check("total 40 km (30 ida + 10 vuelta)", "40,0 km" in r.text or "40.0 km" in r.text)

# --- alta del viaje ---
r = u.post(
    "/viajes",
    data=dict(base, ida_vuelta="true", fecha_viaje="2026-08-23", csrf=t),
    follow_redirects=False,
)
check("viaje con paradas registrado", r.status_code == 303 and r.headers["location"] == "/viajes/1")
detalle = u.get("/viajes/1").text
check("el detalle lista las paradas",
      "parada 1</small>" in detalle and "parada 2</small>" in detalle)
check("el detalle marca la vuelta", "vuelta directa" in detalle)

# no se puede crear sin responder a la pregunta de la vuelta
u3 = TestClient(app, base_url="http://testserver")
u3.post("/login", data={"identificador": "admin", "password": "admin12345",
                        "csrf": csrf(u3.get("/login").text)})
html = u3.get("/viajes/nuevo").text
r = u3.post("/viajes", data=dict(base, fecha_viaje="2026-08-23", csrf=csrf(html)),
            follow_redirects=False)
check("sin decidir la vuelta no se guarda", r.headers["location"] == "/viajes/nuevo")

# --- bloqueo, cobro, CSV ---
r = u.get("/viajes/nuevo", follow_redirects=False)
check("bloqueo con deuda viva", r.status_code == 303 and r.headers["location"] == "/")

html = cli.get("/admin/viajes").text
check("el admin ve el recorrido completo", "Casa" in html and "Hospital" in html)
cli.post("/admin/viajes/1/pagar", data={"importe": "", "metodo": "bizum", "csrf": csrf(html)})
check("viaje marcado como pagado", "Pagado" in cli.get("/admin/viajes").text)
check("panel del usuario al día", "al día" in u.get("/").text)

# --- prepago con recorrido largo ---
KM_POR_TRAMO["valor"] = 60.0
html = u.get("/viajes/nuevo").text
r = u.post(
    "/viajes",
    data=dict(base, pasajeros="1", ida_vuelta="true",
              fecha_viaje="2026-08-24", csrf=csrf(html)),
    follow_redirects=False,
)
check("viaje caro exige prepago", "Prepago pendiente" in u.get(r.headers["location"]).text)

r = u.get("/admin", follow_redirects=False)
check("usuario normal sin acceso a admin", r.status_code == 403)
r = cli.get("/admin/export.csv")
check("CSV con columnas de paradas", "paradas" in r.text and "km_vuelta" in r.text)

# la API de geocodificación exige sesión
anon = TestClient(app, base_url="http://testserver")
r = anon.get("/api/geo/buscar?q=tarragona", follow_redirects=False)
check("la busqueda de direcciones requiere sesion", r.status_code == 303)
r = u.get("/api/geo/inverso?lat=999&lon=999")
check("geocodificacion inversa valida rango", r.json()["nombre"] == "")
r = u.get("/api/geo/buscar?q=tarragona")
d = r.json()
check("la busqueda informa del fallo en vez de decir 'sin resultados'",
      "resultados" in d and "error" in d)
r = u.get("/api/geo/estado", follow_redirects=False)
check("el diagnostico es solo para admin", r.status_code == 403)
r = cli.get("/api/geo/estado")
check("el admin ve el estado de los proveedores", "orden_configurado" in r.json())

servidor.shutdown()
print()
if fallos:
    print(f"{len(fallos)} prueba(s) fallidas: {', '.join(fallos)}")
    sys.exit(1)
print("Todas las pruebas han pasado.")
