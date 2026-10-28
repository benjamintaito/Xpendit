"""CLI delgada: parsea argumentos, arma dependencias (composicion) y muestra resultados.

Uso::

    python -m xpendit analizar data/gastos_historicos.csv --offline --fecha-referencia 2026-10-26
"""

from __future__ import annotations

import argparse
import codecs
import contextlib
import io
import logging
import os
import shlex
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from xpendit.adapters.csv_gastos import LectorCsvGastos
from xpendit.adapters.politica_json import cargar_politica
from xpendit.adapters.reporte.exportar import escribir_csv, escribir_json
from xpendit.adapters.reporte.markdown import MetadatosReporte, generar_markdown
from xpendit.application.lote import ReporteLote
from xpendit.composicion import construir_analizador, construir_fuente_tasas
from xpendit.domain.errores import ConfiguracionInvalida, XpenditError

EXIT_OK = 0
EXIT_ERROR = 2


def cargar_dotenv(ruta: str | None = None) -> None:
    """Carga ``.env`` (buscando desde el directorio actual hacia arriba) si existe.

    Las variables ya definidas en el entorno tienen prioridad sobre el archivo.
    """
    ruta = ruta or find_dotenv(usecwd=True)
    if not ruta:
        return
    try:
        # utf-8-sig: tolera el BOM de "UTF-8 con BOM" (Bloc de notas de Windows).
        load_dotenv(ruta, override=False, encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise ConfiguracionInvalida(
            f"El archivo {ruta} no está guardado en UTF-8. Ábrelo con un editor de texto y "
            "guárdalo con codificación UTF-8 (en el Bloc de notas: Guardar como → Codificación: "
            "UTF-8). En Windows PowerShell 5.1, `echo ... > .env` lo escribe en UTF-16."
        ) from None


def _fecha(texto: str) -> date:
    try:
        return date.fromisoformat(texto)
    except ValueError:
        raise argparse.ArgumentTypeError(f"fecha inválida '{texto}' (formato AAAA-MM-DD)") from None


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xpendit", description="Herramientas del desafío técnico de Xpendit."
    )
    sub = parser.add_subparsers(dest="comando", metavar="COMANDO")

    analizar = sub.add_parser(
        "analizar",
        help="Analiza un lote de gastos en CSV y genera ANALISIS.md.",
        description="Aplica la política a cada gasto del CSV, detecta anomalías y genera "
        "un reporte en Markdown (y opcionalmente JSON/CSV).",
    )
    analizar.add_argument("csv", type=Path, help="Ruta del CSV de gastos.")
    analizar.add_argument(
        "--politica",
        type=Path,
        default=Path("config/politica.json"),
        help="Ruta de la política JSON (por defecto: config/politica.json).",
    )
    analizar.add_argument(
        "--fecha-referencia",
        type=_fecha,
        default=None,
        help="Fecha contra la que se mide la antigüedad, AAAA-MM-DD (por defecto: hoy).",
    )
    analizar.add_argument(
        "--offline",
        action="store_true",
        help="Usa tasas fijas de ejemplo en vez de Open Exchange Rates (no requiere API key).",
    )
    analizar.add_argument(
        "--salida",
        type=Path,
        default=Path("ANALISIS.md"),
        help="Ruta del reporte Markdown (por defecto: ANALISIS.md).",
    )
    analizar.add_argument("--json", type=Path, help="Exporta además los resultados a JSON.")
    analizar.add_argument("--csv-salida", type=Path, help="Exporta además los resultados a CSV.")
    analizar.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".cache/tasas"),
        help="Directorio de la caché en disco de tasas (por defecto: .cache/tasas).",
    )
    analizar.add_argument(
        "--sin-cache", action="store_true", help="No lee ni escribe la caché en disco."
    )
    analizar.add_argument("-v", "--verbose", action="store_true", help="Muestra logs INFO.")
    analizar.set_defaults(funcion=_analizar)
    return parser


