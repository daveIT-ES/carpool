"""Panel de administración: cobros, usuarios, lugares y parámetros."""

import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from ..database import get_decimal, get_session, get_setting, set_setting
from ..deps import flash, redirect, render, require_admin
from ..models import (
    AuditLog,
    DEUDA_STATES,
    InviteCode,
    Payment,
    Place,
    Trip,
    TripStatus,
    User,
    Vehicle,
)
from ..security import csrf_ok, hash_password, new_invite_code

router = APIRouter(prefix="/admin")


def _guard(request: Request, csrf: str, destino: str):
    if not csrf_ok(request.session, csrf):
        flash(request, "La sesión ha caducado. Repite la acción.", "error")
        return redirect(destino)
    return None


def _log(session: Session, actor: User, accion: str, detalle: str) -> None:
    session.add(AuditLog(actor_id=actor.id, accion=accion, detalle=detalle[:400]))


@router.get("")
def resumen(
    request: Request,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    usuarios = session.exec(select(User).order_by(User.alias)).all()
    viajes = session.exec(select(Trip).order_by(Trip.id.desc())).all()

    saldos = []
    for u in usuarios:
        pendientes = [t for t in viajes if t.user_id == u.id and t.estado in DEUDA_STATES]
        cobrado = sum(
            (t.coste_usuario for t in viajes if t.user_id == u.id and t.estado == TripStatus.PAGADO),
            Decimal("0.00"),
        )
        saldos.append(
            {
                "user": u,
                "deuda": sum((t.coste_usuario for t in pendientes), Decimal("0.00")),
                "pendientes": len(pendientes),
                "cobrado": cobrado,
                "viajes": len([t for t in viajes if t.user_id == u.id]),
            }
        )
    saldos.sort(key=lambda s: (-s["deuda"], s["user"].alias))

    return render(
        request,
        "admin_resumen.html",
        user=admin,
        saldos=saldos,
        deuda_total=sum((s["deuda"] for s in saldos), Decimal("0.00")),
        cobrado_total=sum((s["cobrado"] for s in saldos), Decimal("0.00")),
        ultimos=viajes[:12],
    )


@router.get("/viajes")
def listado_viajes(
    request: Request,
    estado: str = "",
    user_id: int = 0,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    query = select(Trip).order_by(Trip.id.desc())
    if estado:
        query = query.where(Trip.estado == estado)
    if user_id:
        query = query.where(Trip.user_id == user_id)
    viajes = session.exec(query).all()
    usuarios = {u.id: u for u in session.exec(select(User)).all()}
    return render(
        request,
        "admin_viajes.html",
        user=admin,
        viajes=viajes,
        usuarios=usuarios,
        estado=estado,
        user_id=user_id,
        estados=[s.value for s in TripStatus],
    )


@router.post("/viajes/{trip_id}/pagar")
def registrar_pago(
    trip_id: int,
    request: Request,
    importe: str = Form(""),
    metodo: str = Form("bizum"),
    nota: str = Form(""),
    csrf: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    if (r := _guard(request, csrf, "/admin/viajes")):
        return r

    viaje = session.get(Trip, trip_id)
    if viaje is None:
        flash(request, "Ese viaje no existe.", "error")
        return redirect("/admin/viajes")
    if viaje.estado == TripStatus.PAGADO:
        flash(request, "Ese viaje ya estaba cobrado.", "warn")
        return redirect("/admin/viajes")

    try:
        cantidad = Decimal(importe.replace(",", ".")) if importe.strip() else viaje.coste_usuario
    except InvalidOperation:
        flash(request, "El importe no es un número válido.", "error")
        return redirect("/admin/viajes")

    session.add(
        Payment(
            trip_id=viaje.id,
            user_id=viaje.user_id,
            importe=cantidad,
            metodo=metodo[:30],
            nota=nota[:200] or None,
            registrado_por_id=admin.id,
        )
    )
    viaje.estado = TripStatus.PAGADO
    session.add(viaje)
    _log(session, admin, "cobro", f"viaje #{viaje.id} {cantidad} € vía {metodo}")
    session.commit()
    flash(request, f"Cobro registrado: {cantidad:.2f} € del viaje #{viaje.id}.", "ok")
    return redirect(request.headers.get("referer", "/admin/viajes"))


@router.post("/viajes/{trip_id}/cancelar")
def cancelar_viaje(
    trip_id: int,
    request: Request,
    csrf: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    if (r := _guard(request, csrf, "/admin/viajes")):
        return r
    viaje = session.get(Trip, trip_id)
    if viaje is None:
        flash(request, "Ese viaje no existe.", "error")
        return redirect("/admin/viajes")
    viaje.estado = TripStatus.CANCELADO
    session.add(viaje)
    _log(session, admin, "cancelacion", f"viaje #{viaje.id}")
    session.commit()
    flash(request, f"Viaje #{viaje.id} cancelado. Deja de contar como deuda.", "ok")
    return redirect(request.headers.get("referer", "/admin/viajes"))


@router.get("/usuarios")
def usuarios(
    request: Request,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    lista = session.exec(select(User).order_by(User.alias)).all()
    invitaciones = session.exec(
        select(InviteCode).where(InviteCode.used_by_id == None).order_by(InviteCode.created_at.desc())  # noqa: E711
    ).all()
    return render(
        request, "admin_usuarios.html", user=admin, usuarios=lista, invitaciones=invitaciones
    )


@router.post("/invitaciones")
def crear_invitacion(
    request: Request,
    csrf: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    if (r := _guard(request, csrf, "/admin/usuarios")):
        return r
    code = new_invite_code()
    session.add(InviteCode(code=code, created_by_id=admin.id))
    _log(session, admin, "invitacion", code)
    session.commit()
    flash(request, f"Código de invitación creado: {code}", "ok")
    return redirect("/admin/usuarios")


@router.post("/usuarios/{user_id}/estado")
def cambiar_estado(
    user_id: int,
    request: Request,
    csrf: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    if (r := _guard(request, csrf, "/admin/usuarios")):
        return r
    u = session.get(User, user_id)
    if u is None or u.id == admin.id:
        flash(request, "No puedes desactivar tu propia cuenta.", "error")
        return redirect("/admin/usuarios")
    u.is_active = not u.is_active
    session.add(u)
    _log(session, admin, "estado_usuario", f"{u.alias} activo={u.is_active}")
    session.commit()
    flash(request, f"Cuenta de {u.alias} {'activada' if u.is_active else 'desactivada'}.", "ok")
    return redirect("/admin/usuarios")


@router.post("/usuarios/{user_id}/password")
def reset_password(
    user_id: int,
    request: Request,
    password: str = Form(...),
    csrf: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    if (r := _guard(request, csrf, "/admin/usuarios")):
        return r
    u = session.get(User, user_id)
    if u is None:
        flash(request, "Ese usuario no existe.", "error")
        return redirect("/admin/usuarios")
    if len(password) < 8:
        flash(request, "La contraseña necesita 8 caracteres como mínimo.", "error")
        return redirect("/admin/usuarios")
    u.password_hash = hash_password(password)
    session.add(u)
    _log(session, admin, "reset_password", u.alias)
    session.commit()
    flash(request, f"Contraseña de {u.alias} actualizada.", "ok")
    return redirect("/admin/usuarios")


@router.get("/lugares")
def lugares(
    request: Request,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    lista = session.exec(select(Place).order_by(Place.nombre)).all()
    return render(request, "admin_lugares.html", user=admin, lugares=lista)


@router.post("/lugares")
def crear_lugar(
    request: Request,
    nombre: str = Form(...),
    lat: float = Form(...),
    lon: float = Form(...),
    csrf: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    if (r := _guard(request, csrf, "/admin/lugares")):
        return r
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        flash(request, "Las coordenadas están fuera de rango.", "error")
        return redirect("/admin/lugares")
    session.add(Place(nombre=nombre.strip()[:120], lat=lat, lon=lon))
    _log(session, admin, "alta_lugar", nombre)
    session.commit()
    flash(request, f"Punto «{nombre}» añadido.", "ok")
    return redirect("/admin/lugares")


@router.post("/lugares/{place_id}/estado")
def estado_lugar(
    place_id: int,
    request: Request,
    csrf: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    if (r := _guard(request, csrf, "/admin/lugares")):
        return r
    p = session.get(Place, place_id)
    if p:
        p.activo = not p.activo
        session.add(p)
        session.commit()
    return redirect("/admin/lugares")


@router.get("/config")
def config(
    request: Request,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    vehiculos = session.exec(select(Vehicle).order_by(Vehicle.nombre)).all()
    return render(
        request,
        "admin_config.html",
        user=admin,
        vehiculos=vehiculos,
        precio_litro=get_setting(session, "precio_litro"),
        umbral_prepago=get_setting(session, "umbral_prepago"),
        umbral_reparto_km=get_setting(session, "umbral_reparto_km"),
        recargo_noche_pct=get_setting(session, "recargo_noche_pct"),
        noche_desde=get_setting(session, "noche_desde"),
        noche_hasta=get_setting(session, "noche_hasta"),
        aviso_home=get_setting(session, "aviso_home"),
    )


@router.post("/config")
def guardar_config(
    request: Request,
    precio_litro: str = Form(...),
    umbral_prepago: str = Form(...),
    umbral_reparto_km: str = Form(...),
    recargo_noche_pct: str = Form("0"),
    noche_desde: str = Form("22:00"),
    noche_hasta: str = Form("06:00"),
    aviso_home: str = Form(""),
    csrf: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    if (r := _guard(request, csrf, "/admin/config")):
        return r
    try:
        valores = {
            "precio_litro": Decimal(precio_litro.replace(",", ".")),
            "umbral_prepago": Decimal(umbral_prepago.replace(",", ".")),
            "umbral_reparto_km": Decimal(umbral_reparto_km.replace(",", ".")),
            "recargo_noche_pct": Decimal(recargo_noche_pct.replace(",", ".")),
        }
    except InvalidOperation:
        flash(request, "Revisa los valores numéricos.", "error")
        return redirect("/admin/config")

    for k, v in valores.items():
        if v < 0:
            flash(request, "Los valores no pueden ser negativos.", "error")
            return redirect("/admin/config")
        set_setting(session, k, str(v))
    import re as _re
    for clave, valor in (("noche_desde", noche_desde), ("noche_hasta", noche_hasta)):
        if not _re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", valor.strip()):
            flash(request, "Las horas deben tener el formato HH:MM.", "error")
            return redirect("/admin/config")
        set_setting(session, clave, valor.strip())
    set_setting(session, "aviso_home", aviso_home.strip()[:200])
    _log(session, admin, "config", str(valores))
    session.commit()
    flash(request, "Parámetros guardados. Los viajes ya registrados no cambian.", "ok")
    return redirect("/admin/config")


@router.post("/vehiculos/{vehicle_id}")
def guardar_vehiculo(
    vehicle_id: int,
    request: Request,
    nombre: str = Form(...),
    consumo_l100: str = Form(...),
    desgaste_eur_km: str = Form(...),
    csrf: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    if (r := _guard(request, csrf, "/admin/config")):
        return r
    v = session.get(Vehicle, vehicle_id)
    if v is None:
        flash(request, "Ese vehículo no existe.", "error")
        return redirect("/admin/config")
    try:
        v.consumo_l100 = Decimal(consumo_l100.replace(",", "."))
        v.desgaste_eur_km = Decimal(desgaste_eur_km.replace(",", "."))
    except InvalidOperation:
        flash(request, "Revisa el consumo y el desgaste.", "error")
        return redirect("/admin/config")
    v.nombre = nombre.strip()[:80]
    session.add(v)
    _log(session, admin, "vehiculo", f"{v.nombre} {v.consumo_l100}L/100 {v.desgaste_eur_km}€/km")
    session.commit()
    flash(request, "Vehículo actualizado.", "ok")
    return redirect("/admin/config")


@router.get("/export.csv")
def exportar(
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    viajes = session.exec(select(Trip).order_by(Trip.id)).all()
    usuarios = {u.id: u.alias for u in session.exec(select(User)).all()}

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(
        ["id", "fecha", "usuario", "origen", "destino", "recorrido", "paradas",
         "km_ida", "km_vuelta", "ida_vuelta", "km_total", "pasajeros", "reparto",
         "hora", "nocturno", "recargo_pct", "recargo", "coste_total",
         "coste_usuario", "estado"]
    )
    for t in viajes:
        w.writerow(
            [t.id, t.fecha_viaje, usuarios.get(t.user_id, "?"), t.origen, t.destino,
             t.ruta, max(0, len(t.puntos or []) - 2),
             t.km_ida, t.km_vuelta, int(t.ida_vuelta), t.km_total, t.pasajeros,
             int(t.reparto_aplicado), t.hora_salida or "", int(t.nocturno),
             t.recargo_pct, t.recargo_importe, t.coste_total,
             t.coste_usuario, t.estado.value]
        )
    buf.seek(0)
    nombre = f"viajes-{datetime.now():%Y%m%d}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
