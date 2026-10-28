from datetime import date

import pytest

from tests.factories import gasto
from xpendit.domain import Estado
from xpendit.domain.anomalias import (
    DetectorDuplicados,
    DetectorMontoInvalido,
    clave_estricta,
    detectores_por_defecto,
)

D1, D2 = date(2026, 10, 7), date(2026, 10, 8)


# --- Duplicados -------------------------------------------------------------------------


def test_marca_solo_las_copias_y_referencia_al_original() -> None:
    gastos = [
        gasto(id="g_1", monto="90", fecha=D1),
        gasto(id="g_2", monto="90", fecha=D1),
        gasto(id="g_3", monto="90", fecha=D1),
    ]
    alertas = DetectorDuplicados().detectar(gastos)
    assert set(alertas) == {"g_2", "g_3"}
    (alerta,) = alertas["g_3"]
    assert alerta.codigo == "DUPLICADO_EXACTO"
    assert alerta.mensaje == "Posible duplicado de g_1: mismo monto (90 USD) y fecha (2026-10-07)."


def test_el_original_es_el_primero_en_el_orden_del_lote() -> None:
    gastos = [gasto(id="g_9", fecha=D1), gasto(id="g_1", fecha=D1)]
    assert set(DetectorDuplicados().detectar(gastos)) == {"g_1"}


@pytest.mark.parametrize(
    "otro",
    [
        gasto(id="g_2", monto="90.01", fecha=D1),  # distinto monto
        gasto(id="g_2", monto="90", moneda="EUR", fecha=D1),  # distinta moneda
        gasto(id="g_2", monto="90", fecha=D2),  # distinta fecha
    ],
)
def test_no_es_duplicado_si_cambia_monto_moneda_o_fecha(otro: object) -> None:
    gastos = [gasto(id="g_1", monto="90", fecha=D1), otro]
    assert DetectorDuplicados().detectar(gastos) == {}  # type: ignore[arg-type]


def test_montos_equivalentes_con_distinta_escala_son_duplicados() -> None:
    gastos = [gasto(id="g_1", monto="90", fecha=D1), gasto(id="g_2", monto="90.00", fecha=D1)]
    assert set(DetectorDuplicados().detectar(gastos)) == {"g_2"}


def test_definicion_del_enunciado_ignora_empleado_y_categoria() -> None:
    gastos = [
        gasto(id="g_1", empleado_id="e_1", categoria="food", fecha=D1),
        gasto(id="g_2", empleado_id="e_2", categoria="transport", fecha=D1),
    ]
    assert set(DetectorDuplicados().detectar(gastos)) == {"g_2"}
    assert DetectorDuplicados(clave_estricta).detectar(gastos) == {}


def test_grupos_en_orden_de_aparicion() -> None:
    gastos = [
        gasto(id="a", monto="1", fecha=D1),
        gasto(id="b", monto="2", fecha=D1),
        gasto(id="c", monto="1", fecha=D1),
        gasto(id="d", monto="2", fecha=D1),
        gasto(id="e", monto="3", fecha=D1),
    ]
    grupos = DetectorDuplicados().grupos(gastos)
    assert [[g.id for g in grupo] for grupo in grupos] == [["a", "c"], ["b", "d"]]


def test_duplicado_impone_pendiente_por_defecto() -> None:
    assert DetectorDuplicados().estado is Estado.PENDIENTE


def test_lote_vacio() -> None:
    assert DetectorDuplicados().detectar([]) == {}


# --- Montos inválidos ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("monto", "fragmento"),
    [("-50", "Monto negativo"), ("-0.01", "Monto negativo"), ("0", "Monto cero")],
)
def test_monto_negativo_o_cero_se_marca(monto: str, fragmento: str) -> None:
    alertas = DetectorMontoInvalido().detectar([gasto(id="g_1", monto=monto)])
    (alerta,) = alertas["g_1"]
    assert alerta.codigo == "MONTO_INVALIDO"
    assert alerta.mensaje.startswith(fragmento)


@pytest.mark.parametrize("monto", ["0.01", "1", "100000"])
def test_monto_positivo_no_se_marca(monto: str) -> None:
    assert DetectorMontoInvalido().detectar([gasto(monto=monto)]) == {}


def test_monto_invalido_impone_rechazado() -> None:
    assert DetectorMontoInvalido().estado is Estado.RECHAZADO


def test_detectores_por_defecto() -> None:
    codigos = [d.codigo for d in detectores_por_defecto()]
    assert codigos == ["DUPLICADO_EXACTO", "MONTO_INVALIDO"]
