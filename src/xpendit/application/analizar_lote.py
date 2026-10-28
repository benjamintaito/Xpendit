"""Caso de uso: analizar un lote de gastos.

Flujo en dos fases bien separadas:

1. **I/O de tasas (una vez por fecha).** Se agrupan las fechas únicas de los gastos que
   necesitan conversión y se consulta al proveedor *una sola vez por fecha* (evita el
   problema N+1: en el CSV del desafío, 50 gastos en 25 fechas únicas, de las cuales 9
   tienen gastos en moneda extranjera = 9 consultas, no 50). El resultado se congela en
   una instantánea :class:`TasasPrecargadas`.
2. **Evaluación pura.** Detectores de anomalías + motor de reglas contra la instantánea:
   ninguna consulta de red ocurre durante la evaluación.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal

from xpendit.application.lote import (
    EstadisticasTasas,
    LectorGastos,
    RegistroGasto,
    ReporteLote,
    ResultadoGasto,
)
from xpendit.domain.anomalias import DetectorAnomalias
from xpendit.domain.errores import (
    ConversionNoDisponible,
    ErrorFatalProveedor,
    ErrorProveedorTasas,
)
from xpendit.domain.modelos import Gasto, ResultadoRegla
from xpendit.domain.motor import MotorReglas
from xpendit.domain.politica import Politica
from xpendit.domain.reglas.base import ContextoEvaluacion
from xpendit.domain.tasas import ConversorMoneda, ProveedorTasas, TasasPrecargadas

logger = logging.getLogger(__name__)


class AnalizarLote:
    def __init__(
        self,
        motor: MotorReglas,
        proveedor_tasas: ProveedorTasas,
        detectores: Sequence[DetectorAnomalias] = (),
    ) -> None:
        self._motor = motor
        self._proveedor = proveedor_tasas
        self._detectores = tuple(detectores)

    def ejecutar(
        self, lector: LectorGastos, politica: Politica, fecha_referencia: date
    ) -> ReporteLote:
        lote = lector.leer()
        for fila in lote.filas_invalidas:
            logger.warning("Fila inválida omitida: %s", fila)
        gastos = [r.gasto for r in lote.registros]

        tasas, estadisticas = self._precargar_tasas(gastos, politica.moneda_base)
        conversor = ConversorMoneda(tasas)
        contexto = ContextoEvaluacion(politica, fecha_referencia, conversor)
        hallazgos = self._detectar_anomalias(gastos)

        resultados = tuple(
            self._evaluar(registro, contexto, hallazgos.get(registro.gasto.id, ()))
            for registro in lote.registros
        )
        return ReporteLote(
            fecha_referencia=fecha_referencia,
            politica=politica,
            resultados=resultados,
            filas_invalidas=lote.filas_invalidas,
            tasas=estadisticas,
        )

    # --- fase 1: tasas -------------------------------------------------------------

    def _precargar_tasas(
        self, gastos: Sequence[Gasto], moneda_base: str
    ) -> tuple[TasasPrecargadas, EstadisticasTasas]:
        """Una consulta por fecha única, solo para fechas con gastos en otra moneda.

        - Falla fatal (credenciales, cuota): se propaga; seguir no tiene sentido.
        - Falla puntual de una fecha: se registra y sus gastos en moneda extranjera
          reciben la alerta TASA_NO_DISPONIBLE (``ReglaConversionMoneda``), que los deja al
          menos PENDIENTE; si otra regla los rechaza, siguen RECHAZADO.
        """
        fechas = sorted({g.fecha for g in gastos if g.moneda != moneda_base})
        por_fecha: dict[date, Mapping[str, Decimal]] = {}
        fallas: dict[date, str] = {}
        for fecha in fechas:
            try:
                por_fecha[fecha] = self._proveedor.obtener_tasas(fecha)
            except ErrorFatalProveedor:
                raise
            except (ErrorProveedorTasas, ConversionNoDisponible) as error:
                logger.warning("Sin tasas para %s: %s", fecha.isoformat(), error)
                fallas[fecha] = str(error)

        estadisticas = EstadisticasTasas(
            fechas_unicas=len({g.fecha for g in gastos}),
            fechas_consultadas=tuple(fechas),
            fallas=fallas,
        )
        logger.info(
            "Tasas: %d gastos, %d fechas únicas, %d consultas al proveedor (%d fallidas).",
            len(gastos),
            estadisticas.fechas_unicas,
            estadisticas.consultas,
            len(fallas),
        )
        return TasasPrecargadas(por_fecha, fallas), estadisticas

    # --- fase 2: evaluación pura ---------------------------------------------------

    def _detectar_anomalias(self, gastos: Sequence[Gasto]) -> dict[str, list[ResultadoRegla]]:
        hallazgos: dict[str, list[ResultadoRegla]] = defaultdict(list)
        for detector in self._detectores:
            for gasto_id, alertas in detector.detectar(gastos).items():
                hallazgos[gasto_id].append(ResultadoRegla(detector.estado, tuple(alertas)))
        return hallazgos

    def _evaluar(
        self,
        registro: RegistroGasto,
        contexto: ContextoEvaluacion,
        hallazgos: Sequence[ResultadoRegla],
    ) -> ResultadoGasto:
        gasto = registro.gasto
        validacion = self._motor.evaluar(gasto, registro.empleado, contexto, hallazgos)
        try:
            monto_base: Decimal | None = contexto.conversor.convertir(
                gasto.monto, gasto.moneda, contexto.politica.moneda_base, gasto.fecha
            )
        except ConversionNoDisponible:
            monto_base = None
        return ResultadoGasto(
            registro=registro,
            validacion=validacion,
            monto_base=monto_base,
            dias_antiguedad=(contexto.fecha_referencia - gasto.fecha).days,
        )
