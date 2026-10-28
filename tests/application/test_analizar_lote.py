from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from tests.factories import FECHA_REFERENCIA, TASAS_PRUEBA, empleado, gasto, politica
from xpendit.adapters.csv_gastos import LectorCsvGastos
from xpendit.adapters.politica_json import cargar_politica
from xpendit.adapters.tasas import TASAS_EJEMPLO_USD, ProveedorTasasFijas
from xpendit.application import AnalizarLote, LoteLeido, RegistroGasto, ReporteLote
from xpendit.domain import Estado, Gasto, MotorReglas, reglas_por_defecto
from xpendit.domain.anomalias import detectores_por_defecto
from xpendit.domain.errores import (
    AccesoRestringido,
    CuotaExcedida,
    ErrorCredencialesProveedor,
    ErrorFechaProveedor,
    ErrorPlanNoPermitido,
    ErrorProveedorTasas,
    FilaInvalida,
    TasasNoDisponibles,
)
from xpendit.domain.tasas import ProveedorTasas

RAIZ = Path(__file__).resolve().parents[2]


class ProveedorEspia:
    """Cuenta las llamadas por fecha; opcionalmente falla en algunas fechas."""

    def __init__(self, fallas: Mapping[date, Exception] | None = None) -> None:
        self.llamadas: Counter[date] = Counter()
        self._fallas = dict(fallas or {})

    def obtener_tasas(self, fecha: date) -> Mapping[str, Decimal]:
        self.llamadas[fecha] += 1
        if fecha in self._fallas:
            raise self._fallas[fecha]
        return TASAS_PRUEBA


class LectorEnMemoria:
    def __init__(self, *gastos: Gasto, invalidas: tuple[FilaInvalida, ...] = ()) -> None:
        self._lote = LoteLeido(
            tuple(RegistroGasto(g, empleado(id=g.empleado_id)) for g in gastos), invalidas
        )

    def leer(self) -> LoteLeido:
        return self._lote


def ejecutar(
    proveedor: ProveedorTasas, *gastos: Gasto, invalidas: tuple[FilaInvalida, ...] = ()
) -> ReporteLote:
    caso = AnalizarLote(MotorReglas(reglas_por_defecto()), proveedor, detectores_por_defecto())
    return caso.ejecutar(
        LectorEnMemoria(*gastos, invalidas=invalidas), politica(), FECHA_REFERENCIA
    )


# --- Optimización N+1 ---------------------------------------------------------------------


def test_n_gastos_en_k_fechas_unicas_hacen_exactamente_k_llamadas() -> None:
    fechas = [FECHA_REFERENCIA - timedelta(days=d) for d in (1, 5, 10, 20)]  # K = 4
    gastos = [
        gasto(id=f"g_{i}", monto=str(1000 + i), moneda="CLP", categoria="food", fecha=fechas[i % 4])
        for i in range(30)  # N = 30
    ]
    espia = ProveedorEspia()
    reporte = ejecutar(espia, *gastos)

    assert sum(espia.llamadas.values()) == 4
    assert set(espia.llamadas) == set(fechas)
    assert all(n == 1 for n in espia.llamadas.values())
    assert reporte.tasas.consultas == 4
    assert reporte.tasas.fechas_unicas == 4
    assert len(reporte.resultados) == 30


def test_gastos_en_moneda_base_no_consultan_tasas() -> None:
    espia = ProveedorEspia()
    gastos = [gasto(id=f"g_{i}", monto="10", moneda="USD", dias=i) for i in range(10)]
    reporte = ejecutar(espia, *gastos)
    assert sum(espia.llamadas.values()) == 0
    assert reporte.tasas.fechas_unicas == 10 and reporte.tasas.consultas == 0


def test_solo_se_consultan_las_fechas_con_moneda_extranjera() -> None:
    espia = ProveedorEspia()
    d1, d2 = FECHA_REFERENCIA - timedelta(days=1), FECHA_REFERENCIA - timedelta(days=2)
    ejecutar(
        espia,
        gasto(id="a", moneda="USD", fecha=d1),
        gasto(id="b", moneda="EUR", fecha=d2, monto="1"),
        gasto(id="c", moneda="MXN", fecha=d2, monto="2"),
    )
    assert dict(espia.llamadas) == {d2: 1}


