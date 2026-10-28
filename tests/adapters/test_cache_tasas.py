from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from xpendit.adapters.tasas import ProveedorTasasConCache
from xpendit.domain.errores import ErrorProveedorTasas
from xpendit.domain.tasas import ProveedorTasas

HOY = date(2026, 10, 26)
AYER = date(2026, 10, 25)


class ProveedorEspia:
    def __init__(self, fallar: bool = False) -> None:
        self.llamadas: list[date] = []
        self.fallar = fallar

    def obtener_tasas(self, fecha: date) -> Mapping[str, Decimal]:
        self.llamadas.append(fecha)
        if self.fallar:
            raise ErrorProveedorTasas("caído")
        return {"USD": Decimal("1"), "CLP": Decimal("900.5") + fecha.day}


def con_cache(espia: ProveedorEspia, directorio: Path | None = None) -> ProveedorTasasConCache:
    return ProveedorTasasConCache(espia, directorio, hoy=lambda: HOY)


def test_cumple_el_puerto() -> None:
    assert isinstance(con_cache(ProveedorEspia()), ProveedorTasas)


def test_memoiza_por_fecha_en_memoria() -> None:
    espia = ProveedorEspia()
    cache = con_cache(espia)
    primera = cache.obtener_tasas(AYER)
    segunda = cache.obtener_tasas(AYER)
    assert primera == segunda
    assert espia.llamadas == [AYER]


def test_fechas_distintas_se_consultan_por_separado() -> None:
    espia = ProveedorEspia()
    cache = con_cache(espia)
    cache.obtener_tasas(date(2026, 1, 1))
    cache.obtener_tasas(date(2026, 1, 2))
    cache.obtener_tasas(date(2026, 1, 1))
    assert espia.llamadas == [date(2026, 1, 1), date(2026, 1, 2)]


def test_persiste_en_disco_y_otra_instancia_no_vuelve_a_consultar(tmp_path: Path) -> None:
    con_cache(ProveedorEspia(), tmp_path).obtener_tasas(AYER)
    archivo = tmp_path / "2026-10-25.json"
    assert json.loads(archivo.read_text(encoding="utf-8"))["tasas"]["CLP"] == "925.5"

    espia = ProveedorEspia()
    cache = con_cache(espia, tmp_path)
    assert cache.obtener_tasas(AYER)["CLP"] == Decimal("925.5")
    assert espia.llamadas == []


@pytest.mark.parametrize("fecha", [HOY, date(2026, 12, 1)])
def test_no_persiste_el_dia_en_curso_ni_futuro(tmp_path: Path, fecha: date) -> None:
    cache = con_cache(ProveedorEspia(), tmp_path)
    cache.obtener_tasas(fecha)
    assert list(tmp_path.iterdir()) == []


# Con la fecha correcta, para que el archivo se descarte por las tasas y no por la fecha.
@pytest.mark.parametrize(
    "contenido",
    [
        "{no json",
        '{"fecha": "2026-10-25", "tasas": {}}',
        '{"fecha": "2026-10-25", "otro": 1}',
        '{"fecha": "2026-10-25", "tasas": {"CLP": "x"}}',
    ],
)
def test_cache_corrupta_se_ignora_y_se_reescribe(tmp_path: Path, contenido: str) -> None:
    (tmp_path / "2026-10-25.json").write_text(contenido, encoding="utf-8")
    espia = ProveedorEspia()
    assert con_cache(espia, tmp_path).obtener_tasas(AYER)["CLP"] == Decimal("925.5")
    assert espia.llamadas == [AYER]
    assert "925.5" in (tmp_path / "2026-10-25.json").read_text(encoding="utf-8")


def test_las_fallas_no_se_cachean() -> None:
    espia = ProveedorEspia(fallar=True)
    cache = con_cache(espia)
    for _ in range(2):
        with pytest.raises(ErrorProveedorTasas):
            cache.obtener_tasas(AYER)
    assert len(espia.llamadas) == 2


def test_error_de_escritura_no_es_fatal(tmp_path: Path) -> None:
    bloqueo = tmp_path / "archivo"
    bloqueo.write_text("no soy un directorio", encoding="utf-8")
    cache = con_cache(ProveedorEspia(), bloqueo / "sub")
    assert cache.obtener_tasas(AYER)["USD"] == Decimal("1")


def test_archivo_de_cache_es_identico_en_cualquier_sistema(tmp_path: Path) -> None:
    # Fin de línea LF también en Windows y un nombre sin ":" ni otros caracteres prohibidos.
    con_cache(ProveedorEspia(), tmp_path).obtener_tasas(AYER)
    (archivo,) = tmp_path.iterdir()
    assert archivo.name == "2026-10-25.json"
    assert archivo.read_bytes() == (
        b'{\n  "fecha": "2026-10-25",\n  "tasas": {\n    "CLP": "925.5",\n    "USD": "1"\n  }\n}'
    )


