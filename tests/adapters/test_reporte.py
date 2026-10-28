"""Reporte Markdown, exportación JSON/CSV y consultas de hallazgos."""

from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tests.factories import TASAS_PRUEBA, empleado, gasto, politica
from xpendit.adapters.csv_gastos import LectorCsvGastos
from xpendit.adapters.politica_json import cargar_politica
from xpendit.adapters.reporte.exportar import a_json, escribir_csv, escribir_json
from xpendit.adapters.reporte.markdown import MetadatosReporte, generar_markdown
from xpendit.adapters.tasas import TASAS_EJEMPLO_USD, ProveedorTasasFijas
from xpendit.application import AnalizarLote, LoteLeido, RegistroGasto, ReporteLote, hallazgos
from xpendit.domain import Estado, MotorReglas, reglas_por_defecto
from xpendit.domain.anomalias import detectores_por_defecto
from xpendit.domain.errores import FilaInvalida

RAIZ = Path(__file__).resolve().parents[2]
REFERENCIA = date(2026, 10, 26)


def reporte_real() -> ReporteLote:
    caso = AnalizarLote(
        MotorReglas(reglas_por_defecto()),
        ProveedorTasasFijas(TASAS_EJEMPLO_USD),
        detectores_por_defecto(),
    )
    return caso.ejecutar(
        LectorCsvGastos(RAIZ / "data" / "gastos_historicos.csv"),
        cargar_politica(RAIZ / "config" / "politica.json"),
        REFERENCIA,
    )


