"""Motor de reglas: aplica una lista de reglas y resuelve el estado final.

El motor no conoce ninguna regla concreta (Open/Closed): recibe las estrategias y el
resolvedor por constructor.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from xpendit.domain.modelos import Alerta, Empleado, Gasto, ResultadoRegla, ResultadoValidacion
from xpendit.domain.reglas.base import ContextoEvaluacion, Regla
from xpendit.domain.resolucion import ResolvedorEstado, ResolvedorPorPrioridad


class MotorReglas:
    def __init__(self, reglas: Sequence[Regla], resolvedor: ResolvedorEstado | None = None) -> None:
        self._reglas = tuple(reglas)
        self._resolvedor = resolvedor or ResolvedorPorPrioridad()

    @property
    def reglas(self) -> tuple[Regla, ...]:
        return self._reglas

    def evaluar(
        self,
        gasto: Gasto,
        empleado: Empleado,
        contexto: ContextoEvaluacion,
        hallazgos_adicionales: Iterable[ResultadoRegla] = (),
    ) -> ResultadoValidacion:
        """Evalúa un gasto.

        ``hallazgos_adicionales`` permite sumar dictámenes que no salen de mirar un gasto
        aislado (p. ej. anomalías del lote, como duplicados); entran a la misma
        resolución de prioridad que las reglas.

        Las alertas de *todas* las reglas se conservan (no solo las de la regla que
        ganó), para que quien revise vea todos los motivos.
        """
        resultados: list[ResultadoRegla] = []
        for regla in self._reglas:
            resultado = regla.evaluar(gasto, empleado, contexto)
            if resultado is not None:
                resultados.append(resultado)
        resultados.extend(hallazgos_adicionales)

        estado = self._resolvedor.resolver(resultados)
        alertas: tuple[Alerta, ...] = tuple(a for r in resultados for a in r.alertas)
        return ResultadoValidacion(gasto_id=gasto.id, estado=estado, alertas=alertas)
