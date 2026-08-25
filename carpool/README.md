# Carpool — reparto de gastos del coche

Aplicación web autoalojada para repartir el coste real de los trayectos entre
quienes suben al coche. Cada pasajero se registra, elige el trayecto, ve el
importe antes de confirmarlo y consulta su historial. El conductor tiene un
panel de administración con todos los viajes, la deuda viva y los cobros.

Pensada para funcionar detrás de un túnel de Cloudflare y para entrar
escaneando un QR pegado en el coche.

---

## Flujo de alta de un viaje

1. **Desde dónde sales.** Por defecto se usa la ubicación del dispositivo
   (`navigator.geolocation`). Si el GPS cae a menos de 400 m de un punto ya
   dado de alta, se etiqueta con el nombre de ese punto; si no, queda como
   «Mi ubicación (lat, lon)». Siempre se puede elegir un punto de la lista.
2. **Paradas por el camino.** Hasta cuatro, en el orden que se indiquen.
3. **A dónde vas.** Destino, fecha, número de pasajeros que comparten gasto.
4. **¿Solo ida o ida y vuelta?** Se pregunta *después* de calcular el
   recorrido, con el precio de la ida ya a la vista. El viaje no se puede
   confirmar hasta responder.

La vuelta se calcula **directa del destino al punto de salida**, sin repetir
las paradas: es lo que ocurre en la práctica cuando ya has dejado a la gente.

## Cómo calcula el precio

```
coste_km    = precio_litro / 100 × consumo_L100 + desgaste_€_km
km_ida      = salida → parada 1 → … → destino
km_vuelta   = destino → salida   (0 si es solo ida)
coste_total = (km_ida + km_vuelta) × coste_km
```

La distancia por carretera la calcula un OSRM propio, sin depender de
servicios externos. Cada tramo con paradas se resuelve en una sola consulta.

**Reparto.** Si la distancia de **ida** supera el umbral (40 km por defecto), el
coste se divide entre los pasajeros que comparten el viaje. Por debajo de ese
umbral cada pasajero paga el trayecto completo. La vuelta suma al importe pero
no cuenta para decidir el reparto: un viaje de 30 km de ida y 30 de vuelta no
reparte.

**Prepago.** Si el importe que le toca pagar al usuario supera el umbral
(10 € por defecto), el viaje queda en `PENDIENTE_PREPAGO` y no se considera
confirmado hasta que el conductor registra el cobro. Justo en el umbral no se
exige prepago: 10,00 € se paga después, 10,01 € por adelantado.

**Bloqueo por deuda.** Mientras un usuario tenga cualquier viaje pendiente de
pago o de prepago, no puede registrar uno nuevo.

Cada viaje guarda una copia de los parámetros con los que se calculó, así que
cambiar el precio del combustible no altera el histórico.

## Estados de un viaje

| Estado | Significado |
|---|---|
| `PENDIENTE_PREPAGO` | Supera el umbral. No confirmado hasta cobrar. |
| `PENDIENTE_PAGO` | Se viaja y se paga después. Cuenta como deuda. |
| `PAGADO` | Cobrado y registrado en `payments`. |
| `CANCELADO` | Anulado por el administrador. Deja de contar como deuda. |

---

## Puesta en marcha

Requisitos: Docker y Docker Compose en el host (por ejemplo, una VM Debian
sobre Proxmox). Reserva unos 4 GB de RAM y 15 GB de disco si vas a procesar el
extracto de Cataluña con OSRM.

### 1. Configuración

```bash
git clone <tu-repo> carpool && cd carpool
cp .env.example .env
sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$(openssl rand -hex 32)/" .env
$EDITOR .env          # contraseñas de admin y de base de datos
```

### 2. Datos de routing (OSRM)

```bash
./scripts/osrm-prepare.sh
# o con otro extracto de Geofabrik:
# ./scripts/osrm-prepare.sh https://download.geofabrik.de/europe/spain-latest.osm.pbf
```

El preproceso tarda entre 10 y 20 minutos con Cataluña y consume bastante RAM
durante `osrm-extract`. Al terminar te dice qué valor poner en `OSM_BASE`.

### 3. Arranque

```bash
docker compose up -d --build
docker compose logs -f app
```

La app queda escuchando en el **puerto 8080** de la máquina. PostgreSQL y OSRM
no publican nada: viven en la red interna de Docker.

### 4. Publicación con Cloudflare

> Operación del día a día (contraseñas, copias, reinicios, problemas
> frecuentes): ver **[OPERACIONES.md](OPERACIONES.md)**.

Si ya tienes un túnel de Cloudflare en otra máquina (lo habitual), añade un
*public hostname* apuntando a `http://IP_DE_ESTA_MAQUINA:8080` y listo.

Si no tienes túnel, puedes levantarlo desde este mismo compose: pon
`TUNNEL_TOKEN` en `.env`, apunta el hostname a `http://app:8000` y arranca con:

```bash
docker compose --profile tunnel up -d
```

En ese caso, para no exponer nada en la red local, cambia la línea de `ports`
de `docker-compose.yml` a `- "127.0.0.1:8080:8000"`.

