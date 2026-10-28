from decimal import Decimal
from pathlib import Path

import pytest

from xpendit.adapters.politica_json import cargar_politica
from xpendit.domain.errores import PoliticaInvalida

POLITICA_REPO = Path(__file__).resolve().parents[2] / "config" / "politica.json"


def test_carga_la_politica_del_repositorio() -> None:
    pol = cargar_politica(POLITICA_REPO)
    assert pol.moneda_base == "USD"
    assert pol.limites_por_categoria["food"].aprobado_hasta == Decimal("100")


def test_decimales_del_json_no_pasan_por_float(tmp_path: Path) -> None:
    ruta = tmp_path / "p.json"
    ruta.write_text(
        '{"moneda_base": "USD", "limites_por_categoria": '
        '{"food": {"aprobado_hasta": 100.10, "pendiente_hasta": 150.30}}}',
        encoding="utf-8",
    )
    assert cargar_politica(ruta).limites_por_categoria["food"].pendiente_hasta == Decimal("150.30")


def test_archivo_inexistente(tmp_path: Path) -> None:
    with pytest.raises(PoliticaInvalida, match="No existe"):
        cargar_politica(tmp_path / "nada.json")


def test_json_invalido_indica_linea(tmp_path: Path) -> None:
    ruta = tmp_path / "p.json"
    # Un valor sin comillas, y no una coma final: Python 3.13 cambió la línea en que
    # señala la coma, y el test debe dar igual en 3.12 y en 3.13+.
    ruta.write_text('{\n  "moneda_base": USD\n}', encoding="utf-8")
    with pytest.raises(PoliticaInvalida, match=r"no es JSON válido \(línea 2, columna 18\)"):
        cargar_politica(ruta)


def test_esquema_invalido_incluye_la_ruta_del_archivo(tmp_path: Path) -> None:
    ruta = tmp_path / "p.json"
    ruta.write_text('{"moneda_base": "dolares"}', encoding="utf-8")
    with pytest.raises(PoliticaInvalida) as error:
        cargar_politica(ruta)
    assert str(ruta) in str(error.value) and "moneda_base" in str(error.value)


def test_directorio_en_vez_de_archivo(tmp_path: Path) -> None:
    with pytest.raises(PoliticaInvalida, match="No se pudo leer"):
        cargar_politica(tmp_path)
