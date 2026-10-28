"""Regla transversal: el monto debe poder expresarse en la moneda base de la política."""

from __future__ import annotations

from xpendit.domain.errores import ConversionNoDisponible
from xpendit.domain.modelos import Empleado, Gasto, ResultadoRegla
from xpendit.domain.reglas.base import ContextoEvaluacion


class ReglaConversionMoneda:
    """Un gasto en moneda extranjera sin tasa para convertirlo no puede aprobarse solo.

    - Moneda igual a la base                 -> ``None`` (no hay nada que convertir)
    - Conversión posible                     -> ``None`` (la regla no opina)
    - Sin tasa para la moneda o la fecha     -> PENDIENTE (TASA_NO_DISPONIBLE)

    Es independiente de la categoría: aunque ninguna regla compare el monto (p. ej.
    ``software`` no tiene límite), nadie verificó cuánto vale el gasto en la moneda base,
    así que decide una persona. Es la única dueña de la alerta: la regla de límite por
    categoría no aplica cuando falta la tasa, para no duplicarla.

    Las fallas de infraestructura (:class:`ErrorProveedorTasas`) no se ocultan: solo se
    captura :class:`ConversionNoDisponible`, que es un caso de negocio.
    """

    CODIGO = "TASA_NO_DISPONIBLE"
    nombre = "conversion_moneda"

    def evaluar(
        self, gasto: Gasto, empleado: Empleado, contexto: ContextoEvaluacion
    ) -> ResultadoRegla | None:
        base = contexto.politica.moneda_base
        try:
            contexto.conversor.convertir(gasto.monto, gasto.moneda, base, gasto.fecha)
        except ConversionNoDisponible as error:
            return ResultadoRegla.pendiente(
                self.CODIGO,
                f"No se pudo convertir {gasto.monto} {gasto.moneda} a {base}: {error} "
                "Requiere revisión.",
            )
        return None
