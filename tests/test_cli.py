"""Pruebas de punta a punta de la CLI (sin red)."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from xpendit import cli

RAIZ = Path(__file__).resolve().parents[1]
CSV = RAIZ / "data" / "gastos_historicos.csv"
POLITICA = RAIZ / "config" / "politica.json"
# La función real: el fixture de abajo la reemplaza en el módulo para no leer un .env real.
CARGAR_DOTENV = cli.cargar_dotenv


@pytest.fixture(autouse=True)
def entorno_aislado(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Sin API key, sin .env real y con el directorio de trabajo en un tmp."""
    monkeypatch.delenv("OXR_APP_ID", raising=False)
    monkeypatch.setattr(cli, "cargar_dotenv", lambda: None)
    monkeypatch.chdir(tmp_path)


def analizar(*extra: str) -> list[str]:
    return ["analizar", str(CSV), "--politica", str(POLITICA), *extra]


def test_offline_genera_reporte_y_exportaciones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    salida, js, cs = tmp_path / "A.md", tmp_path / "r.json", tmp_path / "r.csv"
    codigo = cli.main(
        analizar(
            "--offline",
            "--fecha-referencia",
            "2026-10-26",
            "--salida",
            str(salida),
            "--json",
            str(js),
            "--csv-salida",
            str(cs),
        )
    )
    assert codigo == 0
    md = salida.read_text(encoding="utf-8")
    assert md.startswith("# Análisis del lote de gastos históricos")
    assert "| **RECHAZADO** | 25 |" in md
    assert json.loads(js.read_text(encoding="utf-8"))["resumen"] == {
        "APROBADO": 8,
        "PENDIENTE": 17,
        "RECHAZADO": 25,
    }
    assert cs.exists()
    out = capsys.readouterr().out
    assert "APROBADO   8" in out and "25 fechas únicas, 9 consultas" in out
    assert "modo offline" in out


def test_fin_de_linea_de_las_salidas_no_depende_del_sistema(tmp_path: Path) -> None:
    # En Linux pasa de todos modos; en la CI de Windows comprueba que no se traduce a CRLF.
    salida, js, cs = tmp_path / "A.md", tmp_path / "r.json", tmp_path / "r.csv"
    argumentos = ["--offline", "--fecha-referencia", "2026-10-26", "--salida", str(salida)]
    assert cli.main(analizar(*argumentos, "--json", str(js), "--csv-salida", str(cs))) == 0
    for ruta in (salida, js):
        contenido = ruta.read_bytes()
        assert b"\r" not in contenido
        assert contenido.endswith(b"\n")
    # El CSV usa CRLF (RFC 4180, lo que espera Excel), sin la doble traducción "\r\r\n".
    filas = cs.read_bytes().split(b"\r\n")
    assert filas[0] == b"gasto_id,status,codigos,mensajes"
    assert len(filas) == 52 and filas[-1] == b""  # encabezado + 50 + vacío final
    assert all(b"\r" not in f and b"\n" not in f for f in filas)


@pytest.mark.parametrize(
    ("texto", "sep", "esperado"),
    [
        ("data\\gastos_historicos.csv", "\\", "data/gastos_historicos.csv"),
        ("C:\\Users\\ana\\A.md", "\\", "C:/Users/ana/A.md"),
        ("data/gastos_historicos.csv", "\\", "data/gastos_historicos.csv"),
        ("--fecha-referencia", "\\", "--fecha-referencia"),
        # En macOS/Linux "\" es un carácter válido de un nombre: no se toca.
        ("raro\\nombre.csv", "/", "raro\\nombre.csv"),
    ],
)
def test_ruta_portable(texto: str, sep: str, esperado: str) -> None:
    assert cli.ruta_portable(texto, sep) == esperado


@pytest.mark.skipif(os.name != "nt", reason="solo Windows escribe rutas con barra invertida")
def test_en_windows_el_reporte_muestra_las_rutas_con_barra_normal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(RAIZ)
    salida = tmp_path / "A.md"
    argumentos = ["analizar", "data\\gastos_historicos.csv", "--politica", "config\\politica.json"]
    assert cli.main([*argumentos, "--offline", "--salida", str(salida)]) == 0
    md = salida.read_text(encoding="utf-8")
    assert (
        "python -m xpendit analizar data/gastos_historicos.csv --politica config/politica.json"
        in md
    )
    assert "| Archivo de gastos | `data/gastos_historicos.csv` |" in md
    assert "\\" not in md.splitlines()[2]


def test_salida_por_defecto_es_analisis_md_en_el_directorio_actual(tmp_path: Path) -> None:
    assert cli.main(analizar("--offline", "--fecha-referencia", "2026-10-26")) == 0
    assert (tmp_path / "ANALISIS.md").exists()


def test_sin_fecha_de_referencia_usa_hoy_y_lo_deja_explicito(tmp_path: Path) -> None:
    assert cli.main(analizar("--offline")) == 0
    md = (tmp_path / "ANALISIS.md").read_text(encoding="utf-8")
    assert "--fecha-referencia" in md.splitlines()[2]


