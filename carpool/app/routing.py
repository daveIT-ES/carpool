"""Cliente del servicio de routing OSRM (autoalojado)."""

from dataclasses import dataclass
from decimal import Decimal

import httpx

from .config import get_settings

settings = get_settings()

MAX_PARADAS = 4                 # paradas intermedias, sin contar origen ni destino
MAX_KM_RUTA = Decimal("2000")   # tope de cordura para una sola ruta


class RoutingError(RuntimeError):
    pass


@dataclass(frozen=True)
class Punto:
    nombre: str
    lat: float
    lon: float

    def como_dict(self) -> dict:
        return {"nombre": self.nombre, "lat": self.lat, "lon": self.lon}


def valida_coordenada(lat: float, lon: float) -> bool:
    return -90 <= lat <= 90 and -180 <= lon <= 180


async def ruta(puntos: list[Punto]) -> tuple[Decimal, int, list]:
    """Kilómetros, minutos y trazado real del recorrido por carretera.

    El trazado se devuelve como lista de pares [lat, lon] para dibujarlo en el
    mapa. Se pide simplificado para no mover megas por cada consulta.
    """
    if len(puntos) < 2:
        raise RoutingError("Hace falta al menos un origen y un destino.")
    if len(puntos) > MAX_PARADAS + 2:
        raise RoutingError(f"Como mucho {MAX_PARADAS} paradas intermedias.")
    for p in puntos:
        if not valida_coordenada(p.lat, p.lon):
            raise RoutingError("Alguna coordenada está fuera de rango.")

    coords = ";".join(f"{p.lon},{p.lat}" for p in puntos)
    url = f"{settings.osrm_url.rstrip('/')}/route/v1/{settings.osrm_profile}/{coords}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                url,
                params={"overview": "simplified", "geometries": "geojson"},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise RoutingError("No se ha podido contactar con el servicio de rutas.") from exc

    if data.get("code") != "Ok" or not data.get("routes"):
        raise RoutingError(
            "No hay ruta por carretera que enlace esos puntos. "
            "Comprueba que estén dentro de la zona cargada en el mapa."
        )

    r = data["routes"][0]
    km = Decimal(str(r["distance"])) / Decimal(1000)
    if km > MAX_KM_RUTA:
        raise RoutingError("El recorrido es demasiado largo para esta aplicación.")

    # OSRM devuelve [lon, lat]; Leaflet espera [lat, lon]
    coords = (r.get("geometry") or {}).get("coordinates") or []
    trazado = [[c[1], c[0]] for c in coords if isinstance(c, (list, tuple)) and len(c) == 2]

    return km, int(round(r["duration"] / 60)), trazado
