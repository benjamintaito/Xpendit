"""Interfaz común de las reglas (patrón Strategy) y el contexto que reciben."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from xpendit.domain.modelos import Empleado, Gasto, ResultadoRegla
from xpendit.domain.politica import Politica
from xpendit.domain.tasas import ConversorMoneda


@dataclass(frozen=True, slots=True)
class ContextoEvaluacion:
    """Todo lo externo al gasto que una regla puede necesitar.

    ``fecha_referencia`` se inyecta (nunca ``date.today()`` dentro del dominio): así el
    resultado es reproducible y los tests de bordes son deterministas.
    """

    politica: Politica
    fecha_referencia: date
    conversor: ConversorMoneda


class Regla(Protocol):
    """Una regla de la política.

    ``evaluar`` devuelve ``None`` cuando la regla no aplica al gasto (p. ej. una
    categoría sin límite configurado). Esto es distinto de APROBADO: si ninguna regla
    aplica, el estado por defecto es PENDIENTE.
    """

    @property
    def nombre(self) -> str: ...

    def evaluar(
        self, gasto: Gasto, empleado: Empleado, contexto: ContextoEvaluacion
    ) -> ResultadoRegla | None: ...
