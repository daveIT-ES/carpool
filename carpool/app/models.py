"""Modelo de datos.

Nota de diseño: los viajes guardan un *snapshot* de los parámetros de coste
(precio del litro, consumo, desgaste). Si mañana cambia el precio del
combustible, los viajes ya registrados no se recalculan.
"""

from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import JSON, Column, Numeric
from sqlmodel import Field, SQLModel


def _money(**kw) -> Field:
    return Field(sa_column=Column(Numeric(10, 2), **kw))


class Role(str, Enum):
    USER = "user"
    ADMIN = "admin"


class TripStatus(str, Enum):
    PENDIENTE_PREPAGO = "PENDIENTE_PREPAGO"  # > umbral: no se viaja hasta pagar
    PENDIENTE_PAGO = "PENDIENTE_PAGO"        # <= umbral: se paga después
    PAGADO = "PAGADO"
    CANCELADO = "CANCELADO"


DEUDA_STATES = (TripStatus.PENDIENTE_PREPAGO, TripStatus.PENDIENTE_PAGO)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    alias: str = Field(index=True, unique=True, max_length=40)
    email: str = Field(index=True, unique=True, max_length=200)
    password_hash: str
    role: Role = Field(default=Role.USER)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Place(SQLModel, table=True):
    """Puntos de origen/destino predefinidos por el administrador."""

    __tablename__ = "places"

    id: Optional[int] = Field(default=None, primary_key=True)
    nombre: str = Field(max_length=120)
    lat: float
    lon: float
    activo: bool = Field(default=True)


class Vehicle(SQLModel, table=True):
    __tablename__ = "vehicles"

    id: Optional[int] = Field(default=None, primary_key=True)
    nombre: str = Field(max_length=80)
    consumo_l100: Decimal = _money()          # litros / 100 km
    desgaste_eur_km: Decimal = Field(sa_column=Column(Numeric(10, 4)))
    activo: bool = Field(default=True)
    predeterminado: bool = Field(default=False)


class Setting(SQLModel, table=True):
    """Parámetros globales editables por el administrador."""

    __tablename__ = "settings"

    key: str = Field(primary_key=True, max_length=60)
    value: str = Field(max_length=200)


class Trip(SQLModel, table=True):
    __tablename__ = "trips"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    vehicle_id: Optional[int] = Field(default=None, foreign_key="vehicles.id")

    origen: str = Field(max_length=120)
    destino: str = Field(max_length=120)
    ruta: str = Field(default="", max_length=500)     # "A -> B -> C" para listados
    puntos: list = Field(default_factory=list, sa_column=Column(JSON))
    fecha_viaje: date
    hora_salida: Optional[str] = Field(default=None, max_length=5)   # "HH:MM"

    km_ida: Decimal = _money()          # origen -> paradas -> destino
    km_vuelta: Decimal = _money()       # destino -> origen (0 si es solo ida)
    ida_vuelta: bool = Field(default=False)
    km_total: Decimal = _money()
    duracion_min: Optional[int] = None
    pasajeros: int = Field(default=1)

    # snapshot de parámetros
    precio_litro: Decimal = _money()
    consumo_l100: Decimal = _money()
    desgaste_eur_km: Decimal = Field(sa_column=Column(Numeric(10, 4)))
    umbral_reparto_km: Decimal = _money()
    umbral_prepago: Decimal = _money()

    nocturno: bool = Field(default=False)
    recargo_pct: Decimal = _money()          # % aplicado por horario nocturno
    recargo_importe: Decimal = _money()

    coste_total: Decimal = _money()          # combustible + desgaste + recargo
    coste_usuario: Decimal = _money()
    reparto_aplicado: bool = Field(default=False)

    estado: TripStatus = Field(default=TripStatus.PENDIENTE_PAGO, index=True)
    notas: Optional[str] = Field(default=None, max_length=500)
    # Quien dio de alta el viaje. Distinto de user_id cuando lo registra
    # el administrador a nombre de otra persona.
    registrado_por_id: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Payment(SQLModel, table=True):
    __tablename__ = "payments"

    id: Optional[int] = Field(default=None, primary_key=True)
    trip_id: int = Field(foreign_key="trips.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    importe: Decimal = _money()
    metodo: str = Field(default="bizum", max_length=30)
    fecha: datetime = Field(default_factory=datetime.utcnow)
    registrado_por_id: int = Field(foreign_key="users.id")
    nota: Optional[str] = Field(default=None, max_length=200)


class InviteCode(SQLModel, table=True):
    __tablename__ = "invite_codes"

    code: str = Field(primary_key=True, max_length=24)
    created_by_id: int = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    used_by_id: Optional[int] = Field(default=None, foreign_key="users.id")
    used_at: Optional[datetime] = None


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=datetime.utcnow, index=True)
    actor_id: Optional[int] = Field(default=None, foreign_key="users.id")
    accion: str = Field(max_length=60)
    detalle: str = Field(max_length=400)
