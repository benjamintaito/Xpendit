from datetime import date

import pytest

from tests.factories import contexto, empleado, gasto, politica
from xpendit.domain import Estado, Politica, ResultadoRegla
from xpendit.domain.reglas import ReglaAntiguedad

regla = ReglaAntiguedad()


def evaluar(dias: int, pol: Politica | None = None) -> ResultadoRegla:
    resultado = regla.evaluar(gasto(dias=dias), empleado(), contexto(pol=pol))
    assert resultado is not None
    return resultado


@pytest.mark.parametrize(
    ("dias", "esperado"),
    [
        (0, Estado.APROBADO),  # mismo día
        (1, Estado.APROBADO),
        (29, Estado.APROBADO),
        (30, Estado.APROBADO),  # borde superior del tramo aprobado
        (31, Estado.PENDIENTE),  # primer día pendiente
        (45, Estado.PENDIENTE),
        (60, Estado.PENDIENTE),  # borde superior del tramo pendiente
        (61, Estado.RECHAZADO),  # primer día rechazado
        (365, Estado.RECHAZADO),
    ],
)
def test_estado_segun_dias_de_antiguedad(dias: int, esperado: Estado) -> None:
    resultado = evaluar(dias)
    assert resultado is not None
    assert resultado.estado is esperado


@pytest.mark.parametrize("dias", [0, 30])
def test_aprobado_no_genera_alertas(dias: int) -> None:
    assert evaluar(dias).alertas == ()


@pytest.mark.parametrize("dias", [31, 60])
def test_pendiente_tiene_alerta_del_enunciado(dias: int) -> None:
    resultado = evaluar(dias)
    assert [(a.codigo, a.mensaje) for a in resultado.alertas] == [
        ("LIMITE_ANTIGUEDAD", "Gasto excede los 30 días. Requiere revisión.")
    ]


@pytest.mark.parametrize("dias", [61, 400])
def test_rechazado_tiene_alerta_de_antiguedad(dias: int) -> None:
    resultado = evaluar(dias)
    assert [(a.codigo, a.mensaje) for a in resultado.alertas] == [
        ("LIMITE_ANTIGUEDAD", "Gasto excede los 60 días. Rechazado por antigüedad.")
    ]


@pytest.mark.parametrize("dias", [-1, -30])
def test_fecha_futura_queda_pendiente_con_alerta(dias: int) -> None:
    resultado = evaluar(dias)
    assert resultado.estado is Estado.PENDIENTE
    (alerta,) = resultado.alertas
    assert alerta.codigo == "FECHA_FUTURA"
    assert "posterior a la fecha de referencia (2026-10-26)" in alerta.mensaje


def test_sin_limite_de_antiguedad_en_la_politica_no_aplica() -> None:
    ctx = contexto(pol=politica(limite_antiguedad=None))
    assert regla.evaluar(gasto(dias=500), empleado(), ctx) is None


@pytest.mark.parametrize(
    ("dias", "esperado"),
    [(7, Estado.APROBADO), (8, Estado.PENDIENTE), (14, Estado.PENDIENTE), (15, Estado.RECHAZADO)],
)
def test_umbrales_se_leen_de_la_politica(dias: int, esperado: Estado) -> None:
    pol = politica(limite_antiguedad={"pendiente_dias": 7, "rechazado_dias": 14})
    assert evaluar(dias, pol=pol).estado is esperado


def test_umbrales_iguales_pasan_directo_de_aprobado_a_rechazado() -> None:
    pol = politica(limite_antiguedad={"pendiente_dias": 30, "rechazado_dias": 30})
    assert evaluar(30, pol=pol).estado is Estado.APROBADO
    assert evaluar(31, pol=pol).estado is Estado.RECHAZADO


def test_usa_la_fecha_de_referencia_inyectada_y_no_la_de_hoy() -> None:
    # Gasto de 2020: respecto de una referencia en 2020 es reciente.
    g = gasto(fecha=date(2020, 1, 10))
    resultado = regla.evaluar(g, empleado(), contexto(fecha_referencia=date(2020, 1, 20)))
    assert resultado is not None and resultado.estado is Estado.APROBADO


def test_cuenta_dias_calendario_cruzando_mes_y_anio_bisiesto() -> None:
    # 2024-01-31 -> 2024-03-01 son 30 días (febrero de 2024 tiene 29).
    g = gasto(fecha=date(2024, 1, 31))
    resultado = regla.evaluar(g, empleado(), contexto(fecha_referencia=date(2024, 3, 1)))
    assert resultado is not None and resultado.estado is Estado.APROBADO
    resultado = regla.evaluar(g, empleado(), contexto(fecha_referencia=date(2024, 3, 2)))
    assert resultado is not None and resultado.estado is Estado.PENDIENTE
