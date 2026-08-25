"""Verificacion del flujo completo tal como lo describe el usuario."""
import json, os, pathlib, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import unquote
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.chdir(pathlib.Path(__file__).resolve().parents[1])

DB = pathlib.Path("data/verifica.db"); DB.parent.mkdir(exist_ok=True); DB.unlink(missing_ok=True)
os.environ.update(DATABASE_URL=f"sqlite:///./{DB}", OSRM_URL="http://127.0.0.1:5998",
                  COOKIE_SECURE="false", SECRET_KEY="t", ADMIN_EMAIL="admin@x.local",
                  ADMIN_PASSWORD="admin12345", ADMIN_ALIAS="admin")

class M(BaseHTTPRequestHandler):
    def do_GET(self):
        c = unquote(self.path.split("?")[0]).rsplit("/",1)[-1]
        t = max(1, len(c.split(";"))-1)
        b = json.dumps({"code":"Ok","routes":[{"distance":12000*t,"duration":600*t}]}).encode()
        self.send_response(200); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self,*a): pass
srv = HTTPServer(("127.0.0.1",5998), M)
threading.Thread(target=srv.serve_forever, daemon=True).start()

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

# --- 1. El admin genera un codigo de invitacion
a = TestClient(app, base_url="http://testserver")
a.post("/login", data={"identificador":"admin@x.local","password":"admin12345",
                       "csrf":csrf(a.get("/login").text)})
h = a.get("/admin/usuarios").text
a.post("/admin/invitaciones", data={"csrf":csrf(h)})
codigo = a.get("/admin/usuarios").text.split('class="code">')[1].split("<")[0]
ok("1. El admin genera codigo de invitacion", len(codigo)==8, f"-> {codigo}")

# --- 2. Un usuario nuevo se registra con ese codigo
u = TestClient(app, base_url="http://testserver")
reg = u.get(f"/registro?codigo={codigo}").text
ok("2a. El codigo llega precargado en el formulario", f'value="{codigo}"' in reg)
r = u.post("/registro", data={"alias":"kastrol","email":"k@x.local","password":"passw0rd1",
           "codigo":codigo,"csrf":csrf(reg)}, follow_redirects=False)
ok("2b. Se registra y entra directo", r.status_code==303 and r.headers["location"]=="/")

# --- 3. Sin codigo no se puede registrar
u2 = TestClient(app, base_url="http://testserver")
r = u2.post("/registro", data={"alias":"intruso","email":"i@x.local","password":"passw0rd1",
            "codigo":"XXXXXXXX","csrf":csrf(u2.get("/registro").text)})
ok("3. Sin codigo valido no hay alta", "no es válido" in r.text)

# --- 4. La pantalla de nuevo viaje trae mapa y buscador, SIN lista de puntos
p = u.get("/viajes/nuevo").text
ok("4a. Carga Leaflet (mapa)", "leaflet@1.9.4/dist/leaflet.js" in p and "leaflet.css" in p)
ok("4b. Contenedor del mapa", 'id="mapa"' in p)
ok("4c. Boton de ubicacion actual", 'class="ghost small gps"' in p)
ok("4d. Buscador en origen y destino", p.count('class="q"') >= 2)
ok("4e. Bloque de origen y destino", 'data-rol="origen"' in p and 'data-rol="destino"' in p)
ok("4f. Se pueden anadir paradas", 'id="add-parada"' in p)
ok("4g. NO hay desplegable de puntos predefinidos", '<select' not in p)
ok("4h. No exige lugares dados de alta",
   "no hay puntos de destino configurados" not in p)
ok("4i. Confirmar empieza bloqueado", 'id="confirmar" disabled' in p)

# --- 5. La API de busqueda existe y pide sesion
anon = TestClient(app, base_url="http://testserver")
r = anon.get("/api/geo/buscar?q=tarragona", follow_redirects=False)
ok("5a. Buscar direcciones requiere sesion", r.status_code==303)
r = anon.get("/api/geo/inverso?lat=41&lon=1", follow_redirects=False)
ok("5b. Geocodificacion inversa requiere sesion", r.status_code==303)

# --- 6. Presupuesto con coordenadas libres del mapa (sin ningun Place en la BD)
def pts(*c): return json.dumps([{"nombre":n,"lat":la,"lon":lo} for n,la,lo in c])
ruta = pts(("Mi ubicacion actual",41.10,1.20),("Carrer Major 3, Reus",41.15,1.10))
r = u.post("/viajes/calcular", data={"puntos_json":ruta,"pasajeros":"1"})
ok("6a. Calcula con coordenadas libres", "Mi ubicacion actual" in r.text)
ok("6b. Pregunta la vuelta despues", "¿Necesitas la vuelta?" in r.text)
ok("6c. No confirmable hasta responder", "data-final" not in r.text)
r = u.post("/viajes/calcular", data={"puntos_json":ruta,"pasajeros":"1","ida_vuelta":"false"})
ok("6d. Tras elegir 'solo ida' ya es confirmable", "data-final" in r.text)

# --- 7. Alta real del viaje
t = csrf(u.get("/viajes/nuevo").text)
r = u.post("/viajes", data={"puntos_json":ruta,"pasajeros":"1","ida_vuelta":"false",
           "fecha_viaje":"2026-08-25","csrf":t}, follow_redirects=False)
ok("7a. Viaje guardado", r.status_code==303, f"-> {r.headers.get('location')}")
d = u.get(r.headers["location"]).text
ok("7b. El detalle muestra el recorrido", "Carrer Major 3, Reus" in d)
ok("7c. Queda pendiente de pago", "Pendiente de pago" in d)

# --- 8. Bloqueo por deuda y aislamiento
r = u.get("/viajes/nuevo", follow_redirects=False)
ok("8a. Con deuda no puede pedir otro viaje", r.headers["location"]=="/")
r = u.get("/admin", follow_redirects=False)
ok("8b. Usuario normal no entra en admin", r.status_code==403)
adm = a.get("/admin/viajes").text
ok("8c. El admin ve el viaje del usuario", "kastrol" in adm and "Reus" in adm)

# --- 9. El admin cobra y se desbloquea
a.post("/admin/viajes/1/pagar", data={"importe":"","metodo":"bizum","csrf":csrf(adm)})
ok("9a. Cobro registrado", "Pagado" in a.get("/admin/viajes").text)
ok("9b. El usuario vuelve a estar al dia", "al día" in u.get("/").text)
r = u.get("/viajes/nuevo", follow_redirects=False)
ok("9c. Y puede pedir viaje otra vez", r.status_code==200)

srv.shutdown()
print()
print("FALLOS:" , fallos if fallos else "ninguno")
sys.exit(1 if fallos else 0)