def meta(offline: bool = True, **kwargs: object) -> MetadatosReporte:
    return MetadatosReporte(
        archivo_csv="data/gastos_historicos.csv",
        archivo_politica="config/politica.json",
        comando="python -m xpendit analizar data/gastos_historicos.csv --offline",
        fuente_tasas="tasas de prueba",
        offline=offline,
        tasas_ejemplo=TASAS_EJEMPLO_USD if offline else None,
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.fixture(scope="module")
def reporte() -> ReporteLote:
    return reporte_real()


# --- Hallazgos --------------------------------------------------------------------------


def test_comparacion_de_duplicados(reporte: ReporteLote) -> None:
    comp = hallazgos.comparar_duplicados(reporte)
    assert (len(comp.grupos_enunciado), comp.marcados(comp.grupos_enunciado)) == (7, 9)
    assert (len(comp.grupos_estrictos), comp.marcados(comp.grupos_estrictos)) == (3, 4)
    ids_cruzados = [[g.id for g in grupo] for grupo in comp.grupos_entre_empleados]
    assert ["g_001", "g_011"] in ids_cruzados  # 50 USD el 2026-10-07, Bruno y Ana
    assert len(ids_cruzados) == 5


def test_resumen_por_empleado_ordena_por_rechazos(reporte: ReporteLote) -> None:
    resumenes = hallazgos.resumen_por_empleado(reporte)
    assert resumenes[0].empleado.nombre_completo == "Bruno Soto"
    assert resumenes[0].por_estado[Estado.RECHAZADO] == 7
    assert sum(r.total for r in resumenes) == 50


def test_monto_base_por_estado_suma_el_total(reporte: ReporteLote) -> None:
    totales = hallazgos.monto_base_por_estado(reporte)
    assert totales[Estado.APROBADO] == Decimal("915")


# --- Markdown -----------------------------------------------------------------------------


def test_markdown_responde_lo_que_pide_el_enunciado(reporte: ReporteLote) -> None:
    md = generar_markdown(reporte, meta())
    # Desglose por estado
    assert "| **APROBADO** | 8 |" in md
    assert "| **PENDIENTE** | 17 |" in md
    assert "| **RECHAZADO** | 25 |" in md
    # Anomalías con ejemplos y comparación de criterios
    assert "**7 grupos**, **9 gastos marcados**" in md
    assert "`g_001` (Bruno Soto) / `g_011` (Ana Reyes): 50 USD el 2026-10-07" in md
    assert "No hay montos negativos ni cero en este archivo" in md
    # Optimización N+1
    assert "| **Consultas al proveedor de tasas** | **9** |" in md
    assert "| Fechas únicas en el lote | 25 |" in md
    # Fecha de referencia explícita y advertencia de tasas de ejemplo
    assert "**2026-10-26**" in md
    assert "tasas de ejemplo" in md.lower()
    assert "## Anexo: tasas de ejemplo" in md
    # Hallazgos de negocio
    assert "`core_engineering` rindió `food` 4 veces" in md


def test_resumen_responde_las_tres_preguntas_antes_del_detalle(reporte: ReporteLote) -> None:
    md = generar_markdown(reporte, meta())
    resumen = md[md.index("## Resumen") : md.index("## 1. Desglose")]
    assert "**8 APROBADOS, 17 PENDIENTES y 25 RECHAZADOS** de 50 gastos" in resumen
    assert "**7 grupos de duplicados exactos** (9 copias marcadas)" in resumen
    assert "5 mezclan empleados distintos, p. ej. `g_001` / `g_011`" in resumen
    assert "Ningún monto negativo ni cero." in resumen
    assert "**9 consultas** al proveedor de tasas para 50 gastos" in resumen  # offline: sin API


def test_resumen_con_montos_invalidos_y_en_singular() -> None:
    reporte = _reporte_chico((gasto(id="g_neg", monto="-10", dias=1), empleado()))
    md = generar_markdown(reporte, meta(offline=False))
    resumen = md[md.index("## Resumen") : md.index("## 1. Desglose")]
    assert "**0 APROBADOS, 0 PENDIENTES y 1 RECHAZADO** de 1 gasto" in resumen
    assert "Ningún duplicado exacto." in resumen
    assert "**1 monto negativo o cero** (`g_neg`)" in resumen
    assert "**0 consultas** a la API para 1 gasto" in resumen


def test_markdown_es_determinista(reporte: ReporteLote) -> None:
    assert generar_markdown(reporte, meta()) == generar_markdown(reporte_real(), meta())


def test_markdown_en_modo_real_no_muestra_advertencia_offline(reporte: ReporteLote) -> None:
    md = generar_markdown(reporte, meta(offline=False, solicitudes_http=9))
    assert "Atención — tasas de ejemplo" not in md
    assert "Anexo" not in md
    assert "| Solicitudes HTTP reales (incluye reintentos; 0 si todo vino de caché) | 9 |" in md


def _reporte_chico(
    *gastos_y_empleados: tuple, invalidas: tuple[FilaInvalida, ...] = ()
) -> ReporteLote:  # type: ignore[type-arg]
    class Lector:
        def leer(self) -> LoteLeido:
            return LoteLeido(tuple(RegistroGasto(g, e) for g, e in gastos_y_empleados), invalidas)

    proveedor = ProveedorTasasFijas(por_fecha={date(2026, 10, 20): TASAS_PRUEBA})
    caso = AnalizarLote(MotorReglas(reglas_por_defecto()), proveedor, detectores_por_defecto())
    return caso.ejecutar(Lector(), politica(), REFERENCIA)


def test_markdown_lista_montos_invalidos_filas_invalidas_y_fechas_sin_tasa() -> None:
    reporte = _reporte_chico(
        (gasto(id="g_neg", monto="-10", dias=1), empleado()),
        (gasto(id="g_clp", monto="1000", moneda="CLP", categoria="food", dias=2), empleado()),
        invalidas=(FilaInvalida(7, "monto no numérico: 'x'", "g_x"),),
    )
    md = generar_markdown(reporte, meta(offline=False))
    assert "| `g_neg` | Ana Reyes | -10 USD |" in md
    assert "| 7 | g_x | monto no numérico: 'x' |" in md
    assert "| Fecha sin tasas | Motivo |" in md
    assert "TASA_NO_DISPONIBLE" in md


def test_markdown_escapa_barras_verticales() -> None:
    reporte = _reporte_chico((gasto(categoria="a|b", dias=1), empleado()))
    assert "a\\|b" in generar_markdown(reporte, meta())


# --- Exportación ------------------------------------------------------------------------


def test_json_tiene_la_forma_del_enunciado(reporte: ReporteLote, tmp_path: Path) -> None:
    ruta = tmp_path / "r.json"
    escribir_json(reporte, ruta)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos == a_json(reporte)
    assert datos["resumen"] == {"APROBADO": 8, "PENDIENTE": 17, "RECHAZADO": 25}
    primero = datos["resultados"][0]
    assert set(primero) == {"gasto_id", "status", "alertas"}


def test_csv_de_resultados(reporte: ReporteLote, tmp_path: Path) -> None:
    ruta = tmp_path / "r.csv"
    escribir_csv(reporte, ruta)
    with ruta.open(encoding="utf-8", newline="") as archivo:
        filas = list(csv.DictReader(archivo))
    assert len(filas) == 50
    g029 = next(f for f in filas if f["gasto_id"] == "g_029")
    assert g029["status"] == "RECHAZADO"
    assert g029["codigos"].split("|") == [
        "LIMITE_ANTIGUEDAD",
        "LIMITE_CATEGORIA",
        "POLITICA_CENTRO_COSTO",
        "DUPLICADO_EXACTO",
    ]


def test_total_del_desglose_indica_los_montos_sin_tasa() -> None:
    reporte = _reporte_chico(
        (gasto(id="g_jpy", monto="5000", moneda="JPY", categoria="software", dias=6), empleado()),
        (gasto(id="g_usd", monto="40", categoria="software", dias=6), empleado()),
    )
    md = generar_markdown(reporte, meta(offline=False))
    assert "| Total | 2 | 100.0 % | 40.00 (excluye 1 sin tasa) |" in md
    assert "1 gasto sin tasa de cambio queda fuera de los montos en USD" in md


def test_total_del_desglose_sin_faltantes(reporte: ReporteLote) -> None:
    md = generar_markdown(reporte, meta())
    assert "Todos los gastos tienen monto en USD" in md


# --- Sección de optimización: no prometer más de lo que pasa --------------------------------


def test_fechas_sin_tasa_describen_la_alerta_y_la_prioridad_sin_prometer_pendiente() -> None:
    reporte = _reporte_chico(
        (gasto(id="g_clp", monto="1000", moneda="CLP", categoria="food", dias=2), empleado()),
        (gasto(id="g_viejo", monto="1000", moneda="CLP", categoria="food", dias=90), empleado()),
    )
    md = generar_markdown(reporte, meta(offline=False))
    assert "quedan PENDIENTE" not in md
    assert "| Fechas sin tasas (sus gastos reciben `TASA_NO_DISPONIBLE`) | 2 |" in md
    assert "queda al menos PENDIENTE" in md and "sigue RECHAZADO" in md
    estados = {r.validacion.gasto_id: r.estado for r in reporte.resultados}
    assert estados == {"g_clp": Estado.PENDIENTE, "g_viejo": Estado.RECHAZADO}


def test_explicacion_de_cache_en_modo_offline(reporte: ReporteLote) -> None:
    md = generar_markdown(reporte, meta())
    assert "En esta corrida (modo `--offline`) no se llamó a la API" in md
    assert "así que volver a correr el análisis no gasta cuota" not in md


def test_explicacion_de_cache_con_cache_en_disco(reporte: ReporteLote) -> None:
    md = generar_markdown(
        reporte, meta(offline=False, solicitudes_http=0, directorio_cache=".cache/tasas")
    )
    assert "caché en disco (`.cache/tasas`)" in md
    assert "volver a correr el análisis no gasta cuota" in md


def test_explicacion_de_cache_con_sin_cache(reporte: ReporteLote) -> None:
    md = generar_markdown(reporte, meta(offline=False, solicitudes_http=9))
    assert "`--sin-cache`" in md
    assert "cada corrida vuelve a consultar" in md
    assert "no gasta cuota" not in md
