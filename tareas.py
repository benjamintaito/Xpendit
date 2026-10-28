"""Atajos de desarrollo con solo la biblioteca estándar: funcionan en Windows, macOS y Linux.

Uso (con el entorno virtual activado)::

    python tareas.py test
    python tareas.py check
    python tareas.py analizar-offline --fecha 2026-10-26 --salida mi_analisis.md

Usa el mismo intérprete con que se ejecuta (``sys.executable``) y solo la biblioteca
estándar. ``python tareas.py --help`` lista las tareas.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
FECHA = "2026-10-26"
CSV = "data/gastos_historicos.csv"
SALIDA = "ANALISIS.md"

DESCRIPCIONES = {
    "install": "Instala dependencias de ejecución y desarrollo (+ el paquete en modo editable)",
    "test": "Corre la suite de tests (sin salir a Internet)",
    "cov": "Tests con reporte de cobertura",
    "lint": "ruff: lint y formato (solo verifica)",
    "format": "ruff: aplica formato y correcciones automáticas",
    "typecheck": "mypy --strict sobre src/ y tareas.py",
    "check": "Todo lo que corre la CI: lint, tipos y tests",
    "analizar-offline": "Genera el reporte con tasas de ejemplo (sin API key)",
    "analizar": "Genera el reporte con la API real (requiere OXR_APP_ID en .env)",
}


def comandos(
    tarea: str, *, fecha: str = FECHA, csv: str = CSV, salida: str = SALIDA
) -> list[list[str]]:
    """Comandos que ejecuta una tarea, en orden (se detiene en el primero que falla)."""
    py = [sys.executable, "-m"]
    analizar = [*py, "xpendit", "analizar", csv]
    # --salida solo si cambia: así el comando que queda escrito en el reporte es el mismo
    # que el del README.
    fecha_y_salida = ["--fecha-referencia", fecha]
    if salida != SALIDA:
        fecha_y_salida += ["--salida", salida]
    por_tarea = {
        "install": [[*py, "pip", "install", "-r", "requirements-dev.txt"]],
        "test": [[*py, "pytest", "-q"]],
        "cov": [[*py, "pytest", "--cov"]],
        "lint": [[*py, "ruff", "check", "."], [*py, "ruff", "format", "--check", "."]],
        "format": [[*py, "ruff", "format", "."], [*py, "ruff", "check", "--fix", "."]],
        "typecheck": [[*py, "mypy"]],
        "analizar-offline": [[*analizar, "--offline", *fecha_y_salida]],
        "analizar": [[*analizar, *fecha_y_salida]],
    }
    por_tarea["check"] = por_tarea["lint"] + por_tarea["typecheck"] + por_tarea["test"]
    return por_tarea[tarea]


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python tareas.py",
        description="Atajos de desarrollo (Windows, macOS y Linux).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="tareas:\n"
        + "\n".join(f"  {nombre:<18} {texto}" for nombre, texto in DESCRIPCIONES.items()),
    )
    parser.add_argument("tarea", choices=DESCRIPCIONES, metavar="TAREA", help="ver la lista")
    parser.add_argument("--fecha", default=FECHA, help=f"fecha de referencia (por defecto {FECHA})")
    parser.add_argument("--csv", default=CSV, help=f"CSV de gastos (por defecto {CSV})")
    parser.add_argument("--salida", default=SALIDA, help=f"reporte (por defecto {SALIDA})")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    for comando in comandos(args.tarea, fecha=args.fecha, csv=args.csv, salida=args.salida):
        print("$ " + " ".join(["python", *comando[1:]]), flush=True)
        codigo = subprocess.run(comando, cwd=RAIZ, check=False).returncode
        if codigo != 0:
            return codigo
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
