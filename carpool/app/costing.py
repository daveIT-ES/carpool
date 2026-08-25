"""Cálculo del coste de un trayecto.

Fórmula:
    coste_km    = precio_litro / 100 * consumo_l100 + desgaste_eur_km
    km_ida      = origen -> paradas intermedias -> destino
    km_vuelta   = destino -> origen (0 si es solo ida)
    coste_total = (km_ida + km_vuelta) * coste_km

Reparto:
    Si la distancia de IDA supera `umbral_reparto_km` y hay más de un
    pasajero, el coste se divide entre los pasajeros. Por debajo de ese
    umbral cada pasajero paga el trayecto completo. La vuelta no cuenta
    para decidir el reparto, solo para el importe.

Recargo nocturno:
    Si la hora de salida cae dentro de la franja nocturna configurada, se
    aplica un porcentaje extra sobre el coste del recorrido. El recargo se
    suma antes de repartir entre los pasajeros.

Prepago:
    Si lo que paga el usuario supera `umbral_prepago`, el viaje queda
    pendiente de prepago y no se considera confirmado hasta cobrarlo.
    Exactamente en el umbral (p. ej. 10,00 €) NO se exige prepago.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from .models import TripStatus

CENT = Decimal("0.01")


def q2(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def es_nocturno(hora: Optional[str], desde: str, hasta: str) -> bool:
    """¿La hora "HH:MM" cae en la franja nocturna? Admite franjas que cruzan
    la medianoche (p. ej. de 22:00 a 06:00)."""
    def minutos(txt: str) -> Optional[int]:
        try:
            h, m = str(txt).strip().split(":")
            h, m = int(h), int(m)
        except (ValueError, AttributeError):
            return None
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None
        return h * 60 + m

    t, d, f = minutos(hora), minutos(desde), minutos(hasta)
    if t is None or d is None or f is None or d == f:
        return False
    if d < f:                 # franja normal, p. ej. 01:00-05:00
        return d <= t < f
    return t >= d or t < f    # franja que cruza medianoche


@dataclass
class Coste:
    km_ida: Decimal
    km_vuelta: Decimal
    km_total: Decimal
    coste_km: Decimal
    coste_recorrido: Decimal
    nocturno: bool
    recargo_pct: Decimal
    recargo_importe: Decimal
    coste_total: Decimal
    coste_usuario: Decimal
    reparto_aplicado: bool
    requiere_prepago: bool
    estado: TripStatus


def calcular(
    *,
    km_ida: Decimal,
    km_vuelta: Decimal = Decimal("0"),
    pasajeros: int,
    precio_litro: Decimal,
    consumo_l100: Decimal,
    desgaste_eur_km: Decimal,
    umbral_reparto_km: Decimal,
    umbral_prepago: Decimal,
    hora_salida: Optional[str] = None,
    recargo_noche_pct: Decimal = Decimal("0"),
    noche_desde: str = "22:00",
    noche_hasta: str = "06:00",
) -> Coste:
    km_ida = Decimal(km_ida)
    km_vuelta = Decimal(km_vuelta or 0)
    pasajeros = max(1, int(pasajeros))

    km_total = km_ida + km_vuelta
    coste_km = Decimal(precio_litro) / Decimal(100) * Decimal(consumo_l100) + Decimal(
        desgaste_eur_km
    )
    coste_recorrido = q2(km_total * coste_km)

    pct = Decimal(recargo_noche_pct or 0)
    nocturno = pct > 0 and es_nocturno(hora_salida, noche_desde, noche_hasta)
    recargo = q2(coste_recorrido * pct / Decimal(100)) if nocturno else Decimal("0.00")
    coste_total = q2(coste_recorrido + recargo)

    reparto = km_ida > Decimal(umbral_reparto_km) and pasajeros > 1
    coste_usuario = q2(coste_total / pasajeros) if reparto else coste_total

    requiere_prepago = coste_usuario > Decimal(umbral_prepago)
    estado = (
        TripStatus.PENDIENTE_PREPAGO if requiere_prepago else TripStatus.PENDIENTE_PAGO
    )

    return Coste(
        km_ida=q2(km_ida),
        km_vuelta=q2(km_vuelta),
        km_total=q2(km_total),
        coste_km=coste_km,
        coste_recorrido=coste_recorrido,
        nocturno=nocturno,
        recargo_pct=pct if nocturno else Decimal("0.00"),
        recargo_importe=recargo,
        coste_total=coste_total,
        coste_usuario=coste_usuario,
        reparto_aplicado=reparto,
        requiere_prepago=requiere_prepago,
        estado=estado,
    )
