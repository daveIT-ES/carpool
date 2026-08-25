"""Búsqueda de direcciones y geocodificación inversa.

Usa Photon (komoot) por defecto, que está pensado para búsqueda mientras se
escribe. Nominatim es la alternativa, pero su política de uso prohíbe el
autocompletado, así que con ese proveedor la búsqueda solo se lanza al pulsar
Enter. Los resultados se cachean en memoria para no repetir consultas.
"""

from dataclasses import dataclass, asdict
from typing import Optional

import httpx

from .config import get_settings

settings = get_settings()

UA = "carpool-selfhosted/1.0 (https://github.com/daveIT-ES/carpool)"
_cache: dict[str, list] = {}
_cache_inv: dict[str, str] = {}
MAX_CACHE = 500


@dataclass
class Sugerencia:
    nombre: str
    lat: float
    lon: float

    def dict(self) -> dict:
        return asdict(self)


def _recorta(texto: str) -> str:
    return " ".join(texto.split())[:120]


def _nombre_photon(props: dict) -> str:
    partes = [
        props.get("name"),
        props.get("street"),
        props.get("housenumber"),
    ]
    calle = " ".join(p for p in partes[1:] if p)
    cabeza = props.get("name") or calle
    cola = props.get("city") or props.get("county") or props.get("district")
    provincia = props.get("state")
    trozos = [t for t in (cabeza, cola, provincia) if t]
    # quita duplicados consecutivos
    limpio = []
    for t in trozos:
        if not limpio or limpio[-1] != t:
            limpio.append(t)
    return _recorta(", ".join(limpio)) or _recorta(props.get("country", "?"))


async def buscar(texto: str, lat: Optional[float] = None,
                 lon: Optional[float] = None, limite: int = 6) -> list[Sugerencia]:
    texto = texto.strip()
    if len(texto) < 3:
        return []

    clave = f"{texto.lower()}|{lat}|{lon}"
    if clave in _cache:
        return [Sugerencia(**s) for s in _cache[clave]]

    if settings.geo_provider == "nominatim":
        url = f"{settings.nominatim_url.rstrip('/')}/search"
        params = {
            "q": texto,
            "format": "jsonv2",
            "limit": limite,
            "addressdetails": 0,
            "countrycodes": settings.geo_paises,
        }
    else:
        url = f"{settings.photon_url.rstrip('/')}/api"
        params = {"q": texto, "limit": limite, "lang": "es"}
        if lat is not None and lon is not None:
            params |= {"lat": lat, "lon": lon}

    try:
        async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": UA}) as cli:
            r = await cli.get(url, params=params)
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, ValueError):
        return []

    salida: list[Sugerencia] = []
    if settings.geo_provider == "nominatim":
        for item in data:
            salida.append(
                Sugerencia(
                    nombre=_recorta(item.get("display_name", "")),
                    lat=float(item["lat"]),
                    lon=float(item["lon"]),
                )
            )
    else:
        for f in data.get("features", []):
            coords = f.get("geometry", {}).get("coordinates") or []
            if len(coords) != 2:
                continue
            salida.append(
                Sugerencia(
                    nombre=_nombre_photon(f.get("properties", {})),
                    lat=float(coords[1]),
                    lon=float(coords[0]),
                )
            )

    if len(_cache) > MAX_CACHE:
        _cache.clear()
    _cache[clave] = [s.dict() for s in salida]
    return salida


async def inverso(lat: float, lon: float) -> str:
    """Nombre legible de unas coordenadas. Si falla, devuelve las coordenadas."""
    clave = f"{lat:.5f},{lon:.5f}"
    if clave in _cache_inv:
        return _cache_inv[clave]

    if settings.geo_provider == "nominatim":
        url = f"{settings.nominatim_url.rstrip('/')}/reverse"
        params = {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 17}
    else:
        url = f"{settings.photon_url.rstrip('/')}/reverse"
        params = {"lat": lat, "lon": lon, "lang": "es"}

    nombre = f"{lat:.4f}, {lon:.4f}"
    try:
        async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": UA}) as cli:
            r = await cli.get(url, params=params)
            r.raise_for_status()
            data = r.json()
        if settings.geo_provider == "nominatim":
            nombre = _recorta(data.get("display_name", nombre)) or nombre
        else:
            feats = data.get("features") or []
            if feats:
                nombre = _nombre_photon(feats[0].get("properties", {})) or nombre
    except (httpx.HTTPError, ValueError, KeyError):
        pass

    if len(_cache_inv) > MAX_CACHE:
        _cache_inv.clear()
    _cache_inv[clave] = nombre
    return nombre
