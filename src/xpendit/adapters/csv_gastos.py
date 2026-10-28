"""Adaptador de entrada: lee gastos desde un CSV.

Errores de archivo completo (no existe, faltan columnas) lanzan :class:`ArchivoInvalido`.
Errores de una fila se acumulan como :class:`FilaInvalida` y la lectura continúa: una
fila mala no debe botar el lote entero.

Montos negativos o cero *no* son errores de lectura: se cargan y los marca el detector
de anomalías, para que aparezcan en el reporte.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from xpendit.application.lote import LoteLeido, RegistroGasto
from xpendit.domain.errores import ArchivoInvalido, FilaInvalida
from xpendit.domain.modelos import Empleado, Gasto

COLUMNAS = (
    "gasto_id",
    "empleado_id",
    "empleado_nombre",
    "empleado_apellido",
    "empleado_cost_center",
    "categoria",
    "monto",
    "moneda",
    "fecha",
)
_FECHA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONEDA = re.compile(r"^[A-Z]{3}$")


class LectorCsvGastos:
    def __init__(self, ruta: Path, encoding: str = "utf-8-sig") -> None:
        self._ruta = ruta
        self._encoding = encoding  # utf-8-sig tolera el BOM que agrega Excel

    def leer(self) -> LoteLeido:
        try:
            with self._ruta.open(newline="", encoding=self._encoding) as archivo:
                lector = csv.DictReader(archivo)
                self._validar_encabezado(lector.fieldnames)
                registros: list[RegistroGasto] = []
                invalidas: list[FilaInvalida] = []
                ids_vistos: set[str] = set()
                for fila in lector:
                    try:
                        registro = _parsear_fila(fila, lector.line_num)
                        if registro.gasto.id in ids_vistos:
                            raise FilaInvalida(
                                lector.line_num,
                                "gasto_id repetido en el archivo",
                                registro.gasto.id,
                            )
                    except FilaInvalida as error:
                        invalidas.append(error)
                        continue
                    ids_vistos.add(registro.gasto.id)
                    registros.append(registro)
        except FileNotFoundError:
            raise ArchivoInvalido(f"No existe el archivo de gastos: {self._ruta}") from None
        except UnicodeDecodeError:
            raise ArchivoInvalido(
                f"El archivo {self._ruta} no está codificado en {self._encoding}."
            ) from None
        except csv.Error as error:
            raise ArchivoInvalido(f"CSV mal formado en {self._ruta}: {error}") from None
        return LoteLeido(tuple(registros), tuple(invalidas))

    def _validar_encabezado(self, columnas: Sequence[str] | None) -> None:
        if not columnas:
            raise ArchivoInvalido(f"El archivo {self._ruta} está vacío o no tiene encabezado.")
        faltantes = [c for c in COLUMNAS if c not in {x.strip() for x in columnas}]
        if faltantes:
            raise ArchivoInvalido(
                f"Faltan columnas en {self._ruta}: {', '.join(faltantes)}. "
                f"Se esperaban: {', '.join(COLUMNAS)}."
            )


def _parsear_fila(fila: Mapping[str | None, object], linea: int) -> RegistroGasto:
    # Normaliza claves (espacios en el encabezado) y detecta columnas de más/de menos.
    if None in fila:
        raise FilaInvalida(linea, "la fila tiene más columnas que el encabezado")
    valores = {str(k).strip(): v for k, v in fila.items()}
    gasto_id = str(valores.get("gasto_id") or "").strip() or None

    def campo(nombre: str) -> str:
        valor = valores.get(nombre)
        if not isinstance(valor, str) or not valor.strip():
            raise FilaInvalida(linea, f"falta el campo '{nombre}'", gasto_id)
        return valor.strip()

    texto_monto = campo("monto")
    try:
        monto = Decimal(texto_monto)
    except InvalidOperation:
        raise FilaInvalida(linea, f"monto no numérico: '{texto_monto}'", gasto_id) from None
    if not monto.is_finite():
        raise FilaInvalida(linea, f"monto no finito: '{texto_monto}'", gasto_id)

    moneda = campo("moneda").upper()
    if not _MONEDA.match(moneda):
        raise FilaInvalida(linea, f"moneda inválida: '{moneda}' (se espera ISO 4217)", gasto_id)

    texto_fecha = campo("fecha")
    try:
        if not _FECHA_ISO.match(texto_fecha):
            raise ValueError
        fecha = date.fromisoformat(texto_fecha)
    except ValueError:
        raise FilaInvalida(
            linea, f"fecha inválida: '{texto_fecha}' (se espera AAAA-MM-DD)", gasto_id
        ) from None

    empleado = Empleado(
        id=campo("empleado_id"),
        nombre=campo("empleado_nombre"),
        apellido=campo("empleado_apellido"),
        cost_center=campo("empleado_cost_center").lower(),
    )
    gasto = Gasto(
        id=campo("gasto_id"),
        empleado_id=empleado.id,
        monto=monto,
        moneda=moneda,
        fecha=fecha,
        categoria=campo("categoria").lower(),
    )
    return RegistroGasto(gasto, empleado)
