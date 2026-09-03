"""El administrador registra viajes a nombre de los usuarios finales."""
import json, os, pathlib, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.chdir(pathlib.Path(__file__).resolve().parents[1])

DB = pathlib.Path("data/anombre.db"); DB.parent.mkdir(exist_ok=True); DB.unlink(missing_ok=True)
os.environ.update(DATABASE_URL=f"sqlite:///./{DB}", OSRM_URL="http://127.0.0.1:5994",
                  COOKIE_SECURE="false", SECRET_KEY="t", ADMIN_EMAIL="admin@x.l",
                  ADMIN_PASSWORD="admin12345", ADMIN_ALIAS="admin",
                  TELEGRAM_TOKEN="", TELEGRAM_CHAT_ID="")

class M(BaseHTTPRequestHandler):
    def do_GET(self):
        b = json.dumps({"code":"Ok","routes":[{"distance":15000,"duration":900,
             "geometry":{"coordinates":[[1.2,41.1],[1.1,41.2]]}}]}).encode()
        self.send_response(200); self.send_header("Content-Length",str(len(b)))
        self.send_header("Content-Type","application/json"); self.end_headers(); self.wfile.write(b)
    def log_message(self,*a): pass
srv = HTTPServer(("127.0.0.1",5994), M)
threading.Thread(target=srv.serve_forever, daemon=True).start()

from fastapi.testclient import TestClient
from app.database import init_db
from app.main import app
from sqlmodel import Session, select
from app.database import engine
from app.models import Trip, User
init_db()

fallos=[]
def ok(n,c,e=""):
    print(f"{'OK  ' if c else 'FALLO'} {n} {e}")
    if not c: fallos.append(n)
def csrf(h):
    m='name="csrf" value="'; i=h.index(m)+len(m); return h[i:h.index('"',i)]

RUTA = json.dumps([{"nombre":"Valls","lat":41.10,"lon":1.20},
                   {"nombre":"Reus","lat":41.15,"lon":1.10}])

# --- admin y dos usuarios
a = TestClient(app, base_url="http://testserver")
a.post("/login", data={"identificador":"admin@x.l","password":"admin12345",
                       "csrf":csrf(a.get("/login").text)})
ids = {}
for alias in ("marta","pep"):
    a.post("/admin/invitaciones", data={"csrf":csrf(a.get("/admin/usuarios").text)})
    cod = a.get("/admin/usuarios").text.split('class="code">')[1].split("<")[0]
    u = TestClient(app, base_url="http://testserver")
    u.post("/registro", data={"alias":alias,"email":f"{alias}@x.l","password":"passw0rd1",
           "codigo":cod,"csrf":csrf(u.get("/registro").text)})
    with Session(engine) as s:
        ids[alias] = s.exec(select(User).where(User.alias==alias)).first().id
ok("dos usuarios creados", len(ids)==2)

# --- el formulario muestra el selector solo al admin
f = a.get("/viajes/nuevo").text
ok("el admin ve el selector", 'name="a_nombre_de"' in f)
ok("el selector lista a marta", ">marta<" in f)
u = TestClient(app, base_url="http://testserver")
u.post("/login", data={"identificador":"marta","password":"passw0rd1",
                       "csrf":csrf(u.get("/login").text)})
ok("el usuario normal NO ve el selector", 'name="a_nombre_de"' not in u.get("/viajes/nuevo").text)

# --- el admin registra a nombre de marta
r = a.post("/viajes", data={"puntos_json":RUTA,"pasajeros":"1","ida_vuelta":"false",
    "fecha_viaje":"2026-08-25","hora_salida":"09:00","a_nombre_de":str(ids["marta"]),
    "csrf":csrf(a.get("/viajes/nuevo").text)}, follow_redirects=False)
ok("viaje creado", r.status_code==303)
with Session(engine) as s:
    t = s.get(Trip, 1)
    ok("el viaje es de marta", t.user_id==ids["marta"], f"user_id={t.user_id}")
    ok("queda registrado quien lo dio de alta", t.registrado_por_id==1)
ok("marta ve el viaje en su panel", "Valls" in u.get("/").text)
ok("marta tiene deuda", "pendientes" in u.get("/").text)
ok("el detalle indica quien lo registro", "Registrado por admin" in u.get("/viajes/1").text)

# --- marta queda bloqueada, el admin no
r = u.get("/viajes/nuevo", follow_redirects=False)
ok("marta bloqueada por deuda", r.status_code==303)
r = a.get("/viajes/nuevo", follow_redirects=False)
ok("el admin NO se bloquea", r.status_code==200)

# --- el admin puede registrar otro aunque marta deba, y se le avisa
r = a.post("/viajes", data={"puntos_json":RUTA,"pasajeros":"1","ida_vuelta":"false",
    "fecha_viaje":"2026-08-26","a_nombre_de":str(ids["marta"]),
    "csrf":csrf(a.get("/viajes/nuevo").text)}, follow_redirects=True)
ok("segundo viaje pese a la deuda", "ya tenía" in r.text)

# --- un usuario normal NO puede colar un viaje a otro
r = u.post("/viajes", data={"puntos_json":RUTA,"pasajeros":"1","ida_vuelta":"false",
    "fecha_viaje":"2026-08-27","a_nombre_de":str(ids["pep"]),
    "csrf":csrf(u.get("/").text)}, follow_redirects=False)
with Session(engine) as s:
    de_pep = s.exec(select(Trip).where(Trip.user_id==ids["pep"])).all()
ok("el usuario normal no puede cargar viajes a otro", len(de_pep)==0)

# --- usuario inexistente o desactivado
r = a.post("/viajes", data={"puntos_json":RUTA,"pasajeros":"1","ida_vuelta":"false",
    "fecha_viaje":"2026-08-27","a_nombre_de":"9999",
    "csrf":csrf(a.get("/viajes/nuevo").text)}, follow_redirects=True)
ok("rechaza un usuario inexistente", "no existe" in r.text)
a.post(f"/admin/usuarios/{ids['pep']}/estado", data={"csrf":csrf(a.get("/admin/usuarios").text)})
r = a.post("/viajes", data={"puntos_json":RUTA,"pasajeros":"1","ida_vuelta":"false",
    "fecha_viaje":"2026-08-27","a_nombre_de":str(ids["pep"]),
    "csrf":csrf(a.get("/viajes/nuevo").text)}, follow_redirects=True)
ok("rechaza un usuario desactivado", "desactivado" in r.text)

# --- si no elige a nadie, el viaje es del propio admin
r = a.post("/viajes", data={"puntos_json":RUTA,"pasajeros":"1","ida_vuelta":"false",
    "fecha_viaje":"2026-08-28","a_nombre_de":"",
    "csrf":csrf(a.get("/viajes/nuevo").text)}, follow_redirects=False)
with Session(engine) as s:
    ult = s.exec(select(Trip).order_by(Trip.id.desc())).first()
ok("sin seleccion, el viaje es del admin", ult.user_id==1, f"user_id={ult.user_id}")

# --- CSV y acceso desde el panel
ok("el CSV lleva quien lo registro", "registrado_por" in a.get("/admin/export.csv").text)
ok("hay acceso desde el panel de viajes",
   "Registrar viaje a nombre de un usuario" in a.get("/admin/viajes").text)

srv.shutdown()
print(); print("FALLOS:", fallos if fallos else "ninguno")
sys.exit(1 if fallos else 0)
