"""Regla 2: límite de monto por categoría, en la moneda base de la política."""

from __future__ import annotations

from xpendit.domain.errores import ConversionNoDisponible
from xpendit.domain.modelos import Empleado, Gasto, ResultadoRegla
from xpendit.domain.reglas.base import ContextoEvaluacion


class ReglaLimiteCategoria:
    """Genérica para cualquier categoría de ``limites_por_categoria``.

    Con ``monto`` ya convertido a la moneda base:

    - ``monto <= aprobado_hasta``                    -> APROBADO
    - ``aprobado_hasta < monto <= pendiente_hasta``  -> PENDIENTE ("Requiere revisión")
    - ``monto > pendiente_hasta``                    -> RECHAZADO ("Excede límite aprobado")

    Si ``aprobado_hasta == pendiente_hasta`` (p. ej. transport 200/200) el tramo
    PENDIENTE queda vacío y se pasa directo de APROBADO a RECHAZADO, sin casos especiales.

    - Categoría sin límite configurado -> ``None`` (la regla no aplica).
    - Sin tasa para convertir -> ``None``: sin monto en moneda base no hay nada que
      comparar. La falta de tasa la reporta :class:`ReglaConversionMoneda` (PENDIENTE con
      TASA_NO_DISPONIBLE) para cualquier categoría, una sola vez.
    """

    CODIGO = "LIMITE_CATEGORIA"
    nombre = "limite_categoria"

    def evaluar(
        self, gasto: Gasto, empleado: Empleado, contexto: ContextoEvaluacion
    ) -> ResultadoRegla | None:
        politica = contexto.politica
        limite = politica.limites_por_categoria.get(gasto.categoria)
        if limite is None:
            return None

        base = politica.moneda_base
        try:
            monto = contexto.conversor.convertir(gasto.monto, gasto.moneda, base, gasto.fecha)
        except ConversionNoDisponible:
            return None

        if monto <= limite.aprobado_hasta:
            return ResultadoRegla.aprobado()
        if monto <= limite.pendiente_hasta:
            return ResultadoRegla.pendiente(
                self.CODIGO,
                f"Requiere revisión: {monto} {base} supera el límite de aprobación automática "
                f"de {limite.aprobado_hasta} {base} para '{gasto.categoria}'.",
            )
        return ResultadoRegla.rechazado(
            self.CODIGO,
            f"Excede límite aprobado: {monto} {base} supera el máximo de "
            f"{limite.pendiente_hasta} {base} para '{gasto.categoria}'.",
        )
