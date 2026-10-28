"""Decorador de ProveedorTasas que memoiza por fecha (memoria y, opcionalmente, disco).

Las tasas históricas de un día ya cerrado no cambian, así que se pueden guardar para
siempre: la caché en disco evita gastar cuota de la API entre corridas. Las tasas del
día en curso (o futuro) solo se guardan en memoria, porque todavía pueden cambiar.

El disco es una entrada externa más (alguien pudo editarlo, copiarlo, o quedó a medias): al
leer se exige que el campo ``fecha`` coincida con la fecha pedida y se valida cada código y
cada tasa con el mismo criterio que una respuesta de la API; ante el menor problema se ignora
el archivo completo y se vuelve a consultar.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType

from xpendit.domain.tasas import ProveedorTasas

logger = logging.getLogger(__name__)

_CODIGO_MONEDA = re.compile(r"[A-Z]{3}")


class ProveedorTasasConCache:
    def __init__(
        self,
        interno: ProveedorTasas,
        directorio: Path | None = None,
        hoy: Callable[[], date] = date.today,
    ) -> None:
        self._interno = interno
        self._directorio = directorio
        self._hoy = hoy
        self._memoria: dict[date, Mapping[str, Decimal]] = {}

    def obtener_tasas(self, fecha: date) -> Mapping[str, Decimal]:
        if fecha in self._memoria:
            return self._memoria[fecha]

        tasas = self._leer_disco(fecha)
        if tasas is None:
            # Las fallas del proveedor interno se propagan y no se cachean: un error
            # transitorio no debe quedar "pegado".
            tasas = MappingProxyType(dict(self._interno.obtener_tasas(fecha)))
            if fecha < self._hoy():
                self._escribir_disco(fecha, tasas)

        self._memoria[fecha] = tasas
        return tasas

    # --- disco ---------------------------------------------------------------------

    def _ruta(self, fecha: date) -> Path | None:
        return self._directorio / f"{fecha.isoformat()}.json" if self._directorio else None

    def _leer_disco(self, fecha: date) -> Mapping[str, Decimal] | None:
        ruta = self._ruta(fecha)
        if ruta is None or not ruta.exists():
            return None
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"), parse_float=Decimal)
            # Un archivo copiado bajo el nombre de otro día tendría tasas válidas pero ajenas.
            if datos.get("fecha") != fecha.isoformat():
                raise ValueError(f"la fecha del archivo no es {fecha.isoformat()}")
            tasas = _validar_tasas(datos["tasas"])
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            logger.warning(
                "Caché de tasas inválida en %s (%s); se ignora y se vuelve a consultar.", ruta, exc
            )
            return None
        return MappingProxyType(tasas)

    def _escribir_disco(self, fecha: date, tasas: Mapping[str, Decimal]) -> None:
        ruta = self._ruta(fecha)
        if ruta is None:
            return
        contenido = json.dumps(
            {"fecha": fecha.isoformat(), "tasas": {k: str(v) for k, v in sorted(tasas.items())}},
            indent=2,
        )
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            # Escritura atómica: un corte a mitad de camino no deja un JSON truncado.
            fd, temporal = tempfile.mkstemp(dir=ruta.parent, suffix=".tmp")
        except OSError as exc:
            logger.warning("No se pudo escribir la caché de tasas en %s: %s", ruta, exc)
            return
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as archivo:
                archivo.write(contenido)
            # El temporal ya está cerrado: Windows no permite reemplazar con un archivo abierto.
            # os.replace sí sobrescribe el destino en Windows (os.rename no), aunque falla si
            # otro proceso lo tiene abierto; en ese caso solo se pierde esta escritura.
            os.replace(temporal, ruta)
        except OSError as exc:
            with contextlib.suppress(OSError):
                os.remove(temporal)  # que no queden .tmp huérfanos en el directorio
            logger.warning("No se pudo escribir la caché de tasas en %s: %s", ruta, exc)


def _validar_tasas(crudas: object) -> dict[str, Decimal]:
    """Exige un objeto no vacío de ``{código de 3 letras: tasa finita > 0}``.

    Lanza ``ValueError`` ante la primera entrada inválida (``NaN``, ``Infinity``, ``0``,
    negativos, booleanos, códigos mal formados...): un archivo con una sola tasa mala no es
    confiable entero.
    """
    if not isinstance(crudas, dict) or not crudas:
        raise ValueError("sin tasas")
    tasas: dict[str, Decimal] = {}
    for codigo, valor in crudas.items():
        if not _CODIGO_MONEDA.fullmatch(codigo):
            raise ValueError(f"código de moneda inválido: {codigo!r}")
        if isinstance(valor, bool) or not isinstance(valor, (str, int, Decimal)):
            raise ValueError(f"tasa inválida para {codigo}")
        try:
            tasa = Decimal(valor)
        except InvalidOperation:
            raise ValueError(f"tasa inválida para {codigo}") from None
        if not tasa.is_finite() or tasa <= 0:
            raise ValueError(f"tasa inválida para {codigo}")
        tasas[codigo] = tasa
    return tasas
