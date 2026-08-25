# Instalación rápida

## Lo que necesitas antes

- Una máquina Linux con **Docker** y el plugin **docker compose**. Una VM con
  Ubuntu Server o Debian sobre Proxmox va perfecta.
- **8 GB de RAM** durante la instalación (el preproceso del mapa es lo que más
  come). Después basta con 4 GB.
- **20 GB de disco** libres.
- Un **túnel de Cloudflare** si quieres acceder desde fuera de casa. Sirve el
  que ya tengas para otros servicios.

Si Docker no está instalado:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

Cierra la sesión y vuelve a entrar para que el grupo surta efecto.

---

## Instalación

Un comando:

```bash
git clone https://github.com/daveIT-ES/carpool.git && bash carpool/carpool/scripts/install.sh
```

El script te preguntará dos cosas:

1. **Correo del administrador.** Será tu usuario para entrar.
2. **Token del túnel de Cloudflare.** Déjalo vacío si ya tienes un túnel en
   otra máquina, que es lo habitual.

Y luego, solo:

- Genera las contraseñas (sesiones, base de datos, administrador).
- Descarga y procesa el mapa de Cataluña. **Esto tarda 10-20 minutos.**
- Construye y arranca los contenedores.
- Comprueba que la web responde.

Al terminar imprime la dirección, el usuario y la contraseña. **Apunta la
contraseña**, aunque también queda en el fichero `.env`.

### Otra zona geográfica

Pasa la URL de cualquier extracto de [Geofabrik](https://download.geofabrik.de):

```bash
bash carpool/carpool/scripts/install.sh https://download.geofabrik.de/europe/spain-latest.osm.pbf
```

España entera necesita bastante más RAM y disco que una comunidad autónoma.

---

## Publicar en internet

La aplicación escucha en el **puerto 8080** de la máquina.

**Si ya tienes un túnel de Cloudflare** (lo normal), añade un *public hostname*
apuntando a:

```
http://IP_DE_LA_MAQUINA:8080
```

Deja vacío el campo *HTTP Host Header*.

**Si no tienes túnel**, pega su token cuando el instalador lo pida y apunta el
hostname a `http://app:8000`.

> La ubicación del móvil **solo funciona por HTTPS**. A través del túnel va
> bien; entrando por `http://IP:8080` el navegador la bloquea. No es un fallo
> de la aplicación.

---

## Primeros pasos en la aplicación

Entra con el usuario y la contraseña que imprimió el instalador.

**1. Parámetros** — ajusta lo que determina el precio:

| Campo | Qué poner |
|---|---|
| Precio del combustible | €/litro actual |
| Consumo | L/100 km reales de tu coche |
| Desgaste | €/km. Entre 0,05 y 0,12 en un turismo |
| Límite de pago aplazado | Por encima de ese importe se paga por adelantado (10 € por defecto) |
| Reparto a partir de | Km de ida desde los que el coste se divide entre pasajeros (40 por defecto) |
| Recargo nocturno | % extra en la franja de noche. A 0 % desactivado |

**2. Usuarios** — pulsa *Generar código*. Cada código sirve para un registro.
Pásalo con el enlace:

```
https://tudominio.com/registro?codigo=ABC12345
```

**3. El QR del coche** — uno por persona, porque el código es de un solo uso:

```bash
qrencode -s 8 -o qr.png "https://tudominio.com/registro?codigo=ABC12345"
```

**4. Lugares** (opcional) — puntos habituales que aparecerán como atajos bajo
el mapa. No hace falta: el usuario puede buscar cualquier dirección.

---

## Comprobar que todo va bien

```bash
cd ~/carpool/carpool
./scripts/diagnostico.sh
```

Revisa contenedores, la web, el servicio de rutas, el DNS y la salida a
internet del buscador de direcciones.

---

## Si algo falla

**El script se corta durante el preproceso del mapa, sin mensaje claro.**
Es falta de memoria. Sube la RAM de la máquina a 8 GB y vuelve a ejecutarlo:
detecta lo ya hecho y no repite trabajo.

**«tu usuario no puede usar docker».**

```bash
sudo usermod -aG docker $USER
```

Cierra la sesión y vuelve a entrar.

**La web no responde.**

```bash
docker compose logs --tail=40 app
```

Casi siempre es la contraseña de PostgreSQL descuadrada entre
`POSTGRES_PASSWORD` y la que va dentro de `DATABASE_URL`.

**El buscador de direcciones no encuentra nada.** Ejecuta el diagnóstico: si
la salida a internet falla, la aplicación sigue siendo usable tocando el mapa.

---

El script se puede volver a ejecutar cuando quieras. Si ya hay un `.env`, lo
respeta; si el mapa ya está procesado, no lo repite.

Para el día a día (contraseñas, copias, reinicios), ver
[OPERACIONES.md](OPERACIONES.md).
