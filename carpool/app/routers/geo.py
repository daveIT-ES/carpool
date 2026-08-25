"""API de búsqueda de direcciones para el mapa."""

from fastapi import APIRouter, Depends, Query

from ..deps import require_admin, require_user
from ..geocoding import buscar, estado, inverso
from ..models import User
from ..security import rate_limited

router = APIRouter(prefix="/api/geo")


@router.get("/buscar")
async def api_buscar(
    q: str = Query(..., min_length=3, max_length=120),
    lat: float | None = None,
    lon: float | None = None,
    user: User = Depends(require_user),
):
    if rate_limited(f"geo:{user.id}", limit=150, window=300):
        return {"resultados": [], "error": "Demasiadas búsquedas seguidas. Espera un momento."}
    res, error = await buscar(q, lat, lon)
    return {"resultados": [s.dict() for s in res], "error": error}


@router.get("/inverso")
async def api_inverso(lat: float, lon: float, user: User = Depends(require_user)):
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return {"nombre": ""}
    if rate_limited(f"geo:{user.id}", limit=150, window=300):
        return {"nombre": f"{lat:.4f}, {lon:.4f}"}
    return {"nombre": await inverso(lat, lon)}


@router.get("/estado")
async def api_estado(admin: User = Depends(require_admin)):
    """Diagnóstico: comprueba si los proveedores de direcciones responden."""
    return await estado()
