"""Regla 1: antigüedad del gasto respecto de la fecha de referencia."""

from __future__ import annotations

from xpendit.domain.modelos import Empleado, Gasto, ResultadoRegla
from xpendit.domain.reglas.base import ContextoEvaluacion


class ReglaAntiguedad:
    """``días = fecha_referencia - fecha_gasto``.

    - ``0 <= días <= pendiente_dias``             -> APROBADO
    - ``pendiente_dias < días <= rechazado_dias`` -> PENDIENTE (LIMITE_ANTIGUEDAD)
    - ``días > rechazado_dias``                   -> RECHAZADO (LIMITE_ANTIGUEDAD)
    - ``días < 0`` (fecha futura)                 -> PENDIENTE (FECHA_FUTURA)

    Los umbrales salen de la política, no están fijos en el código.
    """

    CODIGO = "LIMITE_ANTIGUEDAD"
    CODIGO_FECHA_FUTURA = "FECHA_FUTURA"
    nombre = "antiguedad"

    def evaluar(
        self, gasto: Gasto, empleado: Empleado, contexto: ContextoEvaluacion
    ) -> ResultadoRegla | None:
        limite = contexto.politica.limite_antiguedad
        if limite is None:
            return None

        dias = (contexto.fecha_referencia - gasto.fecha).days
        if dias < 0:
            # Una fecha futura suele ser un error de digitación; no se rechaza en
            # automático, pero tampoco se aprueba sin que alguien la mire.
            return ResultadoRegla.pendiente(
                self.CODIGO_FECHA_FUTURA,
                f"La fecha del gasto ({gasto.fecha.isoformat()}) es posterior a la fecha "
                f"de referencia ({contexto.fecha_referencia.isoformat()}). Requiere revisión.",
            )
        if dias <= limite.pendiente_dias:
            return ResultadoRegla.aprobado()
        if dias <= limite.rechazado_dias:
            return ResultadoRegla.pendiente(
                self.CODIGO,
                f"Gasto excede los {limite.pendiente_dias} días. Requiere revisión.",
            )
        return ResultadoRegla.rechazado(
            self.CODIGO,
            f"Gasto excede los {limite.rechazado_dias} días. Rechazado por antigüedad.",
        )
