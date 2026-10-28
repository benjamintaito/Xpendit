"""Modelos del dominio: entidades inmutables, sin dependencias externas.

Los montos se representan con :class:`decimal.Decimal` y nunca con ``float``: en binario
``0.1 + 0.2 != 0.3``, y una comparación de borde como ``monto <= 100`` no puede depender
de errores de redondeo. ``Decimal`` es exacto para cantidades decimales.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any


class Estado(StrEnum):
    """Estado de un gasto tras aplicar la política."""

    APROBADO = "APROBADO"
    PENDIENTE = "PENDIENTE"
    RECHAZADO = "RECHAZADO"


@dataclass(frozen=True, slots=True)
class Gasto:
    """Un gasto rendido por un empleado.

    ``monto`` puede ser negativo o cero: el modelo no lo impide a propósito, porque
    detectar esos casos es responsabilidad de un detector de anomalías (y así se pueden
    reportar en vez de perderse como errores de lectura).
    """

    id: str
    empleado_id: str
    monto: Decimal
    moneda: str
    fecha: date
    categoria: str


@dataclass(frozen=True, slots=True)
class Empleado:
    id: str
    nombre: str
    apellido: str
    cost_center: str

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombre} {self.apellido}"


@dataclass(frozen=True, slots=True)
class Alerta:
    """Motivo legible de un estado distinto de APROBADO."""

    codigo: str
    mensaje: str

    def a_dict(self) -> dict[str, str]:
        return {"codigo": self.codigo, "mensaje": self.mensaje}


@dataclass(frozen=True, slots=True)
class ResultadoRegla:
    """Lo que dictamina una regla (o un detector de anomalías) para un gasto."""

    estado: Estado
    alertas: tuple[Alerta, ...] = ()

    @classmethod
    def aprobado(cls) -> ResultadoRegla:
        return cls(Estado.APROBADO)

    @classmethod
    def pendiente(cls, codigo: str, mensaje: str) -> ResultadoRegla:
        return cls(Estado.PENDIENTE, (Alerta(codigo, mensaje),))

    @classmethod
    def rechazado(cls, codigo: str, mensaje: str) -> ResultadoRegla:
        return cls(Estado.RECHAZADO, (Alerta(codigo, mensaje),))


@dataclass(frozen=True, slots=True)
class ResultadoValidacion:
    """Resultado final de validar un gasto contra la política."""

    gasto_id: str
    estado: Estado
    alertas: tuple[Alerta, ...] = ()

    def a_dict(self) -> dict[str, Any]:
        """Forma exacta pedida por el enunciado (``status`` en la clave serializada)."""
        return {
            "gasto_id": self.gasto_id,
            "status": self.estado.value,
            "alertas": [alerta.a_dict() for alerta in self.alertas],
        }