# --- Fallas del proveedor -----------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        ErrorProveedorTasas("HTTP 503"),
        ErrorFechaProveedor("not_available"),
        TasasNoDisponibles(date(2026, 10, 1), "sin datos"),
    ],
)
def test_falla_puntual_de_una_fecha_deja_sus_gastos_pendientes(error: Exception) -> None:
    mala, buena = FECHA_REFERENCIA - timedelta(days=3), FECHA_REFERENCIA - timedelta(days=4)
    espia = ProveedorEspia(fallas={mala: error})
    reporte = ejecutar(
        espia,
        gasto(id="g_mala_1", monto="1000", moneda="CLP", categoria="food", fecha=mala),
        gasto(id="g_mala_2", monto="2000", moneda="CLP", categoria="food", fecha=mala),
        gasto(id="g_buena", monto="1000", moneda="CLP", categoria="food", fecha=buena),
    )
    por_id = {r.validacion.gasto_id: r for r in reporte.resultados}
    for gid in ("g_mala_1", "g_mala_2"):
        assert por_id[gid].estado is Estado.PENDIENTE
        assert por_id[gid].codigos == ("TASA_NO_DISPONIBLE",)
        assert por_id[gid].monto_base is None
    assert por_id["g_buena"].estado is Estado.APROBADO
    assert espia.llamadas[mala] == 1  # la fecha fallida no se reintenta por cada gasto
    assert set(reporte.tasas.fallas) == {mala}


@pytest.mark.parametrize(
    "error",
    [
        ErrorCredencialesProveedor("401"),
        ErrorPlanNoPermitido("not_allowed"),
        CuotaExcedida("429"),
        AccesoRestringido("access_restricted"),
    ],
)
def test_falla_fatal_aborta_el_lote(error: Exception) -> None:
    # Las fechas se consultan en orden: falla la primera (hace 2 días).
    espia = ProveedorEspia(fallas={FECHA_REFERENCIA - timedelta(days=2): error})
    with pytest.raises(type(error)):
        ejecutar(espia, gasto(moneda="CLP", dias=1), gasto(id="g_2", moneda="CLP", dias=2))
    assert sum(espia.llamadas.values()) == 1  # no sigue gastando cuota


# --- Integración de reglas y anomalías ------------------------------------------------------


def test_anomalias_entran_a_la_resolucion_de_estado() -> None:
    reporte = ejecutar(
        ProveedorEspia(),
        gasto(id="g_1", monto="90", categoria="food", dias=1),
        gasto(id="g_2", monto="90", categoria="food", dias=1),  # duplicado de g_1
        gasto(id="g_3", monto="-20", categoria="software", dias=1),  # negativo
    )
    por_id = {r.validacion.gasto_id: r for r in reporte.resultados}
    assert por_id["g_1"].estado is Estado.APROBADO
    assert por_id["g_2"].estado is Estado.PENDIENTE and por_id["g_2"].codigos == (
        "DUPLICADO_EXACTO",
    )
    assert por_id["g_3"].estado is Estado.RECHAZADO and por_id["g_3"].codigos == ("MONTO_INVALIDO",)


def test_duplicado_que_ademas_viola_una_regla_sigue_rechazado() -> None:
    reporte = ejecutar(
        ProveedorEspia(),
        gasto(id="g_1", monto="200", categoria="food", dias=1),
        gasto(id="g_2", monto="200", categoria="food", dias=1),
    )
    r2 = reporte.resultados[1]
    assert r2.estado is Estado.RECHAZADO
    assert r2.codigos == ("LIMITE_CATEGORIA", "DUPLICADO_EXACTO")


def test_reporte_incluye_filas_invalidas_dias_y_monto_base() -> None:
    invalida = FilaInvalida(5, "monto no numérico: 'abc'", "g_x")
    reporte = ejecutar(
        ProveedorEspia(),
        gasto(id="g_1", monto="90000", moneda="CLP", dias=7),
        invalidas=(invalida,),
    )
    assert reporte.filas_invalidas == (invalida,)
    assert reporte.filas_leidas == 2
    (r,) = reporte.resultados
    assert r.dias_antiguedad == 7
    assert r.monto_base == Decimal("100.00")


def test_conteo_por_estado_incluye_estados_en_cero() -> None:
    reporte = ejecutar(ProveedorEspia(), gasto(dias=1))
    assert reporte.conteo_por_estado() == {
        Estado.APROBADO: 1,
        Estado.PENDIENTE: 0,
        Estado.RECHAZADO: 0,
    }