def configurar_consola() -> None:
    """Pasa ``stdout``/``stderr`` a UTF-8 (con ``errors="replace"``) si no lo están ya.

    En Windows, con la salida redirigida o una consola antigua, la codificación puede ser
    cp1252 o cp850; una ruta o un mensaje con caracteres fuera de esa página de códigos
    lanzaría ``UnicodeEncodeError`` a mitad de la corrida. Así nunca falla: en el peor caso
    un carácter se ve mal.
    """
    for flujo in (sys.stdout, sys.stderr):
        if not isinstance(flujo, io.TextIOWrapper):
            continue  # reemplazado por otra cosa (p. ej. None con pythonw): no se toca
        if codecs.lookup(flujo.encoding).name == "utf-8":
            continue
        # Flujo cerrado o que no admite el cambio: se sigue con el que hay.
        with contextlib.suppress(OSError, ValueError):
            flujo.reconfigure(encoding="utf-8", errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    configurar_consola()
    parser = construir_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "funcion"):
        parser.print_help(sys.stderr)
        return EXIT_ERROR

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        codigo: int = args.funcion(args, argv)
        return codigo
    except XpenditError as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("Interrumpido.", file=sys.stderr)
        return 130


def _analizar(args: argparse.Namespace, argv: Sequence[str] | None) -> int:
    cargar_dotenv()
    fecha_referencia: date = args.fecha_referencia or date.today()
    politica = cargar_politica(args.politica)
    fuente = construir_fuente_tasas(
        offline=args.offline,
        entorno=os.environ,
        directorio_cache=None if args.sin_cache else args.cache_dir,
    )
    analizador = construir_analizador(fuente.proveedor)
    reporte = analizador.ejecutar(LectorCsvGastos(args.csv), politica, fecha_referencia)

    meta = MetadatosReporte(
        archivo_csv=ruta_portable(str(args.csv)),
        archivo_politica=ruta_portable(str(args.politica)),
        comando=_comando(argv, args),
        fuente_tasas=fuente.descripcion,
        offline=fuente.offline,
        tasas_ejemplo=fuente.tasas_ejemplo,
        solicitudes_http=fuente.cliente.solicitudes_http if fuente.cliente else None,
        directorio_cache=fuente.directorio_cache,
    )
    _escribir(args.salida, generar_markdown(reporte, meta))
    if args.json:
        escribir_json(reporte, args.json)
    if args.csv_salida:
        escribir_csv(reporte, args.csv_salida)

    _imprimir_resumen(reporte, args, meta)
    return EXIT_OK


def _escribir(ruta: Path, contenido: str) -> None:
    try:
        # newline="\n": el mismo archivo byte a byte en Windows (que traduciría a CRLF).
        ruta.write_text(contenido, encoding="utf-8", newline="\n")
    except OSError as error:
        raise XpenditError(f"No se pudo escribir {ruta}: {error.strerror}") from None


def _comando(argv: Sequence[str] | None, args: argparse.Namespace) -> str:
    partes = list(argv) if argv is not None else sys.argv[1:]
    if args.fecha_referencia is None:
        # Deja explícita la fecha usada, para que el comando sea reproducible.
        partes += ["--fecha-referencia", date.today().isoformat()]
    return "python -m xpendit " + shlex.join(ruta_portable(p) for p in partes)


def ruta_portable(texto: str, sep: str = os.sep) -> str:
    """Muestra una ruta con ``/`` aunque se haya escrito con ``\\`` en Windows.

    Así ANALISIS.md queda igual en cualquier sistema (y ``shlex.join`` no pone entre comillas
    cada ruta con barras invertidas). Windows acepta ``/`` en las rutas, así que el comando
    que queda en el reporte sigue funcionando ahí. En macOS/Linux no cambia nada.
    """
    return texto if sep == "/" else texto.replace(sep, "/")


def _imprimir_resumen(
    reporte: ReporteLote, args: argparse.Namespace, meta: MetadatosReporte
) -> None:
    conteo = reporte.conteo_por_estado()
    t = reporte.tasas
    print(f"Fecha de referencia: {reporte.fecha_referencia.isoformat()}")
    print(f"Tasas: {meta.fuente_tasas}")
    print(
        f"Gastos evaluados: {len(reporte.resultados)} "
        f"(filas inválidas: {len(reporte.filas_invalidas)})"
    )
    for estado, n in conteo.items():
        print(f"  {estado.value:<10} {n}")
    print(
        f"Tasas: {t.fechas_unicas} fechas únicas, {t.consultas} consultas al proveedor"
        + (
            f", {meta.solicitudes_http} solicitudes HTTP"
            if meta.solicitudes_http is not None
            else ""
        )
        + (f", {len(t.fallas)} fechas sin tasas" if t.fallas else "")
    )
    if meta.offline:
        print("AVISO: modo offline con tasas de ejemplo; regenerar con la API real.")
    print(f"Reporte escrito en {args.salida}")
    for extra in (args.json, args.csv_salida):
        if extra:
            print(f"Resultados exportados a {extra}")
