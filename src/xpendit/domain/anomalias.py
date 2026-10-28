"""Detectores de anomalías de lote.

A diferencia de una regla (que mira un gasto aislado), un detector mira el conjunto
completo de gastos (p. ej. para encontrar duplicados). Cada detector declara qué estado
impone su anomalía; el caso de uso convierte sus alertas en un :class:`ResultadoRegla`
que entra a la misma resolución de prioridad que las reglas.

Para agregar una anomalía: crear una clase con ``codigo``, ``estado`` y
``detectar(gastos) -> dict[gasto_id, list[Alerta]]`` y sumarla a
:func:`detectores_por_defecto`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Hashable, Sequence
from typing import Protocol

from xpendit.domain.modelos import Alerta, Estado, Gasto

ClaveDuplicado = Callable[[Gasto], Hashable]


class DetectorAnomalias(Protocol):
    @property
    def codigo(self) -> str: ...

    @property
    def estado(self) -> Estado: ...

    def detectar(self, gastos: Sequence[Gasto]) -> dict[str, list[Alerta]]: ...


def clave_enunciado(gasto: Gasto) -> Hashable:
    """Definición del enunciado: mismo monto, moneda y fecha."""
    return (gasto.monto, gasto.moneda, gasto.fecha)


def clave_estricta(gasto: Gasto) -> Hashable:
    """Variante más estricta: además, mismo empleado y categoría."""
    return (gasto.empleado_id, gasto.categoria, gasto.monto, gasto.moneda, gasto.fecha)


class DetectorDuplicados:
    """Marca como ``DUPLICADO_EXACTO`` cada gasto que repite la clave de uno anterior.

    El primero de cada grupo (en el orden del lote) se considera el original y no se
    marca; las copias quedan al menos PENDIENTE para revisión humana. No se rechazan en
    automático porque la coincidencia puede ser legítima (dos personas que gastan lo
    mismo el mismo día).
    """

    codigo = "DUPLICADO_EXACTO"

    def __init__(
        self, clave: ClaveDuplicado = clave_enunciado, estado: Estado = Estado.PENDIENTE
    ) -> None:
        self._clave = clave
        self.estado = estado

    def grupos(self, gastos: Sequence[Gasto]) -> list[list[Gasto]]:
        """Grupos con más de un gasto, en orden de aparición (el primero es el original)."""
        por_clave: dict[Hashable, list[Gasto]] = defaultdict(list)
        for gasto in gastos:
            por_clave[self._clave(gasto)].append(gasto)
        return [grupo for grupo in por_clave.values() if len(grupo) > 1]

    def detectar(self, gastos: Sequence[Gasto]) -> dict[str, list[Alerta]]:
        alertas: dict[str, list[Alerta]] = {}
        for original, *copias in self.grupos(gastos):
            for copia in copias:
                alertas[copia.id] = [
                    Alerta(
                        self.codigo,
                        f"Posible duplicado de {original.id}: mismo monto "
                        f"({copia.monto} {copia.moneda}) y fecha ({copia.fecha.isoformat()}).",
                    )
                ]
        return alertas


class DetectorMontoInvalido:
    """Marca como ``MONTO_INVALIDO`` los gastos con monto negativo o cero.

    Se rechazan: no hay nada que reembolsar. Si un negativo representa una devolución o
    nota de crédito, debe ir por otro flujo y no como rendición de gasto.
    """

    codigo = "MONTO_INVALIDO"

    def __init__(self, estado: Estado = Estado.RECHAZADO) -> None:
        self.estado = estado

    def detectar(self, gastos: Sequence[Gasto]) -> dict[str, list[Alerta]]:
        alertas: dict[str, list[Alerta]] = {}
        for gasto in gastos:
            if gasto.monto < 0:
                motivo = "Monto negativo"
            elif gasto.monto == 0:
                motivo = "Monto cero"
            else:
                continue
            alertas[gasto.id] = [
                Alerta(
                    self.codigo,
                    f"{motivo} ({gasto.monto} {gasto.moneda}): no corresponde a un gasto "
                    "reembolsable.",
                )
            ]
        return alertas


def detectores_por_defecto() -> list[DetectorAnomalias]:
    return [DetectorDuplicados(), DetectorMontoInvalido()]
