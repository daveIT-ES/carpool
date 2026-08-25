# Manual de operación

Todos los comandos se ejecutan desde la carpeta del proyecto:

```bash
cd ~/carpool          # o ~/carpool/carpool si el repo quedó anidado
```

---

## Arrancar, parar, reiniciar

| Qué quieres | Comando |
|---|---|
| Arrancar todo | `docker compose up -d` |
| Parar todo (los datos se conservan) | `docker compose down` |
| Reiniciar solo la web | `docker compose restart app` |
| Reiniciar todo | `docker compose restart` |
| Ver qué está corriendo | `docker compose ps` |

Los contenedores tienen `restart: unless-stopped`, así que vuelven solos tras un reinicio de la máquina. No hace falta ponerlos en el arranque.

## Ver qué está pasando

```bash
docker compose logs -f app          # la web, en vivo
docker compose logs --tail=50 app   # las últimas 50 líneas
docker compose logs db              # base de datos
docker compose logs osrm            # servicio de rutas
```

Comprobar que la web responde:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/login
```

Debe devolver `200`. Un `000` significa que el contenedor no está escuchando.

---

## Contraseñas

### Olvidé la contraseña de un usuario (o la mía de administrador)

```bash
./scripts/reset-password.sh correo@ejemplo.com
```

Te pide la nueva contraseña dos veces y la cambia. Sin argumentos, lista los usuarios existentes.

Si el usuario está desactivado, este comando también lo reactiva.

### Cambiar la contraseña de un usuario normal desde la web

Entra como administrador → **Usuarios** → escribe la nueva contraseña en la fila del usuario → *Cambiar*.

### Por qué no sirve editar `ADMIN_PASSWORD` en `.env`

Esa variable **solo se usa la primera vez que arranca la aplicación**, cuando la base de datos está vacía. Después, la contraseña vive cifrada en PostgreSQL y cambiar el `.env` no tiene ningún efecto. Usa el script.

### Cambiar la contraseña de PostgreSQL

Requiere borrar la base de datos, así que **solo hazlo si aún no tienes datos que te importen**:

```bash
docker compose down
docker volume rm carpool_db-data
nano .env      # cambia POSTGRES_PASSWORD y la misma clave dentro de DATABASE_URL
docker compose up -d
```

Si ya hay datos, hazlo sin perderlos:

```bash
docker compose exec db psql -U carpool -c "ALTER USER carpool WITH PASSWORD 'nueva';"
nano .env      # pon 'nueva' en POSTGRES_PASSWORD y en DATABASE_URL
docker compose up -d
```

### Rotar la clave de sesiones

```bash
sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$(openssl rand -hex 32)/" .env
docker compose restart app
```

Cierra la sesión de todos los usuarios. Útil si sospechas que la clave se ha filtrado.

---

## Usuarios

### Dar de alta a alguien

Administrador → **Usuarios** → *Generar código*. Le pasas el código y se registra en `/registro`. Cada código sirve una sola vez.

### Bloquear a alguien

Administrador → **Usuarios** → *Desactivar*. No podrá entrar, pero su historial y su deuda se conservan.

### Convertir a alguien en administrador

```bash
docker compose exec app python -c "
from sqlmodel import Session, select
from app.database import engine
from app.models import User, Role
with Session(engine) as s:
    u = s.exec(select(User).where(User.email=='correo@ejemplo.com')).first()
    u.role = Role.ADMIN; s.add(u); s.commit(); print('hecho:', u.alias)
