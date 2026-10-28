from datetime import date
from decimal import Decimal

import pytest

from xpendit.adapters.tasas import TASAS_EJEMPLO_USD, ProveedorTasasFijas
from xpendit.domain.errores import TasasNoDisponibles
from xpendit.domain.tasas import ProveedorTasas

D1, D2 = date(2026, 1, 1), date(2026, 1, 2)


def test_cumple_el_puerto() -> None:
    assert isinstance(ProveedorTasasFijas({}), ProveedorTasas)


def test_tasas_por_defecto_para_cualquier_fecha() -> None:
    p = ProveedorTasasFijas({"USD": Decimal("1")})
    assert p.obtener_tasas(D1) == {"USD": Decimal("1")}
    assert p.obtener_tasas(D2) == {"USD": Decimal("1")}


def test_tasas_por_fecha_tienen_prioridad() -> None:
    p = ProveedorTasasFijas({"CLP": Decimal("900")}, por_fecha={D1: {"CLP": Decimal("950")}})
    assert p.obtener_tasas(D1)["CLP"] == Decimal("950")
    assert p.obtener_tasas(D2)["CLP"] == Decimal("900")


def test_sin_tasas_para_la_fecha_lanza_error() -> None:
    p = ProveedorTasasFijas(por_fecha={D1: {"USD": Decimal("1")}})
    with pytest.raises(TasasNoDisponibles, match="2026-01-02"):
        p.obtener_tasas(D2)


def test_no_expone_su_estado_interno_para_mutacion() -> None:
    p = ProveedorTasasFijas({"USD": Decimal("1")})
    with pytest.raises(TypeError):
        p.obtener_tasas(D1)["USD"] = Decimal("2")  # type: ignore[index]


def test_tasas_de_ejemplo_incluyen_las_monedas_del_csv() -> None:
    assert {"USD", "CLP", "MXN", "EUR"} <= set(TASAS_EJEMPLO_USD)
