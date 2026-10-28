"""Constructores de objetos de prueba con valores por defecto razonables."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from xpendit.adapters.tasas import ProveedorTasasFijas
from xpendit.domain import ContextoEvaluacion, ConversorMoneda, Empleado, Gasto, Politica
from xpendit.domain.tasas import ProveedorTasas

FECHA_REFERENCIA = date(2026, 10, 26)

POLITICA_EJEMPLO: dict[str, Any] = {
    "moneda_base": "USD",
    "limite_antiguedad": {"pendiente_dias": 30, "rechazado_dias": 60},
    "limites_por_categoria": {
        "food": {"aprobado_hasta": 100, "pendiente_hasta": 150},
        "transport": {"aprobado_hasta": 200, "pendiente_hasta": 200},
    },
    "reglas_centro_costo": [{"cost_center": "core_engineering", "categoria_prohibida": "food"}],
}

TASAS_PRUEBA: dict[str, Decimal] = {
    "USD": Decimal("1"),
    "CLP": Decimal("900"),
    "MXN": Decimal("17.5"),
    "EUR": Decimal("0.92"),
}


def politica(**cambios: Any) -> Politica:
    datos = {**POLITICA_EJEMPLO, **cambios}
    return Politica.desde_dict(datos)


def hace_dias(dias: int, referencia: date = FECHA_REFERENCIA) -> date:
    return referencia - timedelta(days=dias)


def gasto(
    *,
    id: str = "g_123",
    empleado_id: str = "e_001",
    monto: str | int | Decimal = "50",
    moneda: str = "USD",
    fecha: date | None = None,
    dias: int | None = None,
    categoria: str = "software",
) -> Gasto:
    if fecha is None:
        fecha = hace_dias(5 if dias is None else dias)
    return Gasto(
        id=id,
        empleado_id=empleado_id,
        monto=Decimal(str(monto)),
        moneda=moneda,
        fecha=fecha,
        categoria=categoria,
    )


def empleado(*, id: str = "e_001", cost_center: str = "sales_team") -> Empleado:
    return Empleado(id=id, nombre="Ana", apellido="Reyes", cost_center=cost_center)


def contexto(
    *,
    pol: Politica | None = None,
    fecha_referencia: date = FECHA_REFERENCIA,
    tasas: Mapping[str, Decimal] | None = None,
    proveedor: ProveedorTasas | None = None,
) -> ContextoEvaluacion:
    if proveedor is None:
        proveedor = ProveedorTasasFijas(TASAS_PRUEBA if tasas is None else tasas)
    return ContextoEvaluacion(
        politica=pol or politica(),
        fecha_referencia=fecha_referencia,
        conversor=ConversorMoneda(proveedor),
    )
