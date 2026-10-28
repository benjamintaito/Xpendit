"""Exportación de resultados por gasto a JSON y CSV."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from xpendit.application.lote import ReporteLote


def a_json(reporte: ReporteLote) -> dict[str, Any]:
    return {
        "fecha_referencia": reporte.fecha_referencia.isoformat(),
        "resumen": {estado.value: n for estado, n in reporte.conteo_por_estado().items()},
        "resultados": [r.validacion.a_dict() for r in reporte.resultados],
        "filas_invalidas": [
            {"linea": f.numero_linea, "gasto_id": f.gasto_id, "motivo": f.motivo}
            for f in reporte.filas_invalidas
        ],
    }


def escribir_json(reporte: ReporteLote, ruta: Path) -> None:
    ruta.write_text(
        json.dumps(a_json(reporte), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",  # LF también en Windows
    )


def escribir_csv(reporte: ReporteLote, ruta: Path) -> None:
    # newline="": el módulo csv escribe sus propios fines de línea (CRLF, RFC 4180) y así no
    # se duplican como "\r\r\n" en Windows. El resultado es igual en todos los sistemas.
    with ruta.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(["gasto_id", "status", "codigos", "mensajes"])
        for r in reporte.resultados:
            alertas = r.validacion.alertas
            escritor.writerow(
                [
                    r.validacion.gasto_id,
                    r.estado.value,
                    "|".join(a.codigo for a in alertas),
                    " | ".join(a.mensaje for a in alertas),
                ]
            )
