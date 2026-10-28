"""Tests del motor completo con la política del enunciado."""

import json
from datetime import date
from decimal import Decimal

from tests.factories import contexto, empleado, gasto, politica
from xpendit.domain import (
    ContextoEvaluacion,
    Empleado,
    Estado,
    Gasto,
    MotorReglas,
    ResultadoRegla,
    reglas_por_defecto,
)

motor = MotorReglas(reglas_por_defecto())


def test_ejemplo_del_enunciado_pendiente_por_antiguedad() -> None:
    g = gasto(id="g_123", monto="50", categoria="food", dias=45)
    resultado = motor.evaluar(g, empleado(cost_center="sales_team"), contexto())
    assert resultado.a_dict() == {
        "gasto_id": "g_123",
        "status": "PENDIENTE",
        "alertas": [
            {
                "codigo": "LIMITE_ANTIGUEDAD",
                "mensaje": "Gasto excede los 30 días. Requiere revisión.",
            }
        ],
    }


def test_ejemplo_del_enunciado_rechazado_por_centro_costo() -> None:
    g = gasto(id="g_124", monto="50", categoria="food", dias=3)
    resultado = motor.evaluar(g, empleado(cost_center="core_engineering"), contexto())
    assert resultado.a_dict() == {
        "gasto_id": "g_124",
        "status": "RECHAZADO",
        "alertas": [
            {
                "codigo": "POLITICA_CENTRO_COSTO",
                "mensaje": "El C.C. 'core_engineering' no puede reportar 'food'.",
            }
        ],
    }


def test_gasto_que_cumple_todo_queda_aprobado_sin_alertas() -> None:
    g = gasto(id="g_125", monto="80", categoria="food", dias=10)
    assert motor.evaluar(g, empleado(), contexto()).a_dict() == {
        "gasto_id": "g_125",
        "status": "APROBADO",
        "alertas": [],
    }


def test_categoria_sin_limite_y_reciente_queda_aprobada_por_antiguedad() -> None:
    g = gasto(monto="99999", categoria="software", dias=1)
    assert motor.evaluar(g, empleado(), contexto()).estado is Estado.APROBADO


def test_conserva_las_alertas_de_todas_las_reglas_en_orden() -> None:
    g = gasto(monto="120", categoria="food", dias=45)
    resultado = motor.evaluar(g, empleado(cost_center="core_engineering"), contexto())
    assert resultado.estado is Estado.RECHAZADO
    assert [a.codigo for a in resultado.alertas] == [
        "LIMITE_ANTIGUEDAD",
        "LIMITE_CATEGORIA",
        "POLITICA_CENTRO_COSTO",
    ]


def test_rechazado_gana_sobre_pendiente() -> None:
    g = gasto(monto="120", categoria="food", dias=61)  # límite: PENDIENTE, antigüedad: RECHAZADO
    assert motor.evaluar(g, empleado(), contexto()).estado is Estado.RECHAZADO


def test_pendiente_gana_sobre_aprobado() -> None:
    g = gasto(monto="120", categoria="food", dias=1)  # antigüedad: APROBADO, límite: PENDIENTE
    assert motor.evaluar(g, empleado(), contexto()).estado is Estado.PENDIENTE


def test_si_ninguna_regla_aplica_queda_pendiente_sin_alertas() -> None:
    pol = politica(limite_antiguedad=None, limites_por_categoria={}, reglas_centro_costo=[])
    resultado = motor.evaluar(gasto(), empleado(), contexto(pol=pol))
    assert resultado.a_dict() == {"gasto_id": "g_123", "status": "PENDIENTE", "alertas": []}


def test_motor_sin_reglas_deja_todo_pendiente() -> None:
    assert MotorReglas([]).evaluar(gasto(), empleado(), contexto()).estado is Estado.PENDIENTE


def test_hallazgos_adicionales_entran_a_la_resolucion() -> None:
    extra = ResultadoRegla.pendiente("DUPLICADO_EXACTO", "Posible duplicado.")
    resultado = motor.evaluar(gasto(dias=1), empleado(), contexto(), hallazgos_adicionales=[extra])
    assert resultado.estado is Estado.PENDIENTE
    assert [a.codigo for a in resultado.alertas] == ["DUPLICADO_EXACTO"]


def test_agregar_una_regla_nueva_no_requiere_tocar_el_motor() -> None:
    """Open/Closed: una regla nueva es solo una clase más en la lista."""

    class ReglaFinDeSemana:
        nombre = "fin_de_semana"

        def evaluar(
            self, gasto: Gasto, empleado: Empleado, contexto: ContextoEvaluacion
        ) -> ResultadoRegla | None:
            if gasto.fecha.weekday() >= 5:
                return ResultadoRegla.pendiente("GASTO_FIN_DE_SEMANA", "Gasto en fin de semana.")
            return None

    motor_extendido = MotorReglas([*reglas_por_defecto(), ReglaFinDeSemana()])
    sabado = gasto(fecha=date(2026, 10, 24), categoria="software")
    lunes = gasto(fecha=date(2026, 10, 19), categoria="software")

    assert motor.evaluar(sabado, empleado(), contexto()).estado is Estado.APROBADO
    r_sabado = motor_extendido.evaluar(sabado, empleado(), contexto())
    assert r_sabado.estado is Estado.PENDIENTE
    assert r_sabado.alertas[0].codigo == "GASTO_FIN_DE_SEMANA"
    assert motor_extendido.evaluar(lunes, empleado(), contexto()).estado is Estado.APROBADO


def test_resolvedor_es_inyectable() -> None:
    class SiempreRechaza:
        def resolver(self, resultados: object) -> Estado:
            return Estado.RECHAZADO

    m = MotorReglas(reglas_por_defecto(), resolvedor=SiempreRechaza())
    assert m.evaluar(gasto(dias=1), empleado(), contexto()).estado is Estado.RECHAZADO


def test_resultado_es_serializable_a_json() -> None:
    g = gasto(monto="120", categoria="food", dias=45)
    texto = json.dumps(motor.evaluar(g, empleado(), contexto()).a_dict(), ensure_ascii=False)
    assert json.loads(texto)["status"] == "PENDIENTE"


def test_gasto_en_moneda_base_no_consulta_tasas() -> None:
    llamadas: list[date] = []

    class ProveedorEspia:
        def obtener_tasas(self, fecha: date) -> dict[str, Decimal]:
            llamadas.append(fecha)
            return {"USD": Decimal("1")}

    motor.evaluar(gasto(categoria="food"), empleado(), contexto(proveedor=ProveedorEspia()))
    assert llamadas == []
