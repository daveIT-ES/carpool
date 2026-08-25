"""Avisos por Telegram.

Se envían en segundo plano y nunca bloquean la operación: si Telegram no
responde, el viaje se guarda igual y solo queda el aviso en el log.
"""

import logging
from decimal import Decimal
from html import escape

import httpx

from .config import get_settings

log = logging.getLogger("carpool.notify")
settings = get_settings()

API = "https://api.telegram.org"


def configurado() -> bool:
    return bool(settings.telegram_token and settings.telegram_chat_id)


async def enviar(texto: str) -> tuple[bool, str]:
    """Manda un mensaje. Devuelve (ok, detalle) para poder diagnosticar."""
    if not configurado():
        return False, "Falta TELEGRAM_TOKEN o TELEGRAM_CHAT_ID en el .env"
    url = f"{API}/bot{settings.telegram_token}/sendMessage"
    datos = {
        "chat_id": settings.telegram_chat_id,
        "text": texto,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(url, json=datos)
        if r.status_code == 200:
            return True, "enviado"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _linea(etiqueta: str, valor) -> str:
    return f"{etiqueta}: <b>{escape(str(valor))}</b>"


async def aviso_viaje(datos: dict) -> None:
    """Aviso de viaje nuevo. Recibe datos planos, no objetos de la sesión."""
    if not configurado():
        return

    cabecera = (
        "🌙 <b>Viaje nocturno</b>" if datos.get("nocturno") else "🚗 <b>Viaje nuevo</b>"
    )
    partes = [
        cabecera,
        "",
        _linea("Quién", datos["alias"]),
        _linea("Ruta", datos["ruta"]),
        _linea("Cuándo", datos["cuando"]),
        _linea("Distancia", f"{Decimal(datos['km']):.1f} km"),
        _linea("Importe", f"{Decimal(datos['importe']):.2f} €"),
    ]
    if datos.get("pasajeros", 1) > 1:
        partes.append(_linea("Pasajeros", datos["pasajeros"]))
    if datos.get("recargo") and Decimal(datos["recargo"]) > 0:
        partes.append(_linea("Recargo nocturno", f"{Decimal(datos['recargo']):.2f} €"))

    partes.append("")
    if datos.get("prepago"):
        partes.append("⚠️ <b>Requiere prepago.</b> No confirmado hasta cobrarlo.")
    else:
        partes.append("Pago aplazado. Pendiente de cobro.")

    if datos.get("notas"):
        partes.append(f"\n<i>{escape(str(datos['notas']))}</i>")

    ok, detalle = await enviar("\n".join(partes))
    if not ok:
        log.warning("No se ha podido avisar por Telegram: %s", detalle)


async def aviso_prueba() -> tuple[bool, str]:
    return await enviar(
        "✅ <b>Carpool</b>\nLos avisos por Telegram funcionan correctamente."
    )
