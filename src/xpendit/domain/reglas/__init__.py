"""Reglas de la política (Strategy).

Para agregar una regla: crear una clase con ``nombre`` y
``evaluar(gasto, empleado, contexto) -> ResultadoRegla | None`` y sumarla a
:func:`reglas_por_defecto`. El motor no se modifica.
"""

from xpendit.domain.reglas.antiguedad import ReglaAntiguedad
from xpendit.domain.reglas.base import ContextoEvaluacion, Regla
from xpendit.domain.reglas.centro_costo import ReglaCentroCosto
from xpendit.domain.reglas.conversion_moneda import ReglaConversionMoneda
from xpendit.domain.reglas.limite_categoria import ReglaLimiteCategoria


def reglas_por_defecto() -> list[Regla]:
    """Registro de las reglas, en el orden en que se reportan sus alertas.

    Las tres del enunciado más :class:`ReglaConversionMoneda`, que impide aprobar un
    gasto cuyo monto no se pudo expresar en la moneda base.
    """
    return [ReglaAntiguedad(), ReglaConversionMoneda(), ReglaLimiteCategoria(), ReglaCentroCosto()]


__all__ = [
    "ContextoEvaluacion",
    "Regla",
    "ReglaAntiguedad",
    "ReglaCentroCosto",
    "ReglaConversionMoneda",
    "ReglaLimiteCategoria",
    "reglas_por_defecto",
]
