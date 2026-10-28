"""Resolución del estado final a partir de los resultados de las reglas."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from xpendit.domain.modelos import Estado, ResultadoRegla


class ResolvedorEstado(Protocol):
    def resolver(self, resultados: Sequence[ResultadoRegla]) -> Estado: ...


class ResolvedorPorPrioridad:
    """Prioridad del enunciado: RECHAZADO > PENDIENTE > APROBADO.

    Si ninguna regla aplicó (lista vacía) el estado es PENDIENTE: sin evidencia para
    aprobar, la decisión segura es pedir revisión humana.
    """

    def __init__(
        self,
        prioridad: Sequence[Estado] = (Estado.RECHAZADO, Estado.PENDIENTE, Estado.APROBADO),
        por_defecto: Estado = Estado.PENDIENTE,
    ) -> None:
        self._prioridad = tuple(prioridad)
        self._por_defecto = por_defecto

    def resolver(self, resultados: Sequence[ResultadoRegla]) -> Estado:
        presentes = {r.estado for r in resultados}
        for estado in self._prioridad:
            if estado in presentes:
                return estado
        return self._por_defecto
