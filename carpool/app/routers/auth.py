"""Alta de usuarios (por invitación), inicio y cierre de sesión."""

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from sqlmodel import Session, select

from ..database import get_session
from ..deps import current_user, flash, redirect, render
from ..models import AuditLog, InviteCode, Role, User
from ..security import csrf_ok, hash_password, rate_limited, verify_password

router = APIRouter()


@router.get("/login")
def login_form(request: Request, user=Depends(current_user)):
    if user:
        return redirect("/")
    return render(request, "login.html")


@router.post("/login")
def login(
    request: Request,
    identificador: str = Form(...),
    password: str = Form(...),
    csrf: str = Form(""),
    session: Session = Depends(get_session),
):
    if not csrf_ok(request.session, csrf):
        flash(request, "La sesión ha caducado. Inténtalo de nuevo.", "error")
        return redirect("/login")

    ip = request.client.host if request.client else "?"
    if rate_limited(f"login:{ip}", limit=10, window=300):
        flash(request, "Demasiados intentos. Espera unos minutos.", "error")
        return redirect("/login")

    ident = identificador.strip().lower()
    user = session.exec(
        select(User).where((User.email == ident) | (User.alias == ident))
    ).first()

    if not user or not verify_password(password, user.password_hash):
        flash(request, "Usuario o contraseña incorrectos.", "error")
        return redirect("/login")
    if not user.is_active:
        flash(request, "Esta cuenta está desactivada. Habla con el administrador.", "error")
        return redirect("/login")

    request.session.clear()
    request.session["uid"] = user.id
    return redirect("/")


@router.get("/registro")
def register_form(request: Request, codigo: str = "", user=Depends(current_user)):
    if user:
        return redirect("/")
    return render(request, "register.html", codigo=codigo)


@router.post("/registro")
def register(
    request: Request,
    alias: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    codigo: str = Form(...),
    csrf: str = Form(""),
    session: Session = Depends(get_session),
):
    if not csrf_ok(request.session, csrf):
        flash(request, "La sesión ha caducado. Inténtalo de nuevo.", "error")
        return redirect("/registro")

    ip = request.client.host if request.client else "?"
    if rate_limited(f"reg:{ip}", limit=6, window=900):
        flash(request, "Demasiados intentos. Espera unos minutos.", "error")
        return redirect("/registro")

    alias = alias.strip().lower()
    email = email.strip().lower()
    code = codigo.strip().upper()

    if len(alias) < 3 or not alias.replace("_", "").replace(".", "").isalnum():
        flash(request, "El alias necesita 3 caracteres o más, sin espacios ni símbolos.", "error")
        return redirect(f"/registro?codigo={code}")
    if len(password) < 8:
        flash(request, "La contraseña necesita 8 caracteres como mínimo.", "error")
        return redirect(f"/registro?codigo={code}")

    invite = session.get(InviteCode, code)
    if invite is None or invite.used_by_id is not None:
        flash(request, "Ese código de invitación no es válido o ya se ha usado.", "error")
        return redirect("/registro")

    existe = session.exec(
        select(User).where((User.email == email) | (User.alias == alias))
    ).first()
    if existe:
        flash(request, "Ya hay una cuenta con ese alias o correo.", "error")
        return redirect(f"/registro?codigo={code}")

    user = User(
        alias=alias,
        email=email,
        password_hash=hash_password(password),
        role=Role.USER,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    invite.used_by_id = user.id
    invite.used_at = datetime.utcnow()
    session.add(invite)
    session.add(
        AuditLog(actor_id=user.id, accion="alta_usuario", detalle=f"{alias} con código {code}")
    )
    session.commit()

    request.session.clear()
    request.session["uid"] = user.id
    flash(request, f"Cuenta creada. Bienvenido, {alias}.", "ok")
    return redirect("/")


@router.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    if csrf_ok(request.session, csrf):
        request.session.clear()
    return redirect("/login")
