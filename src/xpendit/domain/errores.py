"""Excepciones propias del dominio.

Todas heredan de :class:`XpenditError` para que la CLI pueda capturarlas en un solo
lugar y mostrar un mensaje claro (sin stack trace). Ningún mensaje incluye secretos.
"""

from __future__ import annotations

from datetime import date


class XpenditError(Exception):
    """Raíz de todas las excepciones controladas de la aplicación."""


class PoliticaInvalida(XpenditError):
    """La política de gastos no existe, no es JSON válido o no cumple el esquema."""


class FilaInvalida(XpenditError):
    """Una fila del lote no se pudo convertir en un gasto válido.

    En el analizador de lotes no se propaga: se registra y se sigue con la siguiente fila.
    """

    def __init__(self, numero_linea: int, motivo: str, gasto_id: str | None = None) -> None:
        self.numero_linea = numero_linea
        self.motivo = motivo
        self.gasto_id = gasto_id
        ident = f" ({gasto_id})" if gasto_id else ""
        super().__init__(f"Línea {numero_linea}{ident}: {motivo}")


class ArchivoInvalido(XpenditError):
    """El archivo de entrada completo es inutilizable (no existe, faltan columnas, etc.)."""


class ConfiguracionInvalida(XpenditError):
    """Falta configuración obligatoria (p. ej. la variable de entorno OXR_APP_ID)."""


# --- Conversión de moneda -------------------------------------------------------------


class ConversionNoDisponible(XpenditError):
    """No se pudo convertir un monto porque falta información de tasas.

    Es un caso de negocio (el gasto queda al menos PENDIENTE para revisión humana), no una
    falla de infraestructura.
    """


class MonedaNoSoportada(ConversionNoDisponible):
    """Las tasas de la fecha existen, pero no incluyen la moneda pedida."""

    def __init__(self, moneda: str, fecha: date) -> None:
        self.moneda = moneda
        self.fecha = fecha
        super().__init__(f"No hay tasa para la moneda '{moneda}' en la fecha {fecha.isoformat()}.")


class TasasNoDisponibles(ConversionNoDisponible):
    """No hay tasas para la fecha (el proveedor falló o la fecha no fue precargada)."""

    def __init__(self, fecha: date, motivo: str | None = None) -> None:
        self.fecha = fecha
        self.motivo = motivo
        detalle = f": {motivo}" if motivo else "."
        super().__init__(f"No hay tasas de cambio para la fecha {fecha.isoformat()}{detalle}")


# --- Proveedor de tasas (infraestructura) ---------------------------------------------


class ErrorProveedorTasas(XpenditError):
    """Falla al obtener tasas desde un proveedor externo (red, HTTP, respuesta malformada)."""


class ErrorFatalProveedor(ErrorProveedorTasas):
    """Falla que afecta a todas las fechas por igual: no tiene sentido seguir consultando.

    El analizador de lotes aborta ante estas fallas en vez de marcar cada fecha como
    no disponible.
    """


class ErrorCredencialesProveedor(ErrorFatalProveedor):
    """Falta el App ID o OXR no lo reconoce (``missing_app_id``/``invalid_app_id``)."""


class ErrorPlanNoPermitido(ErrorFatalProveedor):
    """El plan contratado no permite la ruta o función pedida (OXR: ``not_allowed``).

    No es un problema de cuota ni transitorio: reintentar no lo arregla.
    """


class CuotaExcedida(ErrorFatalProveedor):
    """Demasiadas solicitudes: 429 que persiste tras los reintentos."""


class AccesoRestringido(ErrorFatalProveedor):
    """OXR restringió el acceso de la cuenta (``access_restricted``).

    Puede deberse a uso excesivo u otro motivo, que OXR indica en ``description``: no se
    asume que sea cuota agotada.
    """


class ErrorFechaProveedor(ErrorProveedorTasas):
    """El proveedor no tiene tasas para esa fecha (OXR: ``invalid_date``/``not_available``).

    Afecta solo a esa fecha: el lote la registra como falla y sigue con las demás.
    """
