from datetime import date
from decimal import Decimal

import pytest

from tests.factories import TASAS_PRUEBA, contexto, empleado, gasto, politica
from xpendit.adapters.tasas import ProveedorTasasFijas
from xpendit.domain import ContextoEvaluacion, Estado, ResultadoRegla
from xpendit.domain.errores import ErrorProveedorTasas
from xpendit.domain.reglas import ReglaLimiteCategoria

regla = ReglaLimiteCategoria()


def evaluar(
    monto: str, categoria: str = "food", moneda: str = "USD", ctx: ContextoEvaluacion | None = None
) -> ResultadoRegla:
    g = gasto(monto=monto, moneda=moneda, categoria=categoria)
    resultado = regla.evaluar(g, empleado(), ctx or contexto())
    assert resultado is not None
    return resultado


@pytest.mark.parametrize(
    ("monto", "esperado"),
    [
        ("0.01", Estado.APROBADO),
        ("99.99", Estado.APROBADO),
        ("100", Estado.APROBADO),  # borde: aprobado_hasta es inclusivo
        ("100.00", Estado.APROBADO),
        ("100.01", Estado.PENDIENTE),  # primer centavo sobre el límite
        ("120", Estado.PENDIENTE),
        ("150", Estado.PENDIENTE),  # borde: pendiente_hasta es inclusivo
        ("150.01", Estado.RECHAZADO),
        ("1000", Estado.RECHAZADO),
    ],
)
def test_food_en_usd_segun_monto(monto: str, esperado: Estado) -> None:
    assert evaluar(monto).estado is esperado


def test_aprobado_no_genera_alertas() -> None:
    assert evaluar("100").alertas == ()


def test_pendiente_alerta_requiere_revision() -> None:
    (alerta,) = evaluar("120").alertas
    assert alerta.codigo == "LIMITE_CATEGORIA"
    assert alerta.mensaje.startswith("Requiere revisión")
    assert (
        "120 USD" in alerta.mensaje and "100 USD" in alerta.mensaje and "'food'" in alerta.mensaje
    )


def test_rechazado_alerta_excede_limite_aprobado() -> None:
    (alerta,) = evaluar("160").alertas
    assert alerta.codigo == "LIMITE_CATEGORIA"
    assert alerta.mensaje.startswith("Excede límite aprobado")
    assert "150 USD" in alerta.mensaje


@pytest.mark.parametrize(
    ("monto", "esperado"),
    [
        ("199.99", Estado.APROBADO),
        ("200", Estado.APROBADO),
        ("200.01", Estado.RECHAZADO),  # aprobado_hasta == pendiente_hasta: no hay tramo pendiente
        ("500", Estado.RECHAZADO),
    ],
)
def test_transport_sin_tramo_pendiente(monto: str, esperado: Estado) -> None:
    assert evaluar(monto, categoria="transport").estado is esperado


@pytest.mark.parametrize("categoria", ["software", "lodging", "other"])
def test_categoria_sin_limite_no_aplica(categoria: str) -> None:
    g = gasto(monto="999999", categoria=categoria)
    assert regla.evaluar(g, empleado(), contexto()) is None


@pytest.mark.parametrize(
    ("monto", "estado"),
    [
        ("50", Estado.APROBADO),
        ("50.01", Estado.PENDIENTE),
        ("80", Estado.PENDIENTE),
        ("80.01", Estado.RECHAZADO),
    ],
)
def test_es_generica_para_cualquier_categoria_configurada(monto: str, estado: Estado) -> None:
    pol = politica(limites_por_categoria={"lodging": {"aprobado_hasta": 50, "pendiente_hasta": 80}})
    assert evaluar(monto, categoria="lodging", ctx=contexto(pol=pol)).estado is estado


# --- Conversión a la moneda base (CLP a 900 por USD en las tasas de prueba) -----------


