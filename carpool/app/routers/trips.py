"""Panel del usuario: deuda, historial y alta de viajes con paradas."""

import json
from datetime import date, datetime
from decimal import Decimal
from math import asin, cos, radians, sin, sqrt

from fastapi import APIRouter, Depends, Form, Request
from sqlmodel import Session, select

from ..costing import calcular
from ..config import get_settings
from ..database import get_decimal, get_session, get_setting
from ..deps import deuda_de, flash, redirect, render, require_user
from ..models import AuditLog, Payment, Place, Trip, TripStatus, User, Vehicle
from ..routing import MAX_PARADAS, Punto, RoutingError, ruta
from ..security import csrf_ok, rate_limited

router = APIRouter()

def _vehiculo(session: Session) -> Vehicle | None:
    veh = session.exec(
        select(Vehicle).where(Vehicle.activo, Vehicle.predeterminado)
    ).first()
    return veh or session.exec(select(Vehicle).where(Vehicle.activo)).first()


def _parametros(session: Session, vehiculo: Vehicle) -> dict:
    return {
        "precio_litro": get_decimal(session, "precio_litro"),
        "consumo_l100": vehiculo.consumo_l100,
        "desgaste_eur_km": vehiculo.desgaste_eur_km,
        "umbral_reparto_km": get_decimal(session, "umbral_reparto_km"),
        "umbral_prepago": get_decimal(session, "umbral_prepago"),
        "recargo_noche_pct": get_decimal(session, "recargo_noche_pct"),
        "noche_desde": get_setting(session, "noche_desde"),
        "noche_hasta": get_setting(session, "noche_hasta"),
    }


def _metros(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(a))


def _puntos_desde_json(crudo: str) -> list[Punto]:
    """Convierte el JSON que envía el mapa en una lista de puntos validada.

    Formato esperado: [{"nombre": "...", "lat": 41.1, "lon": 1.2}, ...]
    Los datos vienen del navegador, así que se valida todo.
    """
    try:
        datos = json.loads(crudo or "[]")
    except (ValueError, TypeError):
        raise RoutingError("No hemos recibido bien el recorrido. Vuelve a intentarlo.")

    if not isinstance(datos, list):
        raise RoutingError("No hemos recibido bien el recorrido.")
    if len(datos) < 2:
        raise RoutingError("Marca al menos un origen y un destino.")
    if len(datos) > MAX_PARADAS + 2:
        raise RoutingError(f"Como mucho {MAX_PARADAS} paradas intermedias.")

    puntos: list[Punto] = []
    for item in datos:
        if not isinstance(item, dict):
            raise RoutingError("No hemos recibido bien el recorrido.")
        try:
            lat, lon = float(item.get("lat")), float(item.get("lon"))
        except (TypeError, ValueError):
            raise RoutingError("Alguno de los puntos no tiene coordenadas válidas.")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise RoutingError("Alguna coordenada está fuera de rango.")
        nombre = " ".join(str(item.get("nombre") or "").split())[:120]
        if not nombre:
            nombre = f"{lat:.4f}, {lon:.4f}"
        puntos.append(Punto(nombre=nombre, lat=lat, lon=lon))

    # descarta puntos consecutivos que son el mismo sitio
    limpios = [puntos[0]]
    for p in puntos[1:]:
        anterior = limpios[-1]
        if _metros(anterior.lat, anterior.lon, p.lat, p.lon) > 50:
            limpios.append(p)
    if len(limpios) < 2:
        raise RoutingError("El origen y el destino son el mismo sitio.")
    return limpios


async def _presupuesto(
    session: Session,
    puntos: list[Punto],
    ida_vuelta: bool,
    pasajeros: int,
    hora_salida: str | None = None,
):
    vehiculo = _vehiculo(session)
    if vehiculo is None:
        raise RoutingError("No hay ningún vehículo configurado. Avisa al conductor.")

    km_ida, min_ida, trazado = await ruta(puntos)

    km_vuelta, min_vuelta = Decimal("0"), 0
    if ida_vuelta:
        # La vuelta va directa del destino al origen, sin repetir las paradas.
        km_vuelta, min_vuelta, trazado_vuelta = await ruta([puntos[-1], puntos[0]])
        trazado = trazado + trazado_vuelta

    coste = calcular(
        km_ida=km_ida,
        km_vuelta=km_vuelta,
        pasajeros=pasajeros,
        hora_salida=hora_salida,
        **_parametros(session, vehiculo),
    )
    return vehiculo, coste, min_ida + min_vuelta, trazado


