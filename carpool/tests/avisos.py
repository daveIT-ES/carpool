"""Prueba de los avisos: se simula la API de Telegram y se comprueba que el
aviso se dispara al crear un viaje, y que un fallo NO rompe el alta."""
import json, os, pathlib, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.chdir(pathlib.Path(__file__).resolve().parents[1])
DB = pathlib.Path("data/tg.db"); DB.parent.mkdir(exist_ok=True); DB.unlink(missing_ok=True)
os.environ.update(DATABASE_URL=f"sqlite:///./{DB}", OSRM_URL="http://127.0.0.1:5996",
                  COOKIE_SECURE="false", SECRET_KEY="t", ADMIN_EMAIL="a@x.l",
                  ADMIN_PASSWORD="admin12345", ADMIN_ALIAS="admin",
                  TELEGRAM_TOKEN="123:FAKE", TELEGRAM_CHAT_ID="999")

RECIBIDOS = []
MODO = {"fallar": False}

class Falso(BaseHTTPRequestHandler):
    def do_GET(self):
        b = json.dumps({"code":"Ok","routes":[{"distance":23100,"duration":1320,
             "geometry":{"coordinates":[[1.2,41.1],[1.1,41.15]]}}]}).encode()
        self._r(200, b)
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        RECIBIDOS.append(json.loads(self.rfile.read(n)))
        if MODO["fallar"]:
            self._r(500, b'{"ok":false,"description":"simulado"}')
        else:
            self._r(200, b'{"ok":true}')
    def _r(self, c, b):
        self.send_response(c); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self,*a): pass

s1 = HTTPServer(("127.0.0.1",5996), Falso); threading.Thread(target=s1.serve_forever,daemon=True).start()
s2 = HTTPServer(("127.0.0.1",5995), Falso); threading.Thread(target=s2.serve_forever,daemon=True).start()

import app.notify as notify
notify.API = "http://127.0.0.1:5995"

from fastapi.testclient import TestClient
from app.database import init_db
from app.main import app
init_db()

fallos=[]
def ok(n,c,e=""):
    print(f"{'OK  ' if c else 'FALLO'} {n} {e}")
    if not c: fallos.append(n)

def csrf(h):
    m='name="csrf" value="'; i=h.index(m)+len(m); return h[i:h.index('"',i)]

c = TestClient(app, base_url="http://testserver")
c.post("/login", data={"identificador":"a@x.l","password":"admin12345","csrf":csrf(c.get("/login").text)})
ruta = json.dumps([{"nombre":"Valls","lat":41.10,"lon":1.20},
                   {"nombre":"Tarragona","lat":41.15,"lon":1.10}])

# --- viaje normal
r = c.post("/viajes", data={"puntos_json":ruta,"pasajeros":"1","ida_vuelta":"false",
    "fecha_viaje":"2026-08-25","hora_salida":"09:00","notas":"con maletas",
    "csrf":csrf(c.get("/viajes/nuevo").text)}, follow_redirects=False)
ok("el viaje se guarda", r.status_code==303)
ok("se ha enviado un aviso", len(RECIBIDOS)==1, f"-> {len(RECIBIDOS)}")
m = RECIBIDOS[-1]["text"] if RECIBIDOS else ""
ok("lleva el alias", "admin" in m)
ok("lleva la ruta", "Valls" in m and "Tarragona" in m)
ok("lleva el importe", "€" in m)
ok("lleva las notas", "con maletas" in m)
ok("dice pago aplazado", "Pago aplazado" in m)
ok("chat_id correcto", RECIBIDOS[-1]["chat_id"]=="999")

# cobrar para desbloquear
c.post("/admin/viajes/1/pagar", data={"importe":"","metodo":"bizum","csrf":csrf(c.get("/admin/viajes").text)})

# --- viaje nocturno y caro -> prepago
r = c.post("/admin/config", data={"precio_litro":"1.55","umbral_prepago":"1.00",
    "umbral_reparto_km":"40","recargo_noche_pct":"30","noche_desde":"22:00",
    "noche_hasta":"06:00","csrf":csrf(c.get("/admin/config").text)})
r = c.post("/viajes", data={"puntos_json":ruta,"pasajeros":"1","ida_vuelta":"false",
    "fecha_viaje":"2026-08-25","hora_salida":"23:30",
    "csrf":csrf(c.get("/viajes/nuevo").text)}, follow_redirects=False)
m = RECIBIDOS[-1]["text"]
ok("avisa de viaje nocturno", "nocturno" in m.lower())
ok("avisa del recargo", "Recargo nocturno" in m)
ok("avisa de que requiere prepago", "prepago" in m.lower())

# --- si Telegram falla, el viaje se guarda igual
c.post("/admin/viajes/2/pagar", data={"importe":"","metodo":"bizum","csrf":csrf(c.get("/admin/viajes").text)})
MODO["fallar"]=True
antes=len(RECIBIDOS)
r = c.post("/viajes", data={"puntos_json":ruta,"pasajeros":"1","ida_vuelta":"false",
    "fecha_viaje":"2026-08-26","hora_salida":"10:00",
    "csrf":csrf(c.get("/viajes/nuevo").text)}, follow_redirects=False)
ok("con Telegram caido el viaje SI se guarda", r.status_code==303)
ok("se intento el envio", len(RECIBIDOS)==antes+1)

# --- boton de prueba
MODO["fallar"]=False
r = c.post("/admin/probar-aviso", data={"csrf":csrf(c.get("/admin/config").text)})
ok("el boton de prueba envia", "funcionan correctamente" in RECIBIDOS[-1]["text"])
ok("la config muestra que esta activo", "Enviar aviso de prueba" in c.get("/admin/config").text)

s1.shutdown(); s2.shutdown()
print(); print("FALLOS:", fallos if fallos else "ninguno")
sys.exit(1 if fallos else 0)
