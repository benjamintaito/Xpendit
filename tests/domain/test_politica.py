from decimal import Decimal
from typing import Any

import pytest

from tests.factories import POLITICA_EJEMPLO
from xpendit.domain import Politica
from xpendit.domain.errores import PoliticaInvalida
from xpendit.domain.politica import LimiteAntiguedad, LimiteCategoria, ReglaCentroCostoConfig


def test_carga_la_politica_del_enunciado() -> None:
    pol = Politica.desde_dict(POLITICA_EJEMPLO)
    assert pol.moneda_base == "USD"
    assert pol.limite_antiguedad == LimiteAntiguedad(30, 60)
    assert pol.limites_por_categoria["food"] == LimiteCategoria(Decimal("100"), Decimal("150"))
    assert pol.limites_por_categoria["transport"] == LimiteCategoria(Decimal("200"), Decimal("200"))
    assert pol.reglas_centro_costo == (ReglaCentroCostoConfig("core_engineering", "food"),)


def test_secciones_opcionales_pueden_faltar() -> None:
    pol = Politica.desde_dict({"moneda_base": "usd"})
    assert pol.moneda_base == "USD"
    assert pol.limite_antiguedad is None
    assert dict(pol.limites_por_categoria) == {}
    assert pol.reglas_centro_costo == ()


def test_normaliza_mayusculas_y_espacios() -> None:
    pol = Politica.desde_dict(
        {
            "moneda_base": " eur ",
            "limites_por_categoria": {"Food": {"aprobado_hasta": 1, "pendiente_hasta": 2}},
            "reglas_centro_costo": [
                {"cost_center": "Core_Engineering ", "categoria_prohibida": "FOOD"}
            ],
        }
    )
    assert pol.moneda_base == "EUR"
    assert "food" in pol.limites_por_categoria
    assert pol.reglas_centro_costo[0] == ReglaCentroCostoConfig("core_engineering", "food")


def test_floats_se_convierten_sin_error_binario() -> None:
    pol = Politica.desde_dict(
        {
            "moneda_base": "USD",
            "limites_por_categoria": {"x": {"aprobado_hasta": 0.1, "pendiente_hasta": 0.3}},
        }
    )
    assert pol.limites_por_categoria["x"].aprobado_hasta == Decimal("0.1")


def test_limites_son_inmutables() -> None:
    pol = Politica.desde_dict(POLITICA_EJEMPLO)
    with pytest.raises(TypeError):
        pol.limites_por_categoria["food"] = LimiteCategoria(Decimal(0), Decimal(0))  # type: ignore[index]


def con(**cambios: Any) -> dict[str, Any]:
    return {**POLITICA_EJEMPLO, **cambios}


@pytest.mark.parametrize(
    ("datos", "fragmento"),
    [
        ([], "objeto JSON"),
        ({}, "moneda_base"),
        (con(moneda_base="dolar"), "moneda_base"),
        (con(moneda_base=840), "moneda_base"),
        (con(limite_antiguedad=[30, 60]), "limite_antiguedad"),
        (con(limite_antiguedad={"pendiente_dias": -1, "rechazado_dias": 60}), "pendiente_dias"),
        (con(limite_antiguedad={"pendiente_dias": 30}), "rechazado_dias"),
        (con(limite_antiguedad={"pendiente_dias": 30.5, "rechazado_dias": 60}), "pendiente_dias"),
        (con(limite_antiguedad={"pendiente_dias": True, "rechazado_dias": 60}), "pendiente_dias"),
        (
            con(limite_antiguedad={"pendiente_dias": 60, "rechazado_dias": 30}),
            "rechazado_dias debe ser >=",
        ),
        (con(limites_por_categoria=[]), "limites_por_categoria"),
        (con(limites_por_categoria={"food": 100}), "limites_por_categoria.food"),
        (con(limites_por_categoria={"food": {"aprobado_hasta": 100}}), "food.pendiente_hasta"),
        (
            con(limites_por_categoria={"food": {"aprobado_hasta": -1, "pendiente_hasta": 5}}),
            "aprobado_hasta",
        ),
        (
            con(limites_por_categoria={"food": {"aprobado_hasta": "cien", "pendiente_hasta": 5}}),
            "no es un número",
        ),
        (
            con(limites_por_categoria={"food": {"aprobado_hasta": "NaN", "pendiente_hasta": 5}}),
            "finito",
        ),
        (
            con(limites_por_categoria={"food": {"aprobado_hasta": False, "pendiente_hasta": 5}}),
            "aprobado_hasta",
        ),
        (
            con(limites_por_categoria={"food": {"aprobado_hasta": 150, "pendiente_hasta": 100}}),
            "pendiente_hasta debe ser >=",
        ),
        (con(reglas_centro_costo={"cost_center": "x"}), "reglas_centro_costo"),
        (con(reglas_centro_costo=["x"]), "reglas_centro_costo[0]"),
        (
            con(reglas_centro_costo=[{"categoria_prohibida": "food"}]),
            "reglas_centro_costo[0].cost_center",
        ),
        (
            con(reglas_centro_costo=[{"cost_center": "cc", "categoria_prohibida": ""}]),
            "categoria_prohibida",
        ),
    ],
)
def test_rechaza_politicas_invalidas_con_mensaje_claro(datos: Any, fragmento: str) -> None:
    with pytest.raises(PoliticaInvalida) as error:
        Politica.desde_dict(datos)
    assert fragmento in str(error.value)


def test_reporta_todos_los_errores_juntos() -> None:
    with pytest.raises(PoliticaInvalida) as error:
        Politica.desde_dict(
            {"moneda_base": "x", "limite_antiguedad": {"pendiente_dias": -1, "rechazado_dias": 1}}
        )
    mensaje = str(error.value)
    assert "moneda_base" in mensaje and "pendiente_dias" in mensaje