def test_si_falla_el_reemplazo_atomico_no_quedan_temporales(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # En Windows os.replace falla con PermissionError si otro proceso tiene abierto el destino.
    def reemplazo_bloqueado(origen: str, destino: str) -> None:
        raise PermissionError(13, "El proceso no tiene acceso al archivo", destino)

    monkeypatch.setattr(os, "replace", reemplazo_bloqueado)
    cache = con_cache(ProveedorEspia(), tmp_path)

    assert cache.obtener_tasas(AYER)["CLP"] == Decimal("925.5")
    assert list(tmp_path.iterdir()) == []
    assert "No se pudo escribir la caché" in caplog.text


@pytest.mark.parametrize(
    "tasas",
    [
        {"USD": "1", "CLP": "NaN"},
        {"USD": "1", "CLP": "0"},
        {"USD": "1", "CLP": "-1"},
        {"USD": "1", "CLP": "Infinity"},
        {"USD": "1", "CLP": "-Infinity"},
        {"USD": "1", "CLP": "sNaN"},
        {"USD": "1", "CLP": True},
        {"USD": "1", "CLP": None},
        {"USD": "1", "CL": "900"},  # código de 2 letras
        {"USD": "1", "CLPX": "900"},  # código de 4 letras
        {"USD": "1", "C1P": "900"},  # no son letras
        {"USD": "1", "clp": "900"},  # se escriben en mayúsculas: otra cosa es manipulación
    ],
)
def test_cache_con_tasas_invalidas_se_ignora_completa(
    tmp_path: Path, tasas: dict[str, object]
) -> None:
    contenido = json.dumps({"fecha": "2026-10-25", "tasas": tasas})
    (tmp_path / "2026-10-25.json").write_text(contenido, encoding="utf-8")
    espia = ProveedorEspia()
    cache = con_cache(espia, tmp_path)
    assert cache.obtener_tasas(AYER)["CLP"] == Decimal("925.5")
    assert espia.llamadas == [AYER]  # se volvió a consultar
    reescrita = json.loads((tmp_path / "2026-10-25.json").read_text(encoding="utf-8"))
    assert reescrita["tasas"] == {"CLP": "925.5", "USD": "1"}


@pytest.mark.parametrize(
    "contenido",
    ['{"tasas": {"CLP": "900"', "", "null", "[]", '{"fecha": "2026-10-25", "tasas": []}'],
)
def test_cache_con_json_roto_se_ignora(tmp_path: Path, contenido: str) -> None:
    (tmp_path / "2026-10-25.json").write_text(contenido, encoding="utf-8")
    espia = ProveedorEspia()
    assert con_cache(espia, tmp_path).obtener_tasas(AYER)["CLP"] == Decimal("925.5")
    assert espia.llamadas == [AYER]


@pytest.mark.parametrize(
    "contenido",
    [
        {"fecha": "2026-10-24", "tasas": {"USD": "1", "CLP": "999"}},  # copia de otro día
        {"tasas": {"USD": "1", "CLP": "999"}},  # sin fecha
        {"fecha": None, "tasas": {"USD": "1", "CLP": "999"}},
        {"fecha": "25-10-2026", "tasas": {"USD": "1", "CLP": "999"}},  # otro formato
    ],
)
def test_cache_con_fecha_discordante_o_sin_fecha_se_ignora(
    tmp_path: Path, contenido: dict[str, object]
) -> None:
    # Las tasas son válidas en lo numérico, pero no hay cómo saber que son las del día pedido.
    (tmp_path / "2026-10-25.json").write_text(json.dumps(contenido), encoding="utf-8")
    espia = ProveedorEspia()
    cache = con_cache(espia, tmp_path)
    assert cache.obtener_tasas(AYER)["CLP"] == Decimal("925.5")
    assert espia.llamadas == [AYER]  # se volvió a consultar
    reescrita = json.loads((tmp_path / "2026-10-25.json").read_text(encoding="utf-8"))
    assert reescrita == {"fecha": "2026-10-25", "tasas": {"CLP": "925.5", "USD": "1"}}


def test_cache_valida_con_enteros_y_decimales_se_usa(tmp_path: Path) -> None:
    contenido = json.dumps(
        {"fecha": "2026-10-25", "tasas": {"USD": 1, "CLP": "950.123456", "EUR": 0.92}}
    )
    (tmp_path / "2026-10-25.json").write_text(contenido, encoding="utf-8")
    espia = ProveedorEspia()
    tasas = con_cache(espia, tmp_path).obtener_tasas(AYER)
    assert tasas == {"USD": Decimal("1"), "CLP": Decimal("950.123456"), "EUR": Decimal("0.92")}
    assert espia.llamadas == []