def test_sin_app_id_y_sin_offline_falla_con_mensaje_claro(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    codigo = cli.main(analizar("--fecha-referencia", "2026-10-26"))
    assert codigo == 2
    err = capsys.readouterr().err
    assert err.startswith("Error: No se encontró la variable de entorno OXR_APP_ID")
    assert "Traceback" not in err
    assert "--offline" in err
    assert not (tmp_path / "ANALISIS.md").exists()


def test_politica_invalida_falla_sin_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mala = tmp_path / "p.json"
    mala.write_text('{"moneda_base": 1}', encoding="utf-8")
    codigo = cli.main(["analizar", str(CSV), "--politica", str(mala), "--offline"])
    assert codigo == 2
    assert "moneda_base" in capsys.readouterr().err


def test_csv_inexistente_falla_sin_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    codigo = cli.main(["analizar", "no_existe.csv", "--politica", str(POLITICA), "--offline"])
    assert codigo == 2
    assert "No existe el archivo de gastos" in capsys.readouterr().err


def test_no_se_puede_escribir_la_salida(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    codigo = cli.main(analizar("--offline", "--salida", str(tmp_path / "no" / "existe.md")))
    assert codigo == 2
    assert "No se pudo escribir" in capsys.readouterr().err


def test_fecha_de_referencia_invalida(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as salida:
        cli.main(analizar("--offline", "--fecha-referencia", "26/10/2026"))
    assert salida.value.code == 2
    assert "fecha inválida" in capsys.readouterr().err


def test_sin_comando_muestra_ayuda(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 2
    assert "analizar" in capsys.readouterr().err


def test_modulo_ejecutable_con_python_m(tmp_path: Path) -> None:
    entorno = {k: v for k, v in os.environ.items() if k != "OXR_APP_ID"}
    proceso = subprocess.run(
        [
            sys.executable,
            "-m",
            "xpendit",
            *analizar("--offline", "--fecha-referencia", "2026-10-26"),
        ],
        cwd=tmp_path,
        env=entorno,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proceso.returncode == 0, proceso.stderr
    assert (tmp_path / "ANALISIS.md").exists()


@pytest.mark.parametrize("codificacion", ["cp1252", "cp850", "ascii"])
def test_consola_que_no_es_utf8_no_hace_fallar_la_cli(tmp_path: Path, codificacion: str) -> None:
    # Simula una consola Windows antigua (o la salida redirigida) con una ruta cuyo nombre
    # no cabe en esa página de códigos: antes terminaba con UnicodeEncodeError.
    carpeta = tmp_path / "usuario_Ζωή→"
    carpeta.mkdir()
    entorno = {k: v for k, v in os.environ.items() if k not in ("OXR_APP_ID", "PYTHONUTF8")}
    entorno["PYTHONIOENCODING"] = codificacion
    proceso = subprocess.run(
        [
            sys.executable,
            "-m",
            "xpendit",
            *analizar("--offline", "--fecha-referencia", "2026-10-26"),
            "--salida",
            str(carpeta / "ANALISIS.md"),
        ],
        cwd=tmp_path,
        env=entorno,
        capture_output=True,
        check=False,
    )
    stdout = proceso.stdout.decode("utf-8")
    assert proceso.returncode == 0, proceso.stderr.decode("utf-8", errors="replace")
    assert "Traceback" not in proceso.stderr.decode("utf-8", errors="replace")
    assert "fechas únicas" in stdout
    assert "usuario_Ζωή→" in stdout


def test_configurar_consola_pasa_a_utf8_un_flujo_cp1252(monkeypatch: pytest.MonkeyPatch) -> None:
    crudo = io.BytesIO()
    flujo = io.TextIOWrapper(crudo, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", flujo)

    cli.configurar_consola()
    print("Reporte — 25 fechas únicas → Ζωή")
    flujo.flush()

    assert flujo.encoding == "utf-8" and flujo.errors == "replace"
    # El flujo traduce "\n" al fin de línea del sistema: "\r\n" en Windows.
    assert crudo.getvalue().decode("utf-8") == f"Reporte — 25 fechas únicas → Ζωή{os.linesep}"


def test_configurar_consola_no_toca_flujos_utf8_ni_reemplazados(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    utf8 = io.TextIOWrapper(io.BytesIO(), encoding="UTF8")
    texto = io.StringIO()
    monkeypatch.setattr(sys, "stdout", utf8)
    monkeypatch.setattr(sys, "stderr", texto)

    cli.configurar_consola()

    assert utf8.errors == "strict"  # ya era UTF-8: se respeta tal cual
    assert sys.stderr is texto


# --- .env guardado en Windows ------------------------------------------------------------
# Los archivos se llaman "prueba.env" en un tmp: nunca se toca un .env real.


@pytest.mark.parametrize(
    "contenido",
    [
        "\ufeffOXR_APP_ID=desde-bom\n".encode(),  # Bloc de notas: "UTF-8 con BOM"
        "\ufeff# comentario\r\nOXR_APP_ID=desde-bom\r\n".encode(),  # BOM y CRLF
    ],
)
def test_env_con_bom_y_crlf_se_lee(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contenido: bytes
) -> None:
    monkeypatch.setenv("OXR_APP_ID", "")
    monkeypatch.delenv("OXR_APP_ID")  # así el teardown también borra lo que cargue dotenv
    ruta = tmp_path / "prueba.env"
    ruta.write_bytes(contenido)
    CARGAR_DOTENV(str(ruta))
    assert os.environ["OXR_APP_ID"] == "desde-bom"


def test_env_en_utf16_falla_con_mensaje_claro(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Lo que deja `echo OXR_APP_ID=... > .env` en Windows PowerShell 5.1.
    ruta = tmp_path / "prueba.env"
    ruta.write_bytes("OXR_APP_ID=abc\r\n".encode("utf-16"))
    monkeypatch.setattr(cli, "cargar_dotenv", lambda: CARGAR_DOTENV(str(ruta)))
    assert cli.main(analizar("--offline", "--fecha-referencia", "2026-10-26")) == 2
    err = capsys.readouterr().err
    assert "no está guardado en UTF-8" in err and "Traceback" not in err