@pytest.mark.parametrize(
    ("monto_clp", "esperado"),
    [
        ("90000", Estado.APROBADO),  # 100.00 USD
        ("90004", Estado.APROBADO),  # 100.0044 -> 100.00 USD (redondeo a centavos)
        ("90005", Estado.PENDIENTE),  # 100.0056 -> 100.01 USD
        ("135000", Estado.PENDIENTE),  # 150.00 USD
        ("135009", Estado.RECHAZADO),  # 150.01 USD
    ],
)
def test_compara_el_monto_convertido_a_moneda_base(monto_clp: str, esperado: Estado) -> None:
    assert evaluar(monto_clp, moneda="CLP").estado is esperado


def test_un_monto_chico_en_moneda_local_no_se_compara_sin_convertir() -> None:
    # 120 CLP son ~0.13 USD: aprobado, aunque "120" > 100 sin convertir.
    assert evaluar("120", moneda="CLP").estado is Estado.APROBADO


def test_mensaje_muestra_el_monto_convertido() -> None:
    (alerta,) = evaluar("126000", moneda="CLP").alertas
    assert "140.00 USD" in alerta.mensaje


def test_moneda_base_distinta_de_usd() -> None:
    # Límite en EUR; 92 USD = 84.64 EUR (aprobado), 120 USD = 110.40 EUR (pendiente).
    pol = politica(moneda_base="EUR")
    assert evaluar("92", ctx=contexto(pol=pol)).estado is Estado.APROBADO
    assert evaluar("120", ctx=contexto(pol=pol)).estado is Estado.PENDIENTE


def test_usa_la_tasa_de_la_fecha_del_gasto() -> None:
    proveedor = ProveedorTasasFijas(
        por_fecha={
            date(2026, 10, 1): {"USD": Decimal("1"), "CLP": Decimal("1000")},
            date(2026, 10, 2): {"USD": Decimal("1"), "CLP": Decimal("500")},
        }
    )
    ctx = contexto(proveedor=proveedor)
    g1 = gasto(monto="100000", moneda="CLP", categoria="food", fecha=date(2026, 10, 1))
    g2 = gasto(monto="100000", moneda="CLP", categoria="food", fecha=date(2026, 10, 2))
    r1, r2 = regla.evaluar(g1, empleado(), ctx), regla.evaluar(g2, empleado(), ctx)
    assert r1 is not None and r1.estado is Estado.APROBADO  # 100 USD
    assert r2 is not None and r2.estado is Estado.RECHAZADO  # 200 USD


# La falta de tasa la reporta ReglaConversionMoneda (una sola alerta, cualquier categoría);
# sin monto en moneda base, el límite no tiene nada que comparar.


def test_moneda_sin_tasa_la_regla_no_aplica() -> None:
    g = gasto(monto="5000", moneda="JPY", categoria="food")
    assert regla.evaluar(g, empleado(), contexto()) is None


def test_fecha_sin_tasas_la_regla_no_aplica() -> None:
    ctx = contexto(proveedor=ProveedorTasasFijas(por_fecha={}))
    g = gasto(monto="5000", moneda="CLP", categoria="food")
    assert regla.evaluar(g, empleado(), ctx) is None


def test_gasto_en_moneda_base_no_necesita_tasas() -> None:
    ctx = contexto(proveedor=ProveedorTasasFijas(por_fecha={}))
    assert evaluar("120", ctx=ctx).estado is Estado.PENDIENTE


def test_falla_de_infraestructura_no_se_oculta_como_regla() -> None:
    class ProveedorCaido:
        def obtener_tasas(self, fecha: date) -> dict[str, Decimal]:
            raise ErrorProveedorTasas("sin conexión")

    with pytest.raises(ErrorProveedorTasas):
        evaluar("100", moneda="CLP", ctx=contexto(proveedor=ProveedorCaido()))


def test_tasas_de_prueba_son_las_esperadas() -> None:
    # Protege a los tests de arriba contra cambios accidentales del fixture.
    assert TASAS_PRUEBA["CLP"] == Decimal("900")
