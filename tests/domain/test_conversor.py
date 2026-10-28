"""Conversor con tasas cruzadas: monto_destino = monto / tasa[origen] * tasa[destino]."""

from datetime import date
from decimal import Decimal

import pytest

from tests.factories import TASAS_PRUEBA
from xpendit.adapters.tasas import ProveedorTasasFijas
from xpendit.domain import ConversorMoneda
from xpendit.domain.errores import ConversionNoDisponible, MonedaNoSoportada, TasasNoDisponibles
from xpendit.domain.tasas import TasasPrecargadas

FECHA = date(2026, 9, 1)
conversor = ConversorMoneda(ProveedorTasasFijas(TASAS_PRUEBA))


@pytest.mark.parametrize(
    ("monto", "origen", "destino", "esperado"),
    [
        ("90000", "CLP", "USD", "100.00"),  # 90000 / 900
        ("81000", "CLP", "USD", "90.00"),
        ("1750", "MXN", "USD", "100.00"),  # 1750 / 17.5
        ("2100", "MXN", "USD", "120.00"),
        ("92", "EUR", "USD", "100.00"),  # 92 / 0.92
        ("130", "EUR", "USD", "141.30"),  # 141.3043... redondeado a centavos
        ("100", "USD", "CLP", "90000.00"),
        # Base distinta de USD: cruce a través del pivote USD.
        ("90000", "CLP", "EUR", "92.00"),  # 90000 / 900 * 0.92
        ("1750", "MXN", "EUR", "92.00"),
        ("100", "EUR", "MXN", "1902.17"),  # 100 / 0.92 * 17.5 = 1902.1739...
    ],
)
def test_conversion_con_tasas_cruzadas(
    monto: str, origen: str, destino: str, esperado: str
) -> None:
    assert conversor.convertir(Decimal(monto), origen, destino, FECHA) == Decimal(esperado)


def test_redondeo_half_up_a_centavos() -> None:
    proveedor = ProveedorTasasFijas({"USD": Decimal("1"), "XXX": Decimal("8")})
    c = ConversorMoneda(proveedor)
    assert c.convertir(Decimal("0.04"), "XXX", "USD", FECHA) == Decimal("0.01")  # 0.005 -> 0.01
    assert c.convertir(Decimal("0.03"), "XXX", "USD", FECHA) == Decimal("0.00")  # 0.00375 -> 0.00


def test_misma_moneda_devuelve_el_monto_sin_consultar_proveedor() -> None:
    c = ConversorMoneda(ProveedorTasasFijas(por_fecha={}))  # sin tasas: fallaría si consultara
    assert c.convertir(Decimal("123.456"), "USD", "usd", FECHA) == Decimal("123.456")


def test_codigos_en_minusculas_se_normalizan() -> None:
    assert conversor.convertir(Decimal("90000"), "clp", "usd", FECHA) == Decimal("100.00")


@pytest.mark.parametrize(("origen", "destino"), [("JPY", "USD"), ("USD", "JPY")])
def test_moneda_ausente_lanza_moneda_no_soportada(origen: str, destino: str) -> None:
    with pytest.raises(MonedaNoSoportada) as error:
        conversor.convertir(Decimal("1"), origen, destino, FECHA)
    assert error.value.moneda == "JPY"
    assert isinstance(error.value, ConversionNoDisponible)


def test_tasa_cero_se_trata_como_no_soportada() -> None:
    c = ConversorMoneda(ProveedorTasasFijas({"USD": Decimal("1"), "CLP": Decimal("0")}))
    with pytest.raises(MonedaNoSoportada):
        c.convertir(Decimal("1"), "CLP", "USD", FECHA)


def test_fecha_sin_tasas_lanza_tasas_no_disponibles() -> None:
    c = ConversorMoneda(TasasPrecargadas({}, fallas={FECHA: "HTTP 503"}))
    with pytest.raises(TasasNoDisponibles, match="HTTP 503"):
        c.convertir(Decimal("1"), "CLP", "USD", FECHA)


def test_consulta_las_tasas_de_la_fecha_indicada() -> None:
    proveedor = ProveedorTasasFijas(
        por_fecha={
            date(2026, 1, 1): {"USD": Decimal("1"), "CLP": Decimal("800")},
            date(2026, 1, 2): {"USD": Decimal("1"), "CLP": Decimal("1000")},
        }
    )
    c = ConversorMoneda(proveedor)
    assert c.convertir(Decimal("8000"), "CLP", "USD", date(2026, 1, 1)) == Decimal("10.00")
    assert c.convertir(Decimal("8000"), "CLP", "USD", date(2026, 1, 2)) == Decimal("8.00")
