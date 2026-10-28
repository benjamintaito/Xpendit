"""tareas.py: atajos de desarrollo multiplataforma."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import tareas

RAIZ = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("tarea", list(tareas.DESCRIPCIONES))
def test_cada_tarea_usa_el_interprete_actual(tarea: str) -> None:
    # Nunca "python3" ni ".venv/bin/python" fijos: en Windows no existen.
    for comando in tareas.comandos(tarea):
        assert comando[:2] == [sys.executable, "-m"]


def test_check_es_lint_mas_tipos_mas_tests() -> None:
    assert tareas.comandos("check") == (
        tareas.comandos("lint") + tareas.comandos("typecheck") + tareas.comandos("test")
    )


def test_analizar_reproduce_el_comando_del_readme() -> None:
    # El mismo argv que el comando del README: el comando escrito en ANALISIS.md no cambia.
    (comando,) = tareas.comandos("analizar")
    assert comando[2:] == [
        "xpendit",
        "analizar",
        "data/gastos_historicos.csv",
        "--fecha-referencia",
        "2026-10-26",
    ]


def test_analizar_offline_con_otra_fecha_y_salida() -> None:
    (comando,) = tareas.comandos("analizar-offline", fecha="2026-11-01", salida="x.md")
    assert comando[-5:] == ["--offline", "--fecha-referencia", "2026-11-01", "--salida", "x.md"]


def test_tarea_fallida_devuelve_su_codigo(monkeypatch: pytest.MonkeyPatch) -> None:
    ejecutados: list[list[str]] = []

    def run(comando: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        ejecutados.append(comando)
        return subprocess.CompletedProcess(comando, returncode=3 if "ruff" in comando else 0)

    monkeypatch.setattr(subprocess, "run", run)
    assert tareas.main(["check"]) == 3
    assert len(ejecutados) == 1  # se detiene en el primer comando que falla


def test_tarea_desconocida_falla_con_la_lista() -> None:
    proceso = subprocess.run(
        [sys.executable, str(RAIZ / "tareas.py"), "deploy"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proceso.returncode == 2
    assert "analizar-offline" in proceso.stderr
