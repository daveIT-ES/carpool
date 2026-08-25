"""Dependencias compartidas: sesión de usuario, plantillas y mensajes flash."""

from decimal import Decimal
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from .config import get_settings
from .database import get_session
from .models import DEUDA_STATES, Role, Trip, User
from .security import ensure_csrf

settings = get_settings()
templates = Jinja2Templates(directory="app/templates")


def euros(value) -> str:
    if value is None:
        return "—"
    return f"{Decimal(value):,.2f} €".replace(",", "\u2009")


def km(value) -> str:
    if value is None:
        return "—"
    return f"{Decimal(value):,.1f} km".replace(",", "\u2009")


templates.env.filters["euros"] = euros
templates.env.filters["km"] = km

ESTADO_LABEL = {
    "PENDIENTE_PREPAGO": "Prepago pendiente",
    "PENDIENTE_PAGO": "Pendiente de pago",
    "PAGADO": "Pagado",
    "CANCELADO": "Cancelado",
}
templates.env.globals["ESTADO_LABEL"] = ESTADO_LABEL


def flash(request: Request, mensaje: str, nivel: str = "info") -> None:
    request.session.setdefault("_flash", []).append({"m": mensaje, "n": nivel})


def pop_flashes(request: Request) -> list[dict]:
    return request.session.pop("_flash", [])


def current_user(
    request: Request, session: Session = Depends(get_session)
) -> Optional[User]:
    uid = request.session.get("uid")
    if not uid:
        return None
    user = session.get(User, uid)
    if user is None or not user.is_active:
        request.session.clear()
        return None
    return user


def require_user(user: Optional[User] = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"},
        )
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Necesitas permisos de administrador.")
    return user


def deuda_de(session: Session, user_id: int) -> Decimal:
    viajes = session.exec(
        select(Trip).where(Trip.user_id == user_id, Trip.estado.in_(DEUDA_STATES))
    ).all()
    return sum((t.coste_usuario for t in viajes), Decimal("0.00"))


def render(request: Request, plantilla: str, status_code: int = 200, **ctx):
    base = {
        "request": request,
        "app_name": settings.app_name,
        "app_subtitle": settings.app_subtitle,
        "csrf_token": ensure_csrf(request.session),
        "flashes": pop_flashes(request),
    }
    base.update(ctx)
    return templates.TemplateResponse(
        request=request, name=plantilla, context=base, status_code=status_code
    )


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)
