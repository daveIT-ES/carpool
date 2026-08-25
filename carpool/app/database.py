"""Motor de base de datos, acceso a parámetros y datos iniciales."""

from decimal import Decimal
from pathlib import Path
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine, select

from .config import get_settings
from .models import Role, Setting, User, Vehicle
from .security import hash_password

settings = get_settings()

_connect_args = {}
if settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
    db_path = settings.database_url.split("///")[-1]
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(settings.database_url, echo=False, connect_args=_connect_args)


DEFAULTS = {
    "precio_litro": "1.550",       # €/litro
    "umbral_prepago": "10.00",     # € — por encima se paga por adelantado
    "umbral_reparto_km": "40.00",  # km de IDA — por encima se reparte entre pasajeros
    "moneda": "EUR",
    "aviso_home": "",
}


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def get_setting(session: Session, key: str) -> str:
    row = session.get(Setting, key)
    return row.value if row else DEFAULTS.get(key, "")


def get_decimal(session: Session, key: str) -> Decimal:
    return Decimal(get_setting(session, key) or "0")


def set_setting(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row:
        row.value = value
    else:
        row = Setting(key=key, value=value)
    session.add(row)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        for key, value in DEFAULTS.items():
            if session.get(Setting, key) is None:
                session.add(Setting(key=key, value=value))

        admin = session.exec(
            select(User).where(User.email == settings.admin_email)
        ).first()
        if admin is None:
            session.add(
                User(
                    alias=settings.admin_alias,
                    email=settings.admin_email,
                    password_hash=hash_password(settings.admin_password),
                    role=Role.ADMIN,
                )
            )

        if session.exec(select(Vehicle)).first() is None:
            session.add(
                Vehicle(
                    nombre="Coche principal",
                    consumo_l100=Decimal("6.50"),
                    desgaste_eur_km=Decimal("0.0800"),
                    predeterminado=True,
                )
            )

        session.commit()
