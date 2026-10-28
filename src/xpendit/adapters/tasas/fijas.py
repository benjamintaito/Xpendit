"""Proveedor de tasas en memoria (mock): para tests y para el modo ``--offline``."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from types import MappingProxyType

from xpendit.domain.errores import TasasNoDisponibles

# Tasas aproximadas (unidades por 1 USD) usadas por el modo --offline. Son valores
# redondos de ejemplo, NO cotizaciones reales: el análisis definitivo debe regenerarse
# con la API real.
TASAS_EJEMPLO_USD: Mapping[str, Decimal] = MappingProxyType(
    {
        "USD": Decimal("1"),
        "CLP": Decimal("900"),
        "MXN": Decimal("17.5"),
        "EUR": Decimal("0.92"),
    }
)


class ProveedorTasasFijas:
    """Devuelve tasas desde memoria, sin I/O.

    - ``por_fecha``: tasas específicas por fecha (tienen prioridad).
    - ``tasas``: tasas por defecto para cualquier otra fecha (``None`` = no hay).

    Una fecha sin tasas lanza :class:`TasasNoDisponibles`.
    """

    def __init__(
        self,
        tasas: Mapping[str, Decimal] | None = None,
        por_fecha: Mapping[date, Mapping[str, Decimal]] | None = None,
    ) -> None:
        self._tasas = dict(tasas) if tasas is not None else None
        self._por_fecha = {f: dict(t) for f, t in (por_fecha or {}).items()}

    def obtener_tasas(self, fecha: date) -> Mapping[str, Decimal]:
        if fecha in self._por_fecha:
            return MappingProxyType(self._por_fecha[fecha])
        if self._tasas is not None:
            return MappingProxyType(self._tasas)
        raise TasasNoDisponibles(fecha)
