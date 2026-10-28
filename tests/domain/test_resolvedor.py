from itertools import permutations

import pytest

from xpendit.domain import Estado, ResultadoRegla
from xpendit.domain.resolucion import ResolvedorPorPrioridad

A, P, R = Estado.APROBADO, Estado.PENDIENTE, Estado.RECHAZADO


def resultados(*estados: Estado) -> list[ResultadoRegla]:
    return [ResultadoRegla(e) for e in estados]


@pytest.mark.parametrize(
    ("estados", "esperado"),
    [
        ((), P),  # ninguna regla aplica -> PENDIENTE por defecto
        ((A,), A),
        ((P,), P),
        ((R,), R),
        ((A, A), A),
        ((A, P), P),
        ((A, R), R),
        ((P, R), R),
        ((A, P, R), R),
        ((P, P, A), P),
    ],
)
def test_prioridad_rechazado_pendiente_aprobado(
    estados: tuple[Estado, ...], esperado: Estado
) -> None:
    assert ResolvedorPorPrioridad().resolver(resultados(*estados)) is esperado


@pytest.mark.parametrize("orden", list(permutations([A, P, R])))
def test_el_orden_de_las_reglas_no_importa(orden: tuple[Estado, ...]) -> None:
    assert ResolvedorPorPrioridad().resolver(resultados(*orden)) is R


def test_por_defecto_es_configurable() -> None:
    assert ResolvedorPorPrioridad(por_defecto=A).resolver([]) is A
