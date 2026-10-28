"""Política de gastos: modelo inmutable + validación desde un diccionario (JSON ya parseado).

La validación vive en el dominio (es conocimiento del negocio: p. ej. que
``pendiente_hasta >= aprobado_hasta``); leer el archivo es tarea de un adaptador.
Los errores acumulan todas las rutas inválidas para que el mensaje sea accionable.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

from xpendit.domain.errores import PoliticaInvalida

_PATRON_MONEDA = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True, slots=True)
class LimiteAntiguedad:
    """Días de antigüedad: ``<= pendiente_dias`` aprueba, ``<= rechazado_dias`` deja
    pendiente, más allá rechaza."""

    pendiente_dias: int
    rechazado_dias: int


@dataclass(frozen=True, slots=True)
class LimiteCategoria:
    """Montos en la moneda base: ``<= aprobado_hasta`` aprueba, ``<= pendiente_hasta``
    deja pendiente, más allá rechaza."""

    aprobado_hasta: Decimal
    pendiente_hasta: Decimal


@dataclass(frozen=True, slots=True)
class ReglaCentroCostoConfig:
    """Un centro de costo que no puede rendir una categoría."""

    cost_center: str
    categoria_prohibida: str


@dataclass(frozen=True, slots=True)
class Politica:
    moneda_base: str
    limite_antiguedad: LimiteAntiguedad | None = None
    limites_por_categoria: Mapping[str, LimiteCategoria] = field(
        default_factory=lambda: MappingProxyType({})
    )
    reglas_centro_costo: tuple[ReglaCentroCostoConfig, ...] = ()

    @classmethod
    def desde_dict(cls, datos: Any) -> Politica:
        """Construye y valida una política. Lanza :class:`PoliticaInvalida` con todos los
        problemas encontrados."""
        return _ValidadorPolitica().construir(datos)


class _ValidadorPolitica:
    def __init__(self) -> None:
        self.errores: list[str] = []

    def construir(self, datos: Any) -> Politica:
        if not isinstance(datos, Mapping):
            raise PoliticaInvalida("La política debe ser un objeto JSON.")

        moneda_base = self._moneda(datos.get("moneda_base"), "moneda_base")
        antiguedad = self._antiguedad(datos.get("limite_antiguedad"))
        limites = self._limites(datos.get("limites_por_categoria"))
        reglas_cc = self._reglas_cc(datos.get("reglas_centro_costo"))

        if self.errores:
            detalle = "\n".join(f"  - {e}" for e in self.errores)
            raise PoliticaInvalida(f"Política inválida:\n{detalle}")
        assert moneda_base is not None
        return Politica(
            moneda_base=moneda_base,
            limite_antiguedad=antiguedad,
            limites_por_categoria=MappingProxyType(limites),
            reglas_centro_costo=tuple(reglas_cc),
        )

    # --- secciones -----------------------------------------------------------------

    def _moneda(self, valor: Any, ruta: str) -> str | None:
        if not isinstance(valor, str) or not _PATRON_MONEDA.match(valor.strip().upper()):
            self.errores.append(
                f"{ruta}: se esperaba un código ISO 4217 de 3 letras (p. ej. 'USD')."
            )
            return None
        return valor.strip().upper()

    def _antiguedad(self, valor: Any) -> LimiteAntiguedad | None:
        if valor is None:
            return None
        if not isinstance(valor, Mapping):
            self.errores.append("limite_antiguedad: se esperaba un objeto.")
            return None
        pendiente = self._entero_no_negativo(
            valor.get("pendiente_dias"), "limite_antiguedad.pendiente_dias"
        )
        rechazado = self._entero_no_negativo(
            valor.get("rechazado_dias"), "limite_antiguedad.rechazado_dias"
        )
        if pendiente is None or rechazado is None:
            return None
        if rechazado < pendiente:
            self.errores.append("limite_antiguedad: rechazado_dias debe ser >= pendiente_dias.")
            return None
        return LimiteAntiguedad(pendiente, rechazado)

    def _limites(self, valor: Any) -> dict[str, LimiteCategoria]:
        if valor is None:
            return {}
        if not isinstance(valor, Mapping):
            self.errores.append(
                "limites_por_categoria: se esperaba un objeto {categoria: limites}."
            )
            return {}
        limites: dict[str, LimiteCategoria] = {}
        for categoria, cfg in valor.items():
            ruta = f"limites_por_categoria.{categoria}"
            if not isinstance(cfg, Mapping):
                self.errores.append(f"{ruta}: se esperaba un objeto.")
                continue
            aprobado = self._monto_no_negativo(cfg.get("aprobado_hasta"), f"{ruta}.aprobado_hasta")
            pendiente = self._monto_no_negativo(
                cfg.get("pendiente_hasta"), f"{ruta}.pendiente_hasta"
            )
            if aprobado is None or pendiente is None:
                continue
            if pendiente < aprobado:
                self.errores.append(f"{ruta}: pendiente_hasta debe ser >= aprobado_hasta.")
                continue
            limites[str(categoria).strip().lower()] = LimiteCategoria(aprobado, pendiente)
        return limites

    def _reglas_cc(self, valor: Any) -> list[ReglaCentroCostoConfig]:
        if valor is None:
            return []
        if not isinstance(valor, list):
            self.errores.append("reglas_centro_costo: se esperaba una lista.")
            return []
        reglas: list[ReglaCentroCostoConfig] = []
        for i, cfg in enumerate(valor):
            ruta = f"reglas_centro_costo[{i}]"
            if not isinstance(cfg, Mapping):
                self.errores.append(f"{ruta}: se esperaba un objeto.")
                continue
            cc = cfg.get("cost_center")
            cat = cfg.get("categoria_prohibida")
            if not isinstance(cc, str) or not cc.strip():
                self.errores.append(f"{ruta}.cost_center: se esperaba un texto no vacío.")
                continue
            if not isinstance(cat, str) or not cat.strip():
                self.errores.append(f"{ruta}.categoria_prohibida: se esperaba un texto no vacío.")
                continue
            reglas.append(ReglaCentroCostoConfig(cc.strip().lower(), cat.strip().lower()))
        return reglas

    # --- primitivas ----------------------------------------------------------------

    def _entero_no_negativo(self, valor: Any, ruta: str) -> int | None:
        if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
            self.errores.append(f"{ruta}: se esperaba un entero >= 0.")
            return None
        return valor

    def _monto_no_negativo(self, valor: Any, ruta: str) -> Decimal | None:
        # bool es subclase de int: se excluye explícitamente. float se pasa por str para
        # no arrastrar la representación binaria (0.1 -> Decimal('0.1')).
        if isinstance(valor, bool) or not isinstance(valor, (int, float, Decimal, str)):
            self.errores.append(f"{ruta}: se esperaba un número >= 0.")
            return None
        try:
            monto = Decimal(str(valor))
        except InvalidOperation:
            self.errores.append(f"{ruta}: '{valor}' no es un número.")
            return None
        if not monto.is_finite() or monto < 0:
            self.errores.append(f"{ruta}: se esperaba un número finito >= 0.")
            return None
        return monto