### 5. Primeros pasos en la app

1. Entra con el usuario administrador del `.env`.
2. **Parámetros**: ajusta precio del litro, consumo y desgaste del coche.
3. **Lugares**: añade al menos dos puntos de origen/destino con sus coordenadas.
4. **Usuarios**: genera códigos de invitación y repártelos.
5. Genera el QR apuntando a la pantalla de registro con el código incluido:
   `https://tu-dominio/registro?codigo=XXXXXXXX`

> **La ubicación del dispositivo solo funciona sobre HTTPS.** El túnel de
> Cloudflare ya lo da. Si pruebas en la LAN contra `http://ip:8080`, el
> navegador bloqueará la geolocalización y habrá que elegir el punto de salida
> de la lista; con `http://localhost` sí funciona.

---

## Seguridad

- **Registro por invitación.** El QR es público: sin códigos de un solo uso,
  cualquiera que pase por la calle puede darse de alta.
- Contraseñas con Argon2, sesiones en cookie firmada `HttpOnly` + `SameSite=Lax`,
  token CSRF en todos los formularios y limitación de intentos de login.
- Cambia `SECRET_KEY` y las contraseñas por defecto antes de publicar nada.
  Rotar `SECRET_KEY` invalida todas las sesiones abiertas.
- `.env` está en `.gitignore`. Si algún secreto llega a entrar en el historial
  de Git, no basta con borrarlo: hay que reescribir el historial y rotarlo.
- Considera poner Cloudflare Access o Turnstile delante si el enlace se va a
  ver en un sitio muy visible.

## Datos personales

La aplicación guarda alias, correo e historial de trayectos con origen, destino
y fecha. Eso es un perfil de movimientos, así que conviene tratarlo con cuidado:

- Usa alias, no nombres completos.
- Da de alta puntos genéricos (estación, polígono, plaza), nunca domicilios
  exactos.
- La ubicación del móvil se guarda con cuatro decimales (~11 m) como punto de
  salida del viaje. Es el dato más sensible de la aplicación: quien tenga
  acceso al panel de administración ve desde dónde sale cada persona y cuándo.
- Exporta y purga periódicamente. `RETENCION_MESES` está previsto para ello.
- No compartas el CSV fuera del círculo que usa el coche.

## Encaje legal

Esto es una herramienta para repartir gastos reales entre conocidos. Mientras
los importes no superen el coste del trayecto, es el uso normal del coche
compartido. Si el cobro pasara a generar beneficio, la actividad podría
interpretarse como transporte de viajeros sin licencia, con consecuencias en la
cobertura del seguro. Mantén la fórmula pegada al coste. No es asesoramiento
jurídico.

---

## Desarrollo

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="sqlite:///./data/carpool.db" OSRM_URL="http://localhost:5000" COOKIE_SECURE=false
uvicorn app.main:app --reload
```

Pruebas de humo (levantan un OSRM simulado, no necesitan Docker):

```bash
python tests/smoke.py
```

Cubren el cálculo del coste en los bordes (40 km justos, 10,00 € justos), que
las paradas entren en la ruta y la vuelta sea un solo tramo, el etiquetado del
GPS, que no se pueda confirmar sin responder a la pregunta de la vuelta, el
alta por invitación, el bloqueo por deuda, el circuito de cobro y el
aislamiento entre usuarios.

### Estructura

```
app/
  main.py        arranque, middleware, manejo de errores
  config.py      variables de entorno
  models.py      tablas
  database.py    motor, parámetros, datos iniciales
  security.py    Argon2, CSRF, rate limit, invitaciones
  costing.py     fórmula de coste, reparto y prepago
  routing.py     cliente OSRM
  deps.py        sesión de usuario, plantillas, avisos
  routers/       auth, trips, admin
  templates/     Jinja2
  static/app.css hoja de estilos
```

El esquema se crea con `SQLModel.metadata.create_all` en el arranque. Para un
proyecto de este tamaño es suficiente; si más adelante cambias columnas con
datos ya en producción, añade Alembic.

## Licencia

MIT. Ver `LICENSE`.

## Atribución

Si reutilizas este proyecto, agradezco un enlace al repositorio original.
No es una obligación legal, solo cortesía.

## Nota sobre dependencias

El repositorio no incluye binarios de terceros. Se descargan en el momento
del despliegue:

| Qué | De dónde | Cuándo |
|---|---|---|
| Paquetes Python (`requirements.txt`, versiones fijadas) | PyPI | `docker compose build` |
| Imágenes `postgres:16-alpine`, `osrm-backend`, `cloudflared` | Docker Hub / GHCR | `docker compose up` |
| Extracto de OpenStreetMap | Geofabrik | `scripts/osrm-prepare.sh` |
| Tipografías Archivo e IBM Plex Mono | Google Fonts (CDN) | al abrir la web |

Por tanto el primer despliegue necesita salida a internet. Las tipografías se
piden desde el navegador del usuario, no desde el servidor; si quieres que la
aplicación funcione sin CDN, descárgalas a `app/static/` y ajusta el `<link>`
de `app/templates/base.html`.