@router.get("/")
def panel(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    viajes = session.exec(
        select(Trip).where(Trip.user_id == user.id).order_by(Trip.id.desc())
    ).all()
    deuda = deuda_de(session, user.id)
    pagado = sum(
        (t.coste_usuario for t in viajes if t.estado == TripStatus.PAGADO),
        Decimal("0.00"),
    )
    return render(
        request,
        "panel.html",
        user=user,
        viajes=viajes,
        deuda=deuda,
        pagado=pagado,
        n_viajes=len([t for t in viajes if t.estado != TripStatus.CANCELADO]),
    )


@router.get("/viajes/nuevo")
def nuevo_form(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    deuda = deuda_de(session, user.id)
    if deuda > 0:
        flash(
            request,
            f"Tienes {deuda:.2f} € pendientes. Liquida la deuda para poder registrar otro viaje.",
            "error",
        )
        return redirect("/")

    favoritos = session.exec(
        select(Place).where(Place.activo).order_by(Place.nombre)
    ).all()
    cfg = get_settings()
    return render(
        request,
        "nuevo_viaje.html",
        user=user,
        favoritos=favoritos,
        vehiculo=_vehiculo(session),
        hoy=date.today().isoformat(),
        hora_ahora=datetime.now().strftime("%H:%M"),
        max_paradas=MAX_PARADAS,
        mapa_lat=cfg.mapa_lat,
        mapa_lon=cfg.mapa_lon,
        mapa_zoom=cfg.mapa_zoom,
        umbral_reparto=get_decimal(session, "umbral_reparto_km"),
        umbral_prepago=get_decimal(session, "umbral_prepago"),
        recargo_noche=get_decimal(session, "recargo_noche_pct"),
        noche_desde=get_setting(session, "noche_desde"),
        noche_hasta=get_setting(session, "noche_hasta"),
    )


@router.post("/viajes/calcular")
async def calcular_precio(
    request: Request,
    puntos_json: str = Form("[]"),
    ida_vuelta: str = Form(""),
    pasajeros: int = Form(1),
    hora_salida: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Fragmento con el presupuesto. No guarda nada."""
    if rate_limited(f"calc:{user.id}", limit=60, window=300):
        return render(request, "_presupuesto.html", error="Demasiadas consultas seguidas. Espera un momento.")

    quiere_vuelta = ida_vuelta == "true"
    try:
        puntos = _puntos_desde_json(puntos_json)
        vehiculo, coste, minutos, trazado = await _presupuesto(
            session, puntos, quiere_vuelta, pasajeros, hora_salida
        )
    except RoutingError as exc:
        return render(request, "_presupuesto.html", error=str(exc))

    return render(
        request,
        "_presupuesto.html",
        puntos=puntos,
        coste=coste,
        minutos=minutos,
        trazado=trazado,
        pasajeros=pasajeros,
        ida_vuelta=quiere_vuelta,
        decidido=ida_vuelta in ("true", "false"),
    )


@router.post("/viajes")
async def crear_viaje(
    request: Request,
    fecha_viaje: str = Form(...),
    puntos_json: str = Form("[]"),
    ida_vuelta: str = Form(""),
    pasajeros: int = Form(1),
    hora_salida: str = Form(""),
    notas: str = Form(""),
    csrf: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    if not csrf_ok(request.session, csrf):
        flash(request, "La sesión ha caducado. Vuelve a enviar el formulario.", "error")
        return redirect("/viajes/nuevo")

    if deuda_de(session, user.id) > 0:
        flash(request, "Tienes un pago pendiente. No puedes registrar otro viaje.", "error")
        return redirect("/")

    if ida_vuelta not in ("true", "false"):
        flash(request, "Indica si necesitas la vuelta o solo la ida.", "error")
        return redirect("/viajes/nuevo")

    try:
        fecha = date.fromisoformat(fecha_viaje)
    except ValueError:
        flash(request, "La fecha no tiene un formato válido.", "error")
        return redirect("/viajes/nuevo")

    try:
        puntos = _puntos_desde_json(puntos_json)
        vehiculo, coste, minutos, _trazado = await _presupuesto(
            session, puntos, ida_vuelta == "true", pasajeros, hora_salida
        )
    except RoutingError as exc:
        flash(request, str(exc), "error")
        return redirect("/viajes/nuevo")

    viaje = Trip(
        user_id=user.id,
        vehicle_id=vehiculo.id,
        origen=puntos[0].nombre,
        destino=puntos[-1].nombre,
        ruta=" → ".join(p.nombre for p in puntos)[:500],
        puntos=[p.como_dict() for p in puntos],
        fecha_viaje=fecha,
        hora_salida=(hora_salida.strip()[:5] or None),
        km_ida=coste.km_ida,
        km_vuelta=coste.km_vuelta,
        ida_vuelta=ida_vuelta == "true",
        km_total=coste.km_total,
        duracion_min=minutos,
        pasajeros=max(1, pasajeros),
        nocturno=coste.nocturno,
        recargo_pct=coste.recargo_pct,
        recargo_importe=coste.recargo_importe,
        coste_total=coste.coste_total,
        coste_usuario=coste.coste_usuario,
        reparto_aplicado=coste.reparto_aplicado,
        estado=coste.estado,
        notas=notas.strip()[:500] or None,
        **_parametros(session, vehiculo),
    )
    session.add(viaje)
    session.commit()
    session.refresh(viaje)
    session.add(
        AuditLog(
            actor_id=user.id,
            accion="alta_viaje",
            detalle=f"#{viaje.id} {viaje.ruta} · {viaje.coste_usuario} €",
        )
    )
    session.commit()

    if viaje.estado == TripStatus.PENDIENTE_PREPAGO:
        flash(
            request,
            f"Viaje registrado por {viaje.coste_usuario:.2f} €. Supera el límite de pago "
            "aplazado, así que queda pendiente de prepago: paga antes de viajar.",
            "warn",
        )
    else:
        flash(request, f"Viaje registrado. Debes {viaje.coste_usuario:.2f} €.", "ok")
    return redirect(f"/viajes/{viaje.id}")


@router.get("/viajes/{trip_id}")
def detalle(
    trip_id: int,
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    viaje = session.get(Trip, trip_id)
    if viaje is None or (viaje.user_id != user.id and user.role != "admin"):
        flash(request, "Ese viaje no existe.", "error")
        return redirect("/")

    pagos = session.exec(
        select(Payment).where(Payment.trip_id == trip_id).order_by(Payment.id)
    ).all()
    dueno = session.get(User, viaje.user_id)
    return render(request, "detalle_viaje.html", user=user, viaje=viaje, pagos=pagos, dueno=dueno)
