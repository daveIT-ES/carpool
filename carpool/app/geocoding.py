"""Búsqueda de direcciones y geocodificación inversa.

Se consultan varios proveedores en orden hasta que uno responda: Photon
(komoot), que está pensado para búsqueda mientras se escribe, y Nominatim
(OpenStreetMap) como reserva. Si todos fallan se devuelve el error para que
la interfaz pueda distinguir "no hay resultados" de "no hay conexión".

Los resultados se cachean en memoria para no repetir consultas.
"""

from dataclasses import dataclass, asdict
from typing import Optional

import httpx

from .config import get_settings

settings = get_settings()

UA = "carpool-selfhosted/1.0 (+https://github.com/daveIT-ES/carpool)"
MAX_CACHE = 500
_cache: dict[str, list] = {}
_cache_inv: dict[str, str] = {}


@dataclass
class Sugerencia:
    nombre: str
    lat: float
    lon: float

    def dict(self) -> dict:
        return asdict(self)


def _recorta(texto: str) -> str:
    return " ".join(str(texto).split())[:120]


def _proveedores() -> list[str]:
    """Orden de consulta. El configurado primero, el otro como reserva."""
    preferido = settings.geo_provider.strip().lower()
    orden = [preferido] if preferido in ("photon", "nominatim") else ["photon"]
    for p in ("photon", "nominatim"):
        if p not in orden:
            orden.append(p)
    return orden


def _nombre_photon(props: dict) -> str:
    calle = " ".join(
        str(p) for p in (props.get("street"), props.get("housenumber")) if p
    )
    cabeza = props.get("name") or calle
    trozos = [
        cabeza,
        props.get("city") or props.get("county") or props.get("district"),
        props.get("state"),
    ]
    limpio: list[str] = []
    for t in trozos:
        if t and (not limpio or limpio[-1] != t):
            limpio.append(str(t))
    return _recorta(", ".join(limpio)) or _recorta(props.get("country") or "?")


async def _pide(cliente: httpx.AsyncClient, url: str, params: dict):
    r = await cliente.get(url, params=params)
    r.raise_for_status()
    return r.json()


async def _buscar_photon(cli, texto, lat, lon, limite):
    params = {"q": texto, "limit": limite, "lang": "es"}
    if lat is not None and lon is not None:
        params |= {"lat": lat, "lon": lon}
    data = await _pide(cli, f"{settings.photon_url.rstrip('/')}/api", params)
    salida = []
    for f in data.get("features", []):
        c = (f.get("geometry") or {}).get("coordinates") or []
        if len(c) == 2:
            salida.append(
                Sugerencia(_nombre_photon(f.get("properties") or {}), float(c[1]), float(c[0]))
            )
    return salida


async def _buscar_nominatim(cli, texto, lat, lon, limite):
    params = {
        "q": texto,
        "format": "jsonv2",
        "limit": limite,
        "addressdetails": 0,
    }
    if settings.geo_paises:
        params["countrycodes"] = settings.geo_paises
    data = await _pide(cli, f"{settings.nominatim_url.rstrip('/')}/search", params)
    return [
        Sugerencia(_recorta(i.get("display_name", "")), float(i["lat"]), float(i["lon"]))
        for i in data
        if i.get("lat") and i.get("lon")
    ]


async def buscar(
    texto: str,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    limite: int = 8,
) -> tuple[list[Sugerencia], Optional[str]]:
    """Devuelve (sugerencias, error). Error solo si ningún proveedor respondió."""
    texto = " ".join(texto.split())
    if len(texto) < 3:
        return [], None

    clave = f"{texto.lower()}|{lat}|{lon}"
    if clave in _cache:
        return [Sugerencia(**s) for s in _cache[clave]], None

    ultimo_error: Optional[str] = None
    async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": UA}) as cli:
        for prov in _proveedores():
            try:
                if prov == "photon":
                    res = await _buscar_photon(cli, texto, lat, lon, limite)
                else:
                    res = await _buscar_nominatim(cli, texto, lat, lon, limite)
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                ultimo_error = f"{prov}: {type(exc).__name__}"
                continue
            if res:
                if len(_cache) > MAX_CACHE:
                    _cache.clear()
                _cache[clave] = [s.dict() for s in res]
                return res, None
            # respondió pero sin resultados: probamos el siguiente proveedor
            ultimo_error = None

    if ultimo_error:
        return [], (
            "El servicio de direcciones no responde. Puedes marcar el punto "
            "tocando el mapa."
        )
    return [], None


async def inverso(lat: float, lon: float) -> str:
    """Nombre legible de unas coordenadas. Si falla, devuelve las coordenadas."""
    clave = f"{lat:.5f},{lon:.5f}"
    if clave in _cache_inv:
        return _cache_inv[clave]

    respaldo = f"{lat:.4f}, {lon:.4f}"
    nombre = respaldo

    async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": UA}) as cli:
        for prov in _proveedores():
            try:
                if prov == "photon":
                    data = await _pide(
                        cli,
                        f"{settings.photon_url.rstrip('/')}/reverse",
                        {"lat": lat, "lon": lon, "lang": "es"},
                    )
                    feats = data.get("features") or []
                    if feats:
                        nombre = _nombre_photon(feats[0].get("properties") or {}) or respaldo
                else:
                    data = await _pide(
                        cli,
                        f"{settings.nominatim_url.rstrip('/')}/reverse",
                        {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 17},
                    )
                    nombre = _recorta(data.get("display_name") or "") or respaldo
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                continue
            if nombre != respaldo:
                break

    if len(_cache_inv) > MAX_CACHE:
        _cache_inv.clear()
    _cache_inv[clave] = nombre
    return nombre


async def estado() -> dict:
    """Comprueba qué proveedores están accesibles. Para diagnóstico."""
    salida = {}
    async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": UA}) as cli:
        for prov in ("photon", "nominatim"):
            try:
                if prov == "photon":
                    d = await _pide(
                        cli, f"{settings.photon_url.rstrip('/')}/api",
                        {"q": "Tarragona", "limit": 1, "lang": "es"},
                    )
                    n = len(d.get("features") or [])
                else:
                    d = await _pide(
                        cli, f"{settings.nominatim_url.rstrip('/')}/search",
                        {"q": "Tarragona", "format": "jsonv2", "limit": 1},
                    )
                    n = len(d)
                salida[prov] = f"ok ({n} resultado/s)"
            except Exception as exc:  # noqa: BLE001 - es un diagnóstico
                salida[prov] = f"ERROR: {type(exc).__name__}: {exc}"
    salida["orden_configurado"] = " > ".join(_proveedores())
    return salida
