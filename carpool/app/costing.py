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

Prepago:
    Si lo que paga el usuario supera `umbral_prepago`, el viaje queda
    pendiente de prepago y no se considera confirmado hasta cobrarlo.
    Exactamente en el umbral (p. ej. 10,00 €) NO se exige prepago.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from .models import TripStatus

CENT = Decimal("0.01")


def q2(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class Coste:
    km_ida: Decimal
    km_vuelta: Decimal
    km_total: Decimal
    coste_km: Decimal
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
) -> Coste:
    km_ida = Decimal(km_ida)
    km_vuelta = Decimal(km_vuelta or 0)
    pasajeros = max(1, int(pasajeros))

    km_total = km_ida + km_vuelta
    coste_km = Decimal(precio_litro) / Decimal(100) * Decimal(consumo_l100) + Decimal(
        desgaste_eur_km
    )
    coste_total = q2(km_total * coste_km)

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
        coste_total=coste_total,
        coste_usuario=coste_usuario,
        reparto_aplicado=reparto,
        requiere_prepago=requiere_prepago,
        estado=estado,
    )
