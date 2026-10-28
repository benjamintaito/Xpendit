from pathlib import Path

import pytest

from xpendit.adapters.tasas import (
    ClienteOpenExchangeRates,
    ProveedorTasasConCache,
    ProveedorTasasFijas,
)
from xpendit.composicion import (
    construir_analizador,
    construir_fuente_tasas,
    leer_app_id,
    leer_timeout,
)
from xpendit.domain.errores import ConfiguracionInvalida


def test_offline_usa_tasas_fijas_sin_pedir_app_id() -> None:
    fuente = construir_fuente_tasas(offline=True, entorno={}, directorio_cache=None)
    assert isinstance(fuente.proveedor, ProveedorTasasFijas)
    assert fuente.offline and fuente.tasas_ejemplo and fuente.cliente is None


def test_modo_real_compone_cliente_con_cache(tmp_path: Path) -> None:
    fuente = construir_fuente_tasas(
        offline=False, entorno={"OXR_APP_ID": "abc123456789"}, directorio_cache=tmp_path
    )
    assert isinstance(fuente.proveedor, ProveedorTasasConCache)
    assert isinstance(fuente.cliente, ClienteOpenExchangeRates)
    assert not fuente.offline
    assert "abc123456789" not in fuente.descripcion


def test_directorio_de_cache_se_muestra_con_barra_normal() -> None:
    # En Windows Path(".cache") / "tasas" es ".cache\\tasas": el reporte debe decir lo mismo
    # en todos los sistemas (en la CI de Windows este test lo comprueba de verdad).
    fuente = construir_fuente_tasas(
        offline=False,
        entorno={"OXR_APP_ID": "abc123456789"},
        directorio_cache=Path(".cache") / "tasas",
    )
    assert fuente.descripcion.endswith(", con caché en disco en .cache/tasas")
    assert fuente.directorio_cache == ".cache/tasas"


@pytest.mark.parametrize("entorno", [{}, {"OXR_APP_ID": ""}, {"OXR_APP_ID": "   "}])
def test_sin_app_id_explica_como_configurarlo(entorno: dict[str, str]) -> None:
    with pytest.raises(ConfiguracionInvalida) as error:
        leer_app_id(entorno)
    mensaje = str(error.value)
    assert "OXR_APP_ID" in mensaje
    assert "openexchangerates.org" in mensaje
    assert ".env" in mensaje and "--offline" in mensaje
    assert "cp .env.example .env" in mensaje and "copy .env.example .env" in mensaje


def test_app_id_se_limpia_de_espacios() -> None:
    assert leer_app_id({"OXR_APP_ID": "  clave \n"}) == "clave"


@pytest.mark.parametrize(("valor", "esperado"), [(None, 10.0), ("", 10.0), ("2.5", 2.5)])
def test_timeout_desde_entorno(valor: str | None, esperado: float) -> None:
    entorno = {} if valor is None else {"OXR_TIMEOUT": valor}
    assert leer_timeout(entorno) == esperado


@pytest.mark.parametrize(
    "valor", ["0", "-1", "-0.5", "rapido", "NaN", "nan", "inf", "Infinity", "-inf", "1e999"]
)
def test_timeout_invalido(valor: str) -> None:
    with pytest.raises(ConfiguracionInvalida, match="OXR_TIMEOUT"):
        leer_timeout({"OXR_TIMEOUT": valor})


def test_construir_analizador() -> None:
    assert construir_analizador(ProveedorTasasFijas({})) is not None
