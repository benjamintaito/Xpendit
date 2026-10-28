"""Puerto de tasas de cambio y conversor de moneda.

El dominio solo conoce el *puerto* :class:`ProveedorTasas`; las implementaciones
(HTTP, memoria, caché) son adaptadores que se inyectan desde fuera. Así el motor de
reglas nunca hace I/O y se prueba con tasas fijas.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from xpendit.domain.errores import MonedaNoSoportada, TasasNoDisponibles

CENTAVO = Decimal("0.01")


@runtime_checkable
class ProveedorTasas(Protocol):
    """Puerto: entrega las tasas vigentes en una fecha.

    Contrato: devuelve ``{codigo_moneda: unidades_por_1_unidad_pivote}`` (con
    Open Exchange Rates el pivote es USD, p. ej. ``{"USD": 1, "CLP": 950.12, ...}``).
    Puede lanzar ``TasasNoDisponibles`` (caso de negocio) o ``ErrorProveedorTasas``
    (falla de infraestructura).
    """

    def obtener_tasas(self, fecha: date) -> Mapping[str, Decimal]: ...


class TasasPrecargadas:
    """Instantánea inmutable de tasas por fecha; implementa el puerto sin hacer I/O.

    El analizador de lotes consulta al proveedor real una vez por fecha y luego evalúa
    todos los gastos contra esta instantánea: la evaluación queda libre de red y una
    fecha que falló no se vuelve a pedir por cada gasto (``fallas`` guarda el motivo).
    """

    def __init__(
        self,
        por_fecha: Mapping[date, Mapping[str, Decimal]],
        fallas: Mapping[date, str] | None = None,
    ) -> None:
        self._por_fecha = {f: MappingProxyType(dict(t)) for f, t in por_fecha.items()}
        self._fallas = dict(fallas or {})

    @property
    def fallas(self) -> Mapping[date, str]:
        return MappingProxyType(self._fallas)

    def obtener_tasas(self, fecha: date) -> Mapping[str, Decimal]:
        tasas = self._por_fecha.get(fecha)
        if tasas is None:
            raise TasasNoDisponibles(fecha, self._fallas.get(fecha))
        return tasas


class ConversorMoneda:
    """Convierte montos entre monedas usando tasas cruzadas de un mismo pivote.

    Si ``tasas[X]`` son unidades de X por 1 unidad del pivote::

        monto_destino = monto / tasas[origen] * tasas[destino]

    Funciona con cualquier moneda destino (no solo USD), aunque el plan gratuito de
    Open Exchange Rates no permita cambiar el pivote.
    """

    def __init__(self, proveedor: ProveedorTasas, precision: Decimal = CENTAVO) -> None:
        self._proveedor = proveedor
        self._precision = precision

    def convertir(self, monto: Decimal, origen: str, destino: str, fecha: date) -> Decimal:
        """Convierte ``monto`` de ``origen`` a ``destino`` con las tasas de ``fecha``.

        - Misma moneda: devuelve el monto intacto y no consulta al proveedor.
        - Moneda distinta: redondea a centavos (ROUND_HALF_UP) el resultado, porque un
          monto monetario no tiene fracciones de centavo y así la comparación con los
          límites no depende de decimales espurios de la división.
        """
        origen, destino = origen.upper(), destino.upper()
        if origen == destino:
            return monto
        tasas = self._proveedor.obtener_tasas(fecha)
        tasa_origen = _tasa(tasas, origen, fecha)
        tasa_destino = _tasa(tasas, destino, fecha)
        return (monto / tasa_origen * tasa_destino).quantize(self._precision, ROUND_HALF_UP)


def _tasa(tasas: Mapping[str, Decimal], moneda: str, fecha: date) -> Decimal:
    tasa = tasas.get(moneda)
    if tasa is None or tasa <= 0:
        raise MonedaNoSoportada(moneda, fecha)
    return tasa
