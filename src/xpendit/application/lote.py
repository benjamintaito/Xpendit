"""Tipos de la capa de aplicación: puerto de lectura del lote y reporte resultante."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol

from xpendit.domain.errores import FilaInvalida
from xpendit.domain.modelos import Empleado, Estado, Gasto, ResultadoValidacion
from xpendit.domain.politica import Politica


@dataclass(frozen=True, slots=True)
class RegistroGasto:
    """Un gasto junto al empleado que lo rindió (así viene en cada fila del CSV)."""

    gasto: Gasto
    empleado: Empleado


@dataclass(frozen=True, slots=True)
class LoteLeido:
    registros: tuple[RegistroGasto, ...]
    filas_invalidas: tuple[FilaInvalida, ...] = ()

    @property
    def filas_leidas(self) -> int:
        return len(self.registros) + len(self.filas_invalidas)


class LectorGastos(Protocol):
    """Puerto de entrada: cualquier fuente de gastos (CSV, base de datos, API...)."""

    def leer(self) -> LoteLeido: ...


@dataclass(frozen=True, slots=True)
class ResultadoGasto:
    registro: RegistroGasto
    validacion: ResultadoValidacion
    monto_base: Decimal | None
    dias_antiguedad: int

    @property
    def estado(self) -> Estado:
        return self.validacion.estado

    @property
    def codigos(self) -> tuple[str, ...]:
        return tuple(a.codigo for a in self.validacion.alertas)


@dataclass(frozen=True, slots=True)
class EstadisticasTasas:
    """Cómo se obtuvieron las tasas (evidencia de la optimización N+1)."""

    fechas_unicas: int
    fechas_consultadas: tuple[date, ...]
    fallas: Mapping[date, str] = field(default_factory=dict)

    @property
    def consultas(self) -> int:
        return len(self.fechas_consultadas)


@dataclass(frozen=True, slots=True)
class ReporteLote:
    fecha_referencia: date
    politica: Politica
    resultados: tuple[ResultadoGasto, ...]
    filas_invalidas: tuple[FilaInvalida, ...]
    tasas: EstadisticasTasas

    @property
    def filas_leidas(self) -> int:
        return len(self.resultados) + len(self.filas_invalidas)

    def conteo_por_estado(self) -> dict[Estado, int]:
        conteo = Counter(r.estado for r in self.resultados)
        return {estado: conteo.get(estado, 0) for estado in Estado}

    def conteo_por_alerta(self) -> Counter[str]:
        """Cantidad de gastos que tienen cada código de alerta."""
        return Counter(codigo for r in self.resultados for codigo in set(r.codigos))

    def sin_monto_base(self) -> int:
        """Gastos que no se pudieron convertir a la moneda base (quedan fuera de los montos)."""
        return sum(1 for r in self.resultados if r.monto_base is None)

    def gastos(self) -> Sequence[Gasto]:
        return [r.registro.gasto for r in self.resultados]
