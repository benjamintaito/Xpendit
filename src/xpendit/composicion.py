"""Composition root: el único lugar donde se eligen e instancian los adaptadores.

El resto del código recibe sus dependencias ya construidas (por constructor), así que
cambiar de proveedor de tasas, de fuente de gastos o de reglas se hace aquí.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from xpendit.adapters.tasas import (
    TASAS_EJEMPLO_USD,
    ClienteOpenExchangeRates,
    ProveedorTasasConCache,
    ProveedorTasasFijas,
)
from xpendit.application.analizar_lote import AnalizarLote
from xpendit.domain.anomalias import detectores_por_defecto
from xpendit.domain.errores import ConfiguracionInvalida
from xpendit.domain.motor import MotorReglas
from xpendit.domain.reglas import reglas_por_defecto
from xpendit.domain.tasas import ProveedorTasas

VARIABLE_APP_ID = "OXR_APP_ID"
VARIABLE_TIMEOUT = "OXR_TIMEOUT"

MENSAJE_SIN_APP_ID = f"""\
No se encontró la variable de entorno {VARIABLE_APP_ID} (App ID de Open Exchange Rates).
Para usar tasas reales:
  1. Crea una cuenta gratuita en https://openexchangerates.org/signup/free
  2. Copia tu App ID desde https://openexchangerates.org/account/app-ids
  3. Copia la plantilla: `cp .env.example .env` (Windows: `copy .env.example .env`)
     y completa {VARIABLE_APP_ID}=<tu App ID>
O bien ejecuta el analizador con --offline para usar tasas de ejemplo."""


@dataclass(frozen=True, slots=True)
class FuenteTasas:
    proveedor: ProveedorTasas
    descripcion: str
    offline: bool
    tasas_ejemplo: Mapping[str, Decimal] | None = None
    cliente: ClienteOpenExchangeRates | None = None
    directorio_cache: str | None = None  # caché en disco realmente en uso


def leer_app_id(entorno: Mapping[str, str]) -> str:
    app_id = entorno.get(VARIABLE_APP_ID, "").strip()
    if not app_id:
        raise ConfiguracionInvalida(MENSAJE_SIN_APP_ID)
    return app_id


def leer_timeout(entorno: Mapping[str, str], por_defecto: float = 10.0) -> float:
    valor = entorno.get(VARIABLE_TIMEOUT, "").strip()
    if not valor:
        return por_defecto
    try:
        timeout = float(valor)
    except ValueError:
        timeout = math.nan
    # float() acepta "NaN" e "inf": NaN no es <= 0 y pasaría una validación que solo compare con 0.
    if not (math.isfinite(timeout) and timeout > 0):
        raise ConfiguracionInvalida(
            f"{VARIABLE_TIMEOUT} debe ser un número finito de segundos > 0 (recibido: {valor!r})."
        )
    return timeout


def construir_fuente_tasas(
    *, offline: bool, entorno: Mapping[str, str], directorio_cache: Path | None
) -> FuenteTasas:
    if offline:
        return FuenteTasas(
            proveedor=ProveedorTasasFijas(TASAS_EJEMPLO_USD),
            descripcion="Tasas fijas de ejemplo (modo --offline, sin llamadas a la API)",
            offline=True,
            tasas_ejemplo=TASAS_EJEMPLO_USD,
        )
    cliente = ClienteOpenExchangeRates(leer_app_id(entorno), timeout=leer_timeout(entorno))
    descripcion = "Open Exchange Rates, endpoint histórico (tasa del día de cada gasto)"
    if directorio_cache is not None:
        # as_posix: el reporte muestra ".cache/tasas" también en Windows.
        descripcion += f", con caché en disco en {directorio_cache.as_posix()}"
    return FuenteTasas(
        proveedor=ProveedorTasasConCache(cliente, directorio_cache),
        descripcion=descripcion,
        offline=False,
        cliente=cliente,
        directorio_cache=directorio_cache.as_posix() if directorio_cache is not None else None,
    )


def construir_analizador(proveedor: ProveedorTasas) -> AnalizarLote:
    return AnalizarLote(
        motor=MotorReglas(reglas_por_defecto()),
        proveedor_tasas=proveedor,
        detectores=detectores_por_defecto(),
    )
