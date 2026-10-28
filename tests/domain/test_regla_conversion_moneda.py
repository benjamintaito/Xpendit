"""Regla de conversión: sin tasa no hay monto en moneda base, y eso requiere revisión."""

from datetime import date
from decimal import Decimal

import pytest

from tests.factories import contexto, empleado, gasto, politica
from xpendit.adapters.tasas import ProveedorTasasFijas
from xpendit.domain import Estado, MotorReglas, reglas_por_defecto
from xpendit.domain.errores import ErrorProveedorTasas
from xpendit.domain.reglas import ReglaConversionMoneda

regla = ReglaConversionMoneda()


@pytest.mark.parametrize("categoria", ["food", "transport", "software", "otra"])
def test_moneda_sin_tasa_queda_pendiente_en_cualquier_categoria(categoria: str) -> None:
    resultado = regla.evaluar(
        gasto(monto="5000", moneda="JPY", categoria=categoria), empleado(), contexto()
    )
    assert resultado is not None and resultado.estado is Estado.PENDIENTE
    (alerta,) = resultado.alertas
    assert alerta.codigo == "TASA_NO_DISPONIBLE"
    assert "JPY" in alerta.mensaje and "USD" in alerta.mensaje


def test_fecha_sin_tasas_queda_pendiente() -> None:
    ctx = contexto(proveedor=ProveedorTasasFijas(por_fecha={}))
    resultado = regla.evaluar(gasto(monto="5000", moneda="CLP"), empleado(), ctx)
    assert resultado is not None and resultado.alertas[0].codigo == "TASA_NO_DISPONIBLE"


@pytest.mark.parametrize("moneda", ["USD", "usd"])
def test_moneda_base_no_aplica_ni_consulta_tasas(moneda: str) -> None:
    ctx = contexto(proveedor=ProveedorTasasFijas(por_fecha={}))
    assert regla.evaluar(gasto(moneda=moneda), empleado(), ctx) is None


def test_conversion_posible_no_aplica() -> None:
    assert regla.evaluar(gasto(monto="90000", moneda="CLP"), empleado(), contexto()) is None


def test_moneda_base_distinta_de_usd() -> None:
    ctx = contexto(pol=politica(moneda_base="EUR"))
    assert regla.evaluar(gasto(moneda="EUR"), empleado(), ctx) is None
    assert regla.evaluar(gasto(moneda="USD"), empleado(), ctx) is None  # vía tasas cruzadas


def test_falla_de_infraestructura_no_se_oculta() -> None:
    class ProveedorCaido:
        def obtener_tasas(self, fecha: date) -> dict[str, Decimal]:
            raise ErrorProveedorTasas("sin conexión")

    with pytest.raises(ErrorProveedorTasas):
        regla.evaluar(gasto(moneda="CLP"), empleado(), contexto(proveedor=ProveedorCaido()))


# --- En el motor completo -------------------------------------------------------------------


def test_esta_registrada_por_defecto() -> None:
    assert any(isinstance(r, ReglaConversionMoneda) for r in reglas_por_defecto())


@pytest.mark.parametrize(
    ("categoria", "dias", "estado", "codigos"),
    [
        # Antes: software sin límite + 5 días -> APROBADO sin alertas (el bug).
        ("software", 5, Estado.PENDIENTE, ["TASA_NO_DISPONIBLE"]),
        # Con límite: una sola alerta, no dos.
        ("food", 5, Estado.PENDIENTE, ["TASA_NO_DISPONIBLE"]),
        # La prioridad se mantiene: si otra regla rechaza, sigue rechazado.
        ("software", 90, Estado.RECHAZADO, ["LIMITE_ANTIGUEDAD", "TASA_NO_DISPONIBLE"]),
    ],
)
def test_motor_con_moneda_sin_tasa(
    categoria: str, dias: int, estado: Estado, codigos: list[str]
) -> None:
    resultado = MotorReglas(reglas_por_defecto()).evaluar(
        gasto(monto="50", moneda="JPY", categoria=categoria, dias=dias), empleado(), contexto()
    )
    assert resultado.estado is estado
    assert [a.codigo for a in resultado.alertas] == codigos
