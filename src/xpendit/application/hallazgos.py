"""Consultas de análisis sobre un :class:`ReporteLote` (insumos para ANALISIS.md).

Funciones puras: no formatean nada, solo agregan datos.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal

from xpendit.application.lote import ReporteLote, ResultadoGasto
from xpendit.domain.anomalias import DetectorDuplicados, clave_enunciado, clave_estricta
from xpendit.domain.modelos import Empleado, Estado, Gasto


@dataclass(frozen=True, slots=True)
class ResumenEmpleado:
    empleado: Empleado
    total: int
    por_estado: dict[Estado, int]
    monto_base_rechazado: Decimal


@dataclass(frozen=True, slots=True)
class ComparacionDuplicados:
    grupos_enunciado: list[list[Gasto]]
    grupos_estrictos: list[list[Gasto]]
    grupos_entre_empleados: list[list[Gasto]]

    @staticmethod
    def marcados(grupos: list[list[Gasto]]) -> int:
        """Gastos marcados como copia (todos menos el original de cada grupo)."""
        return sum(len(g) - 1 for g in grupos)


def comparar_duplicados(reporte: ReporteLote) -> ComparacionDuplicados:
    gastos = reporte.gastos()
    enunciado = DetectorDuplicados(clave_enunciado).grupos(gastos)
    estrictos = DetectorDuplicados(clave_estricta).grupos(gastos)
    entre_empleados = [g for g in enunciado if len({x.empleado_id for x in g}) > 1]
    return ComparacionDuplicados(enunciado, estrictos, entre_empleados)


def resumen_por_empleado(reporte: ReporteLote) -> list[ResumenEmpleado]:
    """Ordenado por cantidad de rechazos (desc.) y luego por nombre."""
    por_empleado: dict[str, list[ResultadoGasto]] = defaultdict(list)
    for r in reporte.resultados:
        por_empleado[r.registro.empleado.id].append(r)

    resumenes = []
    for resultados in por_empleado.values():
        conteo = Counter(r.estado for r in resultados)
        rechazado = sum(
            (r.monto_base for r in resultados if r.estado is Estado.RECHAZADO and r.monto_base),
            Decimal(0),
        )
        resumenes.append(
            ResumenEmpleado(
                empleado=resultados[0].registro.empleado,
                total=len(resultados),
                por_estado={e: conteo.get(e, 0) for e in Estado},
                monto_base_rechazado=rechazado,
            )
        )
    return sorted(
        resumenes,
        key=lambda x: (-x.por_estado[Estado.RECHAZADO], x.empleado.nombre_completo),
    )


def motivos_por_estado(reporte: ReporteLote, estado: Estado) -> Counter[str]:
    """Códigos de alerta presentes en los gastos que terminaron en ``estado``."""
    return Counter(
        codigo for r in reporte.resultados if r.estado is estado for codigo in set(r.codigos)
    )


def monto_base_por_estado(reporte: ReporteLote) -> dict[Estado, Decimal]:
    totales = {e: Decimal(0) for e in Estado}
    for r in reporte.resultados:
        if r.monto_base is not None:
            totales[r.estado] += r.monto_base
    return totales


def con_alerta(reporte: ReporteLote, codigo: str) -> list[ResultadoGasto]:
    return [r for r in reporte.resultados if codigo in r.codigos]