"
```

---

## Deudas y cobros

- **Marcar un viaje como pagado**: Administrador → **Viajes** → ajusta el importe si hace falta → *Cobrado*.
- **Anular un viaje**: *Cancelar*. Deja de contar como deuda.
- **Ver quién debe**: Administrador → **Resumen**.
- **Exportar todo a Excel**: Administrador → *Exportar CSV*.

Un usuario con deuda viva no puede registrar viajes nuevos. Es intencionado.

---

## Cambiar los parámetros de coste

Administrador → **Parámetros**:

| Campo | Qué es |
|---|---|
| Precio del combustible | €/litro. Actualízalo cuando cambie |
| Límite de pago aplazado | Por encima de este importe se paga por adelantado |
| Reparto a partir de | Km de ida desde los que el coste se divide entre pasajeros |
| Consumo | L/100 km reales de tu coche |
| Desgaste | €/km. Entre 0,05 y 0,12 en un turismo |

Cambiar estos valores **no recalcula los viajes ya registrados**: cada viaje guarda una copia de los parámetros con los que se calculó.

---

## Copias de seguridad

### Manual

```bash
mkdir -p backups
docker compose exec -T db pg_dump -U carpool carpool | gzip > backups/carpool-$(date +%F).sql.gz
```

### Automática (diaria, conserva 30 días)

```bash
sudo tee /etc/cron.daily/carpool-dump >/dev/null <<'EOF'
#!/bin/sh
cd /home/USUARIO/carpool || exit 1
mkdir -p backups
docker compose exec -T db pg_dump -U carpool carpool | gzip > backups/carpool-$(date +\%F).sql.gz
find backups -name '*.sql.gz' -mtime +30 -delete
EOF
sudo chmod +x /etc/cron.daily/carpool-dump
```

Cambia `USUARIO` por el tuyo.

### Restaurar

```bash
docker compose down
docker volume rm carpool_db-data
docker compose up -d db
sleep 10
gunzip -c backups/carpool-2026-08-25.sql.gz | docker compose exec -T db psql -U carpool carpool
docker compose up -d
```

Guarda también el `.env` en un gestor de contraseñas: no está en Git y sin `SECRET_KEY` la restauración no queda limpia.

---

## Actualizar a la última versión

```bash
git pull
docker compose up -d --build
```

Haz una copia antes si el cambio toca la base de datos.

---

## Datos de rutas (OSRM)

### Cambiar de zona geográfica

```bash
./scripts/osrm-prepare.sh https://download.geofabrik.de/europe/spain-latest.osm.pbf
nano .env      # ajusta OSM_BASE al nombre que imprima el script
docker compose up -d
```

España entera necesita bastante más RAM y disco que una comunidad autónoma.

### Actualizar el mapa

Los datos de OpenStreetMap envejecen. Una vez al año basta:

```bash
rm osrm-data/*
./scripts/osrm-prepare.sh
docker compose restart osrm
```

---

## Problemas frecuentes

### El contenedor `app` se reinicia en bucle

Casi siempre es la contraseña de PostgreSQL descuadrada:

```bash
docker compose logs app | tail -20
grep -E 'POSTGRES_PASSWORD|DATABASE_URL' .env
```

La clave de `POSTGRES_PASSWORD` y la que va embebida en `DATABASE_URL` deben ser idénticas. Evita `@`, `:` y `/`, que rompen el formato de la URL.

### «No hay ruta por carretera entre esos puntos»

O los puntos están fuera de la zona cargada en OSRM, o el servicio no arrancó:

```bash
docker compose logs osrm | tail -20
ls osrm-data/*.osrm*
grep OSM_BASE .env
```

El valor de `OSM_BASE` debe coincidir con el nombre de los ficheros `.osrm.*`.

### El botón de ubicación no funciona en el móvil

La geolocalización del navegador **solo funciona por HTTPS**. A través del túnel de Cloudflare funciona; entrando por `http://IP:8080` nunca lo hará. No es un fallo de la aplicación.

### Se ha llenado el disco

```bash
df -h /
docker system df
docker image prune -a      # borra imágenes sin usar
```

Los ficheros intermedios del preproceso de OSRM ocupan varios GB y se pueden borrar tras generar los `.osrm.*`.

### Empezar completamente de cero

```bash
docker compose down -v      # el -v borra también la base de datos
docker compose up -d --build
```

Se pierden todos los usuarios y viajes, y se vuelve a crear el administrador del `.env`.

---

## Publicación con Cloudflare

### Si ya tienes un túnel en otra máquina

El *public hostname* apunta a:

```
http://IP_DE_ESTA_MAQUINA:8080
```

Deja vacío el campo *HTTP Host Header*. Ten en cuenta que el 8080 queda accesible desde toda tu red local; si quieres restringirlo a la IP del túnel:

```bash
sudo ufw allow 22
sudo ufw allow from IP_DEL_TUNEL to any port 8080
sudo ufw enable
```

### Si prefieres el túnel dentro de este compose

Pon el token en `TUNNEL_TOKEN` dentro de `.env`, apunta el hostname a `http://app:8000` y arranca con:

```bash
docker compose --profile tunnel up -d
```

Para que no se exponga nada en la red local, cambia además la línea de `ports` en `docker-compose.yml` a `- "127.0.0.1:8080:8000"`.

### Generar el QR del coche

```bash
qrencode -s 8 -o qr-carpool.png "https://tudominio.com/registro?codigo=ABC12345"
```

Un QR por persona, porque el código de invitación es de un solo uso.
