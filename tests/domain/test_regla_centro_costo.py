import pytest

from tests.factories import contexto, empleado, gasto, politica
from xpendit.domain import Estado
from xpendit.domain.reglas import ReglaCentroCosto

regla = ReglaCentroCosto()


def test_core_engineering_no_puede_rendir_food() -> None:
    resultado = regla.evaluar(
        gasto(categoria="food"), empleado(cost_center="core_engineering"), contexto()
    )
    assert resultado is not None
    assert resultado.estado is Estado.RECHAZADO
    assert [a.a_dict() for a in resultado.alertas] == [
        {
            "codigo": "POLITICA_CENTRO_COSTO",
            "mensaje": "El C.C. 'core_engineering' no puede reportar 'food'.",
        }
    ]


def test_rechaza_aunque_el_monto_sea_minimo() -> None:
    resultado = regla.evaluar(
        gasto(categoria="food", monto="0.01"), empleado(cost_center="core_engineering"), contexto()
    )
    assert resultado is not None and resultado.estado is Estado.RECHAZADO


@pytest.mark.parametrize(
    ("cost_center", "categoria"),
    [
        ("core_engineering", "transport"),  # mismo C.C., otra categoría
        ("core_engineering", "software"),
        ("sales_team", "food"),  # misma categoría, otro C.C.
        ("marketing", "food"),
    ],
)
def test_no_aplica_si_no_coinciden_ambos(cost_center: str, categoria: str) -> None:
    assert (
        regla.evaluar(gasto(categoria=categoria), empleado(cost_center=cost_center), contexto())
        is None
    )


def test_soporta_varias_reglas_configuradas() -> None:
    pol = politica(
        reglas_centro_costo=[
            {"cost_center": "core_engineering", "categoria_prohibida": "food"},
            {"cost_center": "finance", "categoria_prohibida": "lodging"},
        ]
    )
    resultado = regla.evaluar(
        gasto(categoria="lodging"), empleado(cost_center="finance"), contexto(pol=pol)
    )
    assert resultado is not None
    assert resultado.alertas[0].mensaje == "El C.C. 'finance' no puede reportar 'lodging'."


def test_politica_sin_reglas_de_centro_costo_no_aplica() -> None:
    pol = politica(reglas_centro_costo=[])
    resultado = regla.evaluar(
        gasto(categoria="food"), empleado(cost_center="core_engineering"), contexto(pol=pol)
    )
    assert resultado is None