def test_lote_vacio() -> None:
    reporte = ejecutar(ProveedorEspia())
    assert reporte.resultados == ()
    assert reporte.tasas.consultas == 0


# --- Integración con el CSV real (modo offline) ---------------------------------------------


def test_csv_del_desafio_en_modo_offline() -> None:
    caso = AnalizarLote(
        MotorReglas(reglas_por_defecto()),
        ProveedorTasasFijas(TASAS_EJEMPLO_USD),
        detectores_por_defecto(),
    )
    reporte = caso.ejecutar(
        LectorCsvGastos(RAIZ / "data" / "gastos_historicos.csv"),
        cargar_politica(RAIZ / "config" / "politica.json"),
        date(2026, 10, 26),
    )
    assert reporte.conteo_por_estado() == {
        Estado.APROBADO: 8,
        Estado.PENDIENTE: 17,
        Estado.RECHAZADO: 25,
    }
    assert (reporte.tasas.fechas_unicas, reporte.tasas.consultas) == (25, 9)
    assert reporte.conteo_por_alerta()["DUPLICADO_EXACTO"] == 9
    assert reporte.conteo_por_alerta()["POLITICA_CENTRO_COSTO"] == 4

    por_id = {r.validacion.gasto_id: r.validacion.a_dict() for r in reporte.resultados}
    assert por_id["g_013"] == {
        "gasto_id": "g_013",
        "status": "RECHAZADO",
        "alertas": [
            {
                "codigo": "POLITICA_CENTRO_COSTO",
                "mensaje": "El C.C. 'core_engineering' no puede reportar 'food'.",
            }
        ],
    }
    assert por_id["g_014"]["alertas"] == [
        {"codigo": "LIMITE_ANTIGUEDAD", "mensaje": "Gasto excede los 30 días. Requiere revisión."}
    ]
    assert por_id["g_045"]["status"] == "APROBADO"  # 100 USD exactos: borde inclusivo
    assert por_id["g_043"]["status"] == "PENDIENTE"  # copia de g_042


# --- Moneda sin tasa: hallazgo independiente de la categoría --------------------------------


class ProveedorSinEur:
    """Tiene tasas para todas las fechas, pero no incluye EUR."""

    def obtener_tasas(self, fecha: date) -> Mapping[str, Decimal]:
        return {k: v for k, v in TASAS_PRUEBA.items() if k != "EUR"}


def test_moneda_sin_tasa_en_categoria_sin_limite_no_queda_aprobada() -> None:
    # 'software' no tiene límite: antes la regla de categoría no aplicaba, el error de
    # conversión se descartaba y el gasto (reciente) quedaba APROBADO sin alertas.
    reporte = ejecutar(
        ProveedorSinEur(), gasto(id="g_eur", monto="500", moneda="EUR", categoria="software")
    )
    (r,) = reporte.resultados
    assert r.estado is Estado.PENDIENTE
    assert r.codigos == ("TASA_NO_DISPONIBLE",)
    assert r.monto_base is None


def test_moneda_sin_tasa_en_categoria_con_limite_alerta_una_sola_vez() -> None:
    reporte = ejecutar(
        ProveedorSinEur(), gasto(id="g_eur", monto="50", moneda="EUR", categoria="food")
    )
    (r,) = reporte.resultados
    assert r.estado is Estado.PENDIENTE
    assert r.codigos == ("TASA_NO_DISPONIBLE",)


def test_moneda_sin_tasa_no_salva_a_un_gasto_rechazado_por_otra_regla() -> None:
    reporte = ejecutar(
        ProveedorSinEur(),
        gasto(id="g_eur", monto="50", moneda="EUR", categoria="software", dias=90),
    )
    (r,) = reporte.resultados
    assert r.estado is Estado.RECHAZADO
    assert r.codigos == ("LIMITE_ANTIGUEDAD", "TASA_NO_DISPONIBLE")


def test_reporte_cuenta_los_montos_sin_tasa() -> None:
    reporte = ejecutar(
        ProveedorSinEur(),
        gasto(id="g_1", monto="500", moneda="EUR", categoria="software"),
        gasto(id="g_2", monto="40", moneda="USD", categoria="software"),
    )
    assert reporte.sin_monto_base() == 1
