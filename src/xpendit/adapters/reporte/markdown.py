"""Genera ANALISIS.md a partir de un ReporteLote.

Todo el contenido sale de los datos: si cambian las tasas, la política o la fecha de
referencia, basta con volver a correr el analizador. No incluye la hora de generación
para que regenerar con los mismos datos produzca exactamente el mismo archivo.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from xpendit.application import hallazgos
from xpendit.application.lote import ReporteLote, ResultadoGasto
from xpendit.domain.anomalias import DetectorDuplicados, DetectorMontoInvalido
from xpendit.domain.modelos import Estado, Gasto
from xpendit.domain.reglas import (
    ReglaAntiguedad,
    ReglaCentroCosto,
    ReglaConversionMoneda,
    ReglaLimiteCategoria,
)

DESCRIPCION_CODIGOS: Mapping[str, str] = {
    ReglaAntiguedad.CODIGO: "Antigüedad sobre el umbral de la política",
    ReglaAntiguedad.CODIGO_FECHA_FUTURA: "Fecha posterior a la fecha de referencia",
    ReglaLimiteCategoria.CODIGO: "Monto (en moneda base) sobre el límite de la categoría",
    ReglaConversionMoneda.CODIGO: "Sin tasa de cambio para convertir a la moneda base",
    ReglaCentroCosto.CODIGO: "Categoría prohibida para el centro de costo",
    DetectorDuplicados.codigo: "Mismo monto, moneda y fecha que un gasto anterior",
    DetectorMontoInvalido.codigo: "Monto negativo o cero",
}


@dataclass(frozen=True, slots=True)
class MetadatosReporte:
    archivo_csv: str
    archivo_politica: str
    comando: str
    fuente_tasas: str
    offline: bool
    tasas_ejemplo: Mapping[str, Decimal] | None = None
    solicitudes_http: int | None = None
    # Caché en disco realmente usada en la corrida (None: --offline o --sin-cache).
    directorio_cache: str | None = None


def generar_markdown(reporte: ReporteLote, meta: MetadatosReporte) -> str:
    secciones = [
        _encabezado(reporte, meta),
        _resumen(reporte, meta),
        _desglose(reporte),
        _anomalias(reporte),
        _optimizacion(reporte, meta),
        _hallazgos_negocio(reporte, meta),
        _detalle(reporte),
        _supuestos(reporte),
    ]
    if meta.offline and meta.tasas_ejemplo:
        secciones.append(_anexo_tasas(reporte, meta.tasas_ejemplo))
    return "\n\n".join(s.strip("\n") for s in secciones) + "\n"


# --- secciones ------------------------------------------------------------------------


def _encabezado(reporte: ReporteLote, meta: MetadatosReporte) -> str:
    pol = reporte.politica
    partes = [
        "# Análisis del lote de gastos históricos",
        f"> Archivo generado con `{meta.comando}`. No editar a mano: regenerar.",
    ]
    if meta.offline:
        partes.append(
            "> **Atención — tasas de ejemplo.** Este análisis se generó en modo `--offline` con "
            "tasas fijas aproximadas (ver anexo), no con cotizaciones reales. Los gastos en "
            "monedas distintas de "
            f"{pol.moneda_base} pueden cambiar de estado con las tasas reales: el resultado "
            "definitivo debe regenerarse con la API de Open Exchange Rates (sin `--offline`)."
        )
    antig = pol.limite_antiguedad
    umbral = f"{antig.pendiente_dias}/{antig.rechazado_dias} días" if antig else "sin límite"
    partes.append(
        _tabla(
            ["Parámetro", "Valor"],
            [
                ["Archivo de gastos", f"`{meta.archivo_csv}`"],
                ["Política", f"`{meta.archivo_politica}` (moneda base {pol.moneda_base})"],
                [
                    "Fecha de referencia",
                    f"**{reporte.fecha_referencia.isoformat()}** — la antigüedad ({umbral}) se "
                    "mide contra esta fecha; con otra fecha el desglose cambia",
                ],
                ["Tasas de cambio", meta.fuente_tasas],
            ],
        )
    )
    return "\n\n".join(partes)


def _resumen(reporte: ReporteLote, meta: MetadatosReporte) -> str:
    """Respuesta breve a las tres preguntas del enunciado; el detalle va en las secciones 1-3."""
    conteo = reporte.conteo_por_estado()
    estados = [f"{n} {e.value}{'' if n == 1 else 'S'}" for e, n in conteo.items()]
    gastos = _gastos(len(reporte.resultados))

    comp = hallazgos.comparar_duplicados(reporte)
    if comp.grupos_enunciado:
        cruzados = comp.grupos_entre_empleados
        ejemplo = (cruzados or comp.grupos_enunciado)[0]
        duplicados = (
            f"**{len(comp.grupos_enunciado)} grupos de duplicados exactos** "
            f"({comp.marcados(comp.grupos_enunciado)} copias marcadas); "
            f"{len(cruzados)} mezclan empleados distintos, p. ej. "
            + " / ".join(f"`{g.id}`" for g in ejemplo)
            + f": {_monto(ejemplo[0])} el {ejemplo[0].fecha.isoformat()}."
        )
    else:
        duplicados = "Ningún duplicado exacto."
    invalidos = hallazgos.con_alerta(reporte, DetectorMontoInvalido.codigo)
    if invalidos:
        n = len(invalidos)
        ids = ", ".join(f"`{r.registro.gasto.id}`" for r in invalidos)
        negativos = (
            f"**{n} monto{'' if n == 1 else 's'} negativo{'' if n == 1 else 's'} o cero** ({ids})."
        )
    else:
        negativos = "Ningún monto negativo ni cero."

    t = reporte.tasas
    destino = "al proveedor de tasas" if meta.offline else "a la API"
    return "\n\n".join(
        [
            "## Resumen",
            _lista(
                [
                    f"**Desglose:** **{', '.join(estados[:-1])} y {estados[-1]}** de {gastos}.",
                    f"**Anomalías:** {duplicados} {negativos}",
                    f"**Optimización N+1:** **{t.consultas} consultas** {destino} para {gastos}, "
                    f"una por fecha única con gastos en moneda distinta de "
                    f"{reporte.politica.moneda_base}, en vez de una por gasto.",
                ]
            ),
        ]
    )


def _desglose(reporte: ReporteLote) -> str:
    conteo = reporte.conteo_por_estado()
    montos = hallazgos.monto_base_por_estado(reporte)
    total = len(reporte.resultados)
    base = reporte.politica.moneda_base
    filas = [
        [f"**{e.value}**", str(n), _pct(n, total), _dinero(montos[e])] for e, n in conteo.items()
    ]
    sin_monto = reporte.sin_monto_base()
    total_monto = _dinero(sum(montos.values(), Decimal(0)))
    if sin_monto:
        total_monto += f" (excluye {sin_monto} sin tasa)"
        nota_montos = (
            f"**Ojo con los montos:** {_gastos(sin_monto)} sin tasa de cambio "
            f"{'queda' if sin_monto == 1 else 'quedan'} fuera de los montos en {base} (no se "
            f"pudieron convertir; ver `{ReglaConversionMoneda.CODIGO}`). Los totales suman solo "
            "los gastos convertidos."
        )
    else:
        nota_montos = (
            f"Todos los gastos tienen monto en {base} (convertido con la tasa del día de cada "
            "gasto cuando la moneda es otra)."
        )
    filas.append(["Total", str(total), _pct(total, total), total_monto])

    por_alerta = reporte.conteo_por_alerta()
    rech = hallazgos.motivos_por_estado(reporte, Estado.RECHAZADO)
    pend = hallazgos.motivos_por_estado(reporte, Estado.PENDIENTE)
    filas_alertas = [
        [
            f"`{codigo}`",
            str(n),
            str(rech.get(codigo, 0)),
            str(pend.get(codigo, 0)),
            DESCRIPCION_CODIGOS.get(codigo, ""),
        ]
        for codigo, n in sorted(por_alerta.items(), key=lambda x: (-x[1], x[0]))
    ]
    return "\n\n".join(
        [
            "## 1. Desglose por estado",
            f"Filas leídas: **{reporte.filas_leidas}** · gastos válidos evaluados: "
            f"**{total}** · filas inválidas omitidas: **{len(reporte.filas_invalidas)}**.",
            _tabla(["Estado", "Gastos", "%", f"Monto ({base})"], filas),
            nota_montos,
            "### Motivos (alertas)",
            "Un gasto puede tener varias alertas; se conservan todas, no solo la que decidió "
            "el estado.",
            _tabla(
                ["Código", "Gastos con la alerta", "…en RECHAZADO", "…en PENDIENTE", "Significado"],
                filas_alertas,
            )
            if filas_alertas
            else "_Ningún gasto generó alertas._",
        ]
    )


def _anomalias(reporte: ReporteLote) -> str:
    comp = hallazgos.comparar_duplicados(reporte)
    por_id = {r.registro.gasto.id: r for r in reporte.resultados}
    det_dup = DetectorDuplicados()

    filas_dup = []
    for i, grupo in enumerate(comp.grupos_enunciado, start=1):
        for j, gasto in enumerate(grupo):
            r = por_id[gasto.id]
            filas_dup.append(
                [
                    str(i),
                    f"`{gasto.id}`",
                    "original" if j == 0 else f"copia de `{grupo[0].id}`",
                    r.registro.empleado.nombre_completo,
                    gasto.categoria,
                    _monto(gasto),
                    gasto.fecha.isoformat(),
                    r.estado.value,
                ]
            )

    marcados = comp.marcados(comp.grupos_enunciado)
    partes = [
        "## 2. Anomalías",
        "### 2.1 Duplicados exactos (mismo monto, moneda y fecha)",
        f"Se aplica la definición del enunciado. En cada grupo el primer gasto del archivo se "
        f"considera el original y no se marca; cada copia recibe la alerta `{det_dup.codigo}` "
        f"y queda al menos **{det_dup.estado.value}** (revisión humana: no se rechaza en "
        "automático). Si otra regla la rechaza, sigue rechazada.",
        f"Resultado: **{len(comp.grupos_enunciado)} grupos**, **{marcados} gastos marcados** "
        "como copia.",
    ]
    if filas_dup:
        partes.append(
            _tabla(
                [
                    "Grupo",
                    "Gasto",
                    "Rol",
                    "Empleado",
                    "Categoría",
                    "Monto",
                    "Fecha",
                    "Estado final",
                ],
                filas_dup,
            )
        )

    marcados_estrictos = comp.marcados(comp.grupos_estrictos)
    partes += [
        "**Ojo con la definición.** Monto + moneda + fecha no mira quién rindió el gasto, así "
        f"que en este archivo **{len(comp.grupos_entre_empleados)} de los "
        f"{len(comp.grupos_enunciado)} grupos** mezclan empleados distintos (probables "
        "coincidencias, no duplicados):",
        _lista(
            " / ".join(
                f"`{g.id}` ({por_id[g.id].registro.empleado.nombre_completo})" for g in grupo
            )
            + f": {_monto(grupo[0])} el {grupo[0].fecha.isoformat()}"
            for grupo in comp.grupos_entre_empleados
        )
        or "_Ninguno._",
        "Una versión más estricta agregaría empleado y categoría a la clave. Comparación:",
        _tabla(
            ["Criterio", "Grupos", "Gastos marcados"],
            [
                [
                    "Enunciado: monto + moneda + fecha (aplicado)",
                    str(len(comp.grupos_enunciado)),
                    str(marcados),
                ],
                [
                    "Estricto: + empleado + categoría (informativo)",
                    str(len(comp.grupos_estrictos)),
                    str(marcados_estrictos),
                ],
            ],
        ),
        "Grupos que sobreviven al criterio estricto: "
        + (
            ", ".join(" = ".join(f"`{g.id}`" for g in grupo) for grupo in comp.grupos_estrictos)
            or "ninguno"
        )
        + ".",
    ]

    invalidos = hallazgos.con_alerta(reporte, DetectorMontoInvalido.codigo)
    partes.append("### 2.2 Montos negativos o cero")
    if invalidos:
        partes.append(
            _tabla(
                ["Gasto", "Empleado", "Monto", "Fecha", "Estado final"],
                [
                    [
                        f"`{r.registro.gasto.id}`",
                        r.registro.empleado.nombre_completo,
                        _monto(r.registro.gasto),
                        r.registro.gasto.fecha.isoformat(),
                        r.estado.value,
                    ]
                    for r in invalidos
                ],
            )
        )
    else:
        partes.append(
            "**No hay montos negativos ni cero en este archivo.** El detector existe y está "
            "cubierto por tests: un monto `<= 0` recibe la alerta "
            f"`{DetectorMontoInvalido.codigo}` y queda **RECHAZADO** (no hay nada que "
            "reembolsar; una devolución o nota de crédito debe ir por otro flujo). "
            "Un monto no numérico se reporta como fila inválida."
        )

    partes.append("### 2.3 Filas inválidas")
    if reporte.filas_invalidas:
        partes.append(
            _tabla(
                ["Línea", "Gasto", "Motivo"],
                [
                    [str(f.numero_linea), f.gasto_id or "—", f.motivo]
                    for f in reporte.filas_invalidas
                ],
            )
        )
    else:
        partes.append("Ninguna: todas las filas tienen el formato esperado.")
    return "\n\n".join(partes)


def _optimizacion(reporte: ReporteLote, meta: MetadatosReporte) -> str:
    t = reporte.tasas
    base = reporte.politica.moneda_base
    extranjeros = sum(1 for g in reporte.gastos() if g.moneda != base)
    http = (
        "0 (modo offline)"
        if meta.offline
        else (str(meta.solicitudes_http) if meta.solicitudes_http is not None else "—")
    )
    filas = [
        ["Gastos evaluados", str(len(reporte.resultados))],
        [f"Gastos en moneda distinta de {base}", str(extranjeros)],
        ["Fechas únicas en el lote", str(t.fechas_unicas)],
        [f"Fechas únicas con gastos en moneda distinta de {base}", str(len(t.fechas_consultadas))],
        ["**Consultas al proveedor de tasas**", f"**{t.consultas}**"],
        ["Solicitudes HTTP reales (incluye reintentos; 0 si todo vino de caché)", http],
        [
            f"Fechas sin tasas (sus gastos reciben `{ReglaConversionMoneda.CODIGO}`)",
            str(len(t.fallas)),
        ],
    ]
    partes = [
        "## 3. Optimización N+1 de tasas de cambio",
        "Sin agrupar, se pediría la tasa al convertir cada gasto (una llamada por gasto). "
        "El analizador, en cambio, agrupa las **fechas únicas** de los gastos que necesitan "
        "conversión, consulta **una sola vez por fecha** y evalúa todo contra esa instantánea "
        "en memoria (la evaluación no hace red). Los gastos ya expresados en la moneda base no "
        "necesitan tasa, así que sus fechas no se consultan.",
        _tabla(["Métrica", "Valor"], filas),
        f"Con el plan gratuito (~1000 solicitudes/mes) esto significa {t.consultas} solicitudes "
        f"en vez de {len(reporte.resultados)}. " + _explicacion_cache(t.consultas, meta),
    ]
    if t.fallas:
        partes.append(
            "Los gastos en moneda extranjera de esas fechas reciben la alerta "
            f"`{ReglaConversionMoneda.CODIGO}`: un gasto así queda al menos PENDIENTE (no hay "
            "base para aprobarlo), pero si otra regla lo rechaza (p. ej. por antigüedad) sigue "
            "RECHAZADO, por la prioridad RECHAZADO > PENDIENTE > APROBADO."
        )
        partes.append(
            _tabla(
                ["Fecha sin tasas", "Motivo"],
                [[f.isoformat(), motivo] for f, motivo in sorted(t.fallas.items())],
            )
        )
    return "\n\n".join(partes)


def _explicacion_cache(consultas: int, meta: MetadatosReporte) -> str:
    """Describe la caché según lo que realmente se usó en esta corrida."""
    if meta.offline:
        return (
            "En esta corrida (modo `--offline`) no se llamó a la API: las tasas son fijas de "
            "ejemplo. Con la API real, además, las tasas de días cerrados se guardan en una "
            "caché en disco (`.cache/tasas/` por defecto) y una segunda corrida no gasta cuota."
        )
    if meta.directorio_cache is not None:
        return (
            "Además, las tasas de días cerrados se guardan en una caché en disco "
            f"(`{meta.directorio_cache}`), así que volver a correr el análisis no gasta cuota "
            "(la fila de solicitudes HTTP muestra 0 cuando todo vino de la caché)."
        )
    return (
        "Esta corrida usó `--sin-cache`: no se leyó ni escribió la caché en disco, así que "
        f"cada corrida vuelve a consultar esas {consultas} fechas a la API."
    )


def _hallazgos_negocio(reporte: ReporteLote, meta: MetadatosReporte) -> str:
    base = reporte.politica.moneda_base
    rechazados = [r for r in reporte.resultados if r.estado is Estado.RECHAZADO]
    partes = ["## 4. Hallazgos de negocio"]

    # Antigüedad como principal motivo de rechazo.
    antig = reporte.politica.limite_antiguedad
    if antig and rechazados:
        por_antiguedad = [r for r in rechazados if r.dias_antiguedad > antig.rechazado_dias]
        solo_antiguedad = [r for r in por_antiguedad if set(r.codigos) == {ReglaAntiguedad.CODIGO}]
        partes.append(
            f"- **La antigüedad domina los rechazos:** {len(por_antiguedad)} de "
            f"{len(rechazados)} rechazos tienen más de {antig.rechazado_dias} días a la fecha de "
            f"referencia, y {len(solo_antiguedad)} de ellos se rechazan *solo* por eso. Son "
            "rendiciones tardías más que gastos indebidos: conviene recordar el plazo a los "
            "equipos (y el número depende directamente de la fecha de referencia)."
        )

    # Centro de costo con categoría prohibida.
    prohibidos = hallazgos.con_alerta(reporte, ReglaCentroCosto.CODIGO)
    for regla in reporte.politica.reglas_centro_costo:
        casos = [
            r
            for r in prohibidos
            if r.registro.empleado.cost_center == regla.cost_center
            and r.registro.gasto.categoria == regla.categoria_prohibida
        ]
        if not casos:
            continue
        personas = sorted({r.registro.empleado.nombre_completo for r in casos})
        partes.append(
            f"- **`{regla.cost_center}` rindió `{regla.categoria_prohibida}` {len(casos)} veces** "
            f"({', '.join(f'`{r.registro.gasto.id}`' for r in casos)}; "
            f"{', '.join(personas)}), todos rechazados por política. "
            f"Total {_dinero(_suma_base(casos))} {base}. Sugiere que la restricción no es "
            "conocida en el equipo."
        )

    # Concentración de rechazos por empleado.
    resumenes = hallazgos.resumen_por_empleado(reporte)
    if resumenes and rechazados:
        top = resumenes[0]
        partes.append(
            f"- **Quién concentra rechazos:** {top.empleado.nombre_completo} "
            f"(`{top.empleado.cost_center}`) con {top.por_estado[Estado.RECHAZADO]} de "
            f"{top.total} gastos rechazados "
            f"({_dinero(top.monto_base_rechazado)} {base}). Detalle por empleado:"
        )
        partes.append(
            _tabla(
                [
                    "Empleado",
                    "C.C.",
                    "Gastos",
                    "Aprobados",
                    "Pendientes",
                    "Rechazados",
                    f"Monto rechazado ({base})",
                ],
                [
                    [
                        s.empleado.nombre_completo,
                        s.empleado.cost_center,
                        str(s.total),
                        str(s.por_estado[Estado.APROBADO]),
                        str(s.por_estado[Estado.PENDIENTE]),
                        str(s.por_estado[Estado.RECHAZADO]),
                        _dinero(s.monto_base_rechazado),
                    ]
                    for s in resumenes
                ],
            )
        )

    # Límites por categoría.
    sobre_limite = hallazgos.con_alerta(reporte, ReglaLimiteCategoria.CODIGO)
    if sobre_limite:
        por_categoria: dict[str, int] = {}
        for r in sobre_limite:
            cat = r.registro.gasto.categoria
            por_categoria[cat] = por_categoria.get(cat, 0) + 1
        detalle = ", ".join(f"{n} en `{c}`" for c, n in sorted(por_categoria.items()))
        partes.append(
            f"- **Límites por categoría:** {len(sobre_limite)} gastos superan el monto de "
            f"aprobación automática ({detalle})."
        )

    # Duplicados con mayor probabilidad de ser reales.
    comp = hallazgos.comparar_duplicados(reporte)
    if comp.grupos_estrictos:
        nombres = {
            r.registro.empleado.id: r.registro.empleado.nombre_completo for r in reporte.resultados
        }
        grupos = "; ".join(
            " = ".join(f"`{g.id}`" for g in grupo)
            + f" ({nombres[grupo[0].empleado_id]}, {grupo[0].categoria}, {_monto(grupo[0])})"
            for grupo in comp.grupos_estrictos
        )
        partes.append(
            f"- **Duplicados más probables:** los {len(comp.grupos_estrictos)} grupos que "
            f"coinciden también en empleado y categoría ({grupos}) son los primeros que "
            "revisaría un analista."
        )

    # Sensibilidad a las tasas de cambio.
    sensibles = _sensibles_a_tasa(reporte)
    if sensibles:
        aviso = (
            "con las tasas de ejemplo; con tasas reales pueden moverse"
            if meta.offline
            else "con las tasas reales del día de cada gasto"
        )
        partes.append(
            f"- **Sensibilidad a la tasa de cambio:** {len(sensibles)} gastos en moneda "
            f"extranjera caen en una categoría con límite; su monto en {base} se calculó "
            f"{aviso}. Distancia al umbral más cercano:"
        )
        partes.append(
            _tabla(
                [
                    "Gasto",
                    "Monto original",
                    f"Monto {base}",
                    "Umbral más cercano",
                    "Margen",
                    "Estado final",
                ],
                sensibles,
            )
        )
    return "\n\n".join(partes)


def _detalle(reporte: ReporteLote) -> str:
    base = reporte.politica.moneda_base
    filas = []
    for r in reporte.resultados:
        g, e = r.registro.gasto, r.registro.empleado
        filas.append(
            [
                f"`{g.id}`",
                e.nombre_completo,
                e.cost_center,
                g.categoria,
                _monto(g),
                _dinero(r.monto_base) if r.monto_base is not None else "—",
                g.fecha.isoformat(),
                str(r.dias_antiguedad),
                f"**{r.estado.value}**",
                "<br>".join(f"`{a.codigo}`: {a.mensaje}" for a in r.validacion.alertas) or "—",
            ]
        )
    return "\n\n".join(
        [
            "## 5. Detalle por gasto",
            _tabla(
                [
                    "Gasto",
                    "Empleado",
                    "C.C.",
                    "Categoría",
                    "Monto",
                    f"{base}",
                    "Fecha",
                    "Días",
                    "Estado",
                    "Alertas",
                ],
                filas,
            ),
        ]
    )


def _supuestos(reporte: ReporteLote) -> str:
    pol = reporte.politica
    sin_limite = sorted({g.categoria for g in reporte.gastos()} - set(pol.limites_por_categoria))
    texto_sin_limite = (
        f"Categorías del lote sin límite configurado ({', '.join(sin_limite)}) no se evalúan "
        "por monto."
        if sin_limite
        else "Todas las categorías del lote tienen límite configurado."
    )
    return "\n\n".join(
        [
            "## 6. Supuestos y decisiones",
            _lista(
                [
                    "Estado final por prioridad: RECHAZADO > PENDIENTE > APROBADO; si ninguna "
                    "regla aplica, PENDIENTE sin alertas.",
                    f"Antigüedad = días calendario entre la fecha del gasto y la fecha de "
                    f"referencia ({reporte.fecha_referencia.isoformat()}). Fecha futura → "
                    "PENDIENTE con alerta `FECHA_FUTURA`.",
                    f"Límites por categoría comparados en {pol.moneda_base}, con la tasa del día "
                    "del gasto y el monto convertido redondeado a centavos. " + texto_sin_limite,
                    "Gasto en moneda extranjera sin tasa (para la moneda o la fecha), en "
                    "cualquier categoría → alerta `TASA_NO_DISPONIBLE`: queda al menos "
                    "PENDIENTE (no hay base para aprobarlo) y RECHAZADO si otra regla lo "
                    "rechaza; su monto no entra en los totales.",
                    "Duplicado = mismo monto, moneda y fecha (definición del enunciado); el "
                    "primero del archivo es el original; las copias quedan al menos PENDIENTE "
                    "(RECHAZADO si otra regla las rechaza).",
                    "Monto negativo o cero → RECHAZADO con alerta `MONTO_INVALIDO`.",
                    "Detalle y alternativas consideradas: "
                    "[`docs/DECISIONES.md`](docs/DECISIONES.md).",
                ]
            ),
        ]
    )


def _anexo_tasas(reporte: ReporteLote, tasas: Mapping[str, Decimal]) -> str:
    monedas = sorted({g.moneda for g in reporte.gastos()} | {reporte.politica.moneda_base})
    filas = [[m, str(tasas[m]) if m in tasas else "— (sin tasa)"] for m in monedas]
    return "\n\n".join(
        [
            "## Anexo: tasas de ejemplo usadas (modo offline)",
            "Unidades de cada moneda por 1 USD, iguales para todas las fechas. Son valores "
            "redondos aproximados elegidos para correr sin API key; **no son cotizaciones "
            "reales**.",
            _tabla(["Moneda", "Unidades por USD"], filas),
        ]
    )


# --- ayudas ---------------------------------------------------------------------------


def _sensibles_a_tasa(reporte: ReporteLote) -> list[list[str]]:
    base = reporte.politica.moneda_base
    filas = []
    for r in reporte.resultados:
        g = r.registro.gasto
        limite = reporte.politica.limites_por_categoria.get(g.categoria)
        monto = r.monto_base
        if g.moneda == base or limite is None or monto is None:
            continue
        umbrales = sorted({limite.aprobado_hasta, limite.pendiente_hasta})
        umbral = min(umbrales, key=lambda u: abs(monto - u))
        margen = monto - umbral
        filas.append(
            [
                f"`{g.id}`",
                _monto(g),
                _dinero(monto),
                f"{_dinero(umbral)} ({g.categoria})",
                f"{'+' if margen > 0 else ''}{_dinero(margen)}",
                r.estado.value,
            ]
        )
    return filas


def _suma_base(resultados: Sequence[ResultadoGasto]) -> Decimal:
    return sum((r.monto_base for r in resultados if r.monto_base is not None), Decimal(0))


def _gastos(n: int) -> str:
    return f"{n} gasto" if n == 1 else f"{n} gastos"


def _monto(gasto: Gasto) -> str:
    return f"{gasto.monto} {gasto.moneda}"


def _dinero(valor: Decimal) -> str:
    return f"{valor:.2f}"


def _pct(parte: int, total: int) -> str:
    return f"{(100 * parte / total):.1f} %" if total else "—"


def _celda(texto: str) -> str:
    return texto.replace("|", "\\|").replace("\n", " ")


def _tabla(encabezados: Sequence[str], filas: Iterable[Sequence[str]]) -> str:
    lineas = [
        "| " + " | ".join(encabezados) + " |",
        "|" + "|".join("---" for _ in encabezados) + "|",
    ]
    lineas += ["| " + " | ".join(_celda(c) for c in fila) + " |" for fila in filas]
    return "\n".join(lineas)


def _lista(items: Iterable[str]) -> str:
    return "\n".join(f"- {item}" for item in items)
