from datetime import date
from decimal import Decimal

import pytest

from xpendit.domain.errores import TasasNoDisponibles
from xpendit.domain.tasas import ProveedorTasas, TasasPrecargadas

D1, D2 = date(2026, 1, 1), date(2026, 1, 2)


def test_devuelve_las_tasas_precargadas() -> None:
    t = TasasPrecargadas({D1: {"CLP": Decimal("900")}})
    assert t.obtener_tasas(D1) == {"CLP": Decimal("900")}
    assert isinstance(t, ProveedorTasas)


def test_fecha_no_precargada_lanza_error() -> None:
    with pytest.raises(TasasNoDisponibles):
        TasasPrecargadas({D1: {}}).obtener_tasas(D2)


def test_fecha_fallida_conserva_el_motivo() -> None:
    t = TasasPrecargadas({}, fallas={D2: "HTTP 503"})
    assert dict(t.fallas) == {D2: "HTTP 503"}
    with pytest.raises(TasasNoDisponibles, match="HTTP 503"):
        t.obtener_tasas(D2)


def test_es_inmutable_frente_al_diccionario_original() -> None:
    original = {"CLP": Decimal("900")}
    t = TasasPrecargadas({D1: original})
    original["CLP"] = Decimal("1")
    assert t.obtener_tasas(D1)["CLP"] == Decimal("900")
