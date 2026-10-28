"""Regla 3 (cruzada): categorías prohibidas por centro de costo."""

from __future__ import annotations

from xpendit.domain.modelos import Empleado, Gasto, ResultadoRegla
from xpendit.domain.reglas.base import ContextoEvaluacion


class ReglaCentroCosto:
    """Cruza datos del gasto (categoría) y del empleado (centro de costo).

    Si alguna entrada de ``reglas_centro_costo`` coincide -> RECHAZADO
    (POLITICA_CENTRO_COSTO). Si no, la regla no aplica (``None``): que no esté prohibido
    no significa que esté aprobado.
    """

    CODIGO = "POLITICA_CENTRO_COSTO"
    nombre = "centro_costo"

    def evaluar(
        self, gasto: Gasto, empleado: Empleado, contexto: ContextoEvaluacion
    ) -> ResultadoRegla | None:
        for regla in contexto.politica.reglas_centro_costo:
            if (
                regla.cost_center == empleado.cost_center
                and regla.categoria_prohibida == gasto.categoria
            ):
                return ResultadoRegla.rechazado(
                    self.CODIGO,
                    f"El C.C. '{empleado.cost_center}' no puede reportar '{gasto.categoria}'.",
                )
        return None
