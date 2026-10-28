"""Carga la política desde un archivo JSON (la validación la hace el dominio)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from xpendit.domain.errores import PoliticaInvalida
from xpendit.domain.politica import Politica


def cargar_politica(ruta: Path) -> Politica:
    try:
        texto = ruta.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise PoliticaInvalida(f"No existe el archivo de política: {ruta}") from None
    except OSError as error:
        raise PoliticaInvalida(f"No se pudo leer la política {ruta}: {error}") from None
    try:
        # parse_float=Decimal: los límites nunca pasan por float.
        datos = json.loads(texto, parse_float=Decimal)
    except json.JSONDecodeError as error:
        raise PoliticaInvalida(
            f"La política {ruta} no es JSON válido (línea {error.lineno}, columna {error.colno}): "
            f"{error.msg}."
        ) from None
    try:
        return Politica.desde_dict(datos)
    except PoliticaInvalida as error:
        raise PoliticaInvalida(f"{ruta}: {error}") from None
