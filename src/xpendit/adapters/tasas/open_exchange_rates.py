"""Adaptador HTTP del puerto ProveedorTasas para Open Exchange Rates (OXR).

Notas del plan gratuito:

- La base es siempre USD (no se envía ``base``); el conversor usa tasas cruzadas.
- Endpoint histórico: ``GET /api/historical/YYYY-MM-DD.json``.
- ~1000 solicitudes/mes: por eso el lote pide una vez por fecha y hay caché en disco.

Manejo de secretos: el ``app_id`` viaja en el header ``Authorization: Token <app_id>``
(método documentado por OXR, puesto por un objeto ``auth=``), **no** en la query string. Lo
que sí se garantiza (y está probado): no va en la URL, no aparece en los logs de ``urllib3``
en nivel DEBUG (que registran la URL completa) y no aparece en nuestros mensajes de error,
logs, ``repr`` ni trazas (los textos de error de OXR se enmascaran por si lo contienen y las
excepciones originales no se encadenan). Lo que no se puede garantizar: que no lo vea un
proxy, un APM u otra herramienta que registre los headers de la solicitud.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import requests
from requests.auth import AuthBase

from xpendit.domain.errores import (
    AccesoRestringido,
    ConfiguracionInvalida,
    CuotaExcedida,
    ErrorCredencialesProveedor,
    ErrorFechaProveedor,
    ErrorPlanNoPermitido,
    ErrorProveedorTasas,
)

logger = logging.getLogger(__name__)

URL_BASE = "https://openexchangerates.org/api"

# Valores de ``message`` de la tabla de errores de OXR
# (https://docs.openexchangerates.org/reference/errors). Ninguno se reintenta.
_CREDENCIALES = frozenset({"missing_app_id", "invalid_app_id"})
_PLAN = frozenset({"not_allowed"})
_ACCESO_RESTRINGIDO = frozenset({"access_restricted"})
_FECHA = frozenset({"invalid_date", "not_available"})


_SUGERENCIA_CUOTA = (
    "El plan gratuito permite ~1000 solicitudes/mes; usa la caché en disco o --offline."
)


class RespuestaHttp(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    @property
    def headers(self) -> Mapping[str, str]: ...


class SesionHttp(Protocol):
    """Lo mínimo que se usa de ``requests.Session``; permite inyectar un doble en tests."""

    def get(self, url: str, *, auth: AuthBase, timeout: float) -> RespuestaHttp: ...


def enmascarar(secreto: str) -> str:
    """``'abcdef123456' -> '********3456'``; secretos cortos se ocultan completos."""
    if len(secreto) <= 8:
        return "*" * len(secreto)
    return "*" * (len(secreto) - 4) + secreto[-4:]


class AutenticacionToken(AuthBase):
    """Pone ``Authorization: Token <app_id>`` en cada solicitud.

    Se pasa como ``auth=`` y no como ``headers=``: con ``trust_env=True`` (el valor por
    omisión de ``requests.Session``) requests reemplaza un header ``Authorization`` explícito
    por las credenciales de ``.netrc`` si hay una entrada para el host; un objeto ``auth=``
    tiene prioridad sobre ``.netrc``.
    """

    def __init__(self, app_id: str) -> None:
        self._app_id = app_id

    def __call__(self, solicitud: requests.PreparedRequest) -> requests.PreparedRequest:
        solicitud.headers["Authorization"] = f"Token {self._app_id}"
        return solicitud

    def __repr__(self) -> str:
        return f"AutenticacionToken(app_id={enmascarar(self._app_id)!r})"


class ClienteOpenExchangeRates:
    def __init__(
        self,
        app_id: str,
        *,
        sesion: SesionHttp | None = None,
        url_base: str = URL_BASE,
        timeout: float = 10.0,
        max_intentos: int = 3,
        backoff_inicial: float = 0.5,
        espera_maxima: float = 30.0,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        app_id = (app_id or "").strip()
        if not app_id:
            raise ConfiguracionInvalida("Falta el App ID de Open Exchange Rates (OXR_APP_ID).")
        if max_intentos < 1:
            raise ValueError("max_intentos debe ser >= 1")
        self._app_id = app_id
        self._auth = AutenticacionToken(app_id)
        self._sesion: SesionHttp = sesion if sesion is not None else requests.Session()
        self._url_base = url_base.rstrip("/")
        self._timeout = timeout
        self._max_intentos = max_intentos
        self._backoff_inicial = backoff_inicial
        self._espera_maxima = espera_maxima
        self._dormir = dormir
        self.solicitudes_http = 0

    def __repr__(self) -> str:
        app_id = enmascarar(self._app_id)
        return f"ClienteOpenExchangeRates(app_id={app_id!r}, url_base={self._url_base!r})"

    # --- puerto ProveedorTasas -----------------------------------------------------

    def obtener_tasas(self, fecha: date) -> dict[str, Decimal]:
        ruta = f"/historical/{fecha.isoformat()}.json"
        ultimo_error: ErrorProveedorTasas | None = None

        for intento in range(1, self._max_intentos + 1):
            logger.debug("GET %s (intento %d/%d)", ruta, intento, self._max_intentos)
            espera = self._backoff_inicial * 2 ** (intento - 1)
            try:
                self.solicitudes_http += 1
                respuesta = self._sesion.get(
                    self._url_base + ruta,
                    auth=self._auth,
                    timeout=self._timeout,
                )
            except requests.Timeout:
                ultimo_error = ErrorProveedorTasas(
                    f"Tiempo de espera agotado ({self._timeout:g} s) al pedir las tasas del "
                    f"{fecha.isoformat()} a Open Exchange Rates."
                )
            except requests.RequestException as exc:
                # El mensaje de requests puede traer detalles de la conexión: solo se usa el
                # tipo, para no exponer nada que no controlamos.
                ultimo_error = ErrorProveedorTasas(
                    f"Error de red ({type(exc).__name__}) al pedir las tasas del "
                    f"{fecha.isoformat()} a Open Exchange Rates."
                )
            else:
                if respuesta.status_code == 200:
                    return self._parsear(respuesta.text, fecha)
                ultimo_error, reintentable = self._clasificar_error(respuesta, fecha)
                if not reintentable:
                    raise ultimo_error
                espera = self._retry_after(respuesta) or espera

            if intento < self._max_intentos:
                espera = min(espera, self._espera_maxima)
                logger.warning(
                    "%s Reintento %d/%d en %.1f s.",
                    ultimo_error,
                    intento + 1,
                    self._max_intentos,
                    espera,
                )
                self._dormir(espera)

        assert ultimo_error is not None
        raise ultimo_error

    # --- detalles ------------------------------------------------------------------

    def _parsear(self, texto: str, fecha: date) -> dict[str, Decimal]:
        # parse_float=Decimal: las tasas nunca pasan por float (sin pérdida de precisión).
        try:
            datos = json.loads(texto, parse_float=Decimal, parse_int=Decimal)
        except ValueError:
            raise ErrorProveedorTasas(
                f"Respuesta malformada de Open Exchange Rates para {fecha.isoformat()}: no es JSON."
            ) from None

        tasas = datos.get("rates") if isinstance(datos, dict) else None
        if not isinstance(tasas, dict) or not tasas:
            raise ErrorProveedorTasas(
                f"Respuesta malformada de Open Exchange Rates para {fecha.isoformat()}: "
                "falta el objeto 'rates'."
            )
        resultado: dict[str, Decimal] = {}
        for moneda, valor in tasas.items():
            tasa = _a_decimal(valor)
            if tasa is None or tasa <= 0:
                raise ErrorProveedorTasas(
                    f"Respuesta malformada de Open Exchange Rates para {fecha.isoformat()}: "
                    f"tasa inválida para '{moneda}'."
                )
            resultado[str(moneda).upper()] = tasa
        return resultado

    def _clasificar_error(
        self, respuesta: RespuestaHttp, fecha: date
    ) -> tuple[ErrorProveedorTasas, bool]:
        """Traduce una respuesta de error a una excepción y dice si vale la pena reintentar.

        Primero manda el ``message`` del cuerpo JSON (identifica el caso sin ambigüedad: p. ej.
        ``not_allowed`` es un problema de plan aunque llegue con un status 429). Si no hay un
        ``message`` conocido se usa el status HTTP; en particular, un 401 es siempre un
        problema de credenciales, venga con el ``message`` que venga. Se reintenta únicamente
        lo transitorio: 5xx y 429 sin ``message`` conocido (los errores de red se tratan
        aparte).
        """
        status = respuesta.status_code
        codigo, descripcion = self._detalle_error(respuesta.text)
        detalle = f"HTTP {status}" + (f" [{codigo}]" if codigo else "")
        clave = codigo.lower()

        if clave in _ACCESO_RESTRINGIDO:
            motivo = (
                f"Motivo indicado por OXR: {descripcion}"
                if descripcion
                else "OXR no indicó el motivo (puede ser uso excesivo u otro)."
            )
            return AccesoRestringido(
                f"Open Exchange Rates respondió acceso restringido ({detalle}). {motivo} "
                "Reintentar no lo arregla; revisa el estado de tu cuenta en OXR."
            ), False

        if descripcion:
            detalle += f" {descripcion}"
        if clave in _PLAN:
            return ErrorPlanNoPermitido(
                f"Tu plan de Open Exchange Rates no permite esta ruta o función ({detalle}). "
                "El plan gratuito incluye el endpoint histórico con base USD; reintentar no "
                "lo arregla."
            ), False
        if clave in _FECHA:
            return ErrorFechaProveedor(
                f"Open Exchange Rates no tiene tasas para el {fecha.isoformat()} ({detalle})."
            ), False
        if clave in _CREDENCIALES or status == 401:
            return ErrorCredencialesProveedor(
                f"Open Exchange Rates rechazó el App ID ({detalle}). "
                "Revisa OXR_APP_ID en tu archivo .env."
            ), False
        if status == 429:
            return CuotaExcedida(
                f"Open Exchange Rates rechazó la solicitud por exceso de uso ({detalle}). "
                f"{_SUGERENCIA_CUOTA}"
            ), True
        if status == 403:
            return ErrorCredencialesProveedor(
                f"Open Exchange Rates denegó el acceso ({detalle}). "
                "Revisa OXR_APP_ID y los permisos de tu plan."
            ), False
        return ErrorProveedorTasas(
            f"Open Exchange Rates respondió {detalle} al pedir las tasas del {fecha.isoformat()}."
        ), status >= 500

    def _detalle_error(self, texto: str) -> tuple[str, str]:
        """Extrae ``message``/``description`` del cuerpo de error de OXR (si es JSON)."""
        try:
            cuerpo: Any = json.loads(texto)
        except ValueError:
            return "", ""
        if not isinstance(cuerpo, dict):
            return "", ""
        codigo = self._sin_secreto(str(cuerpo.get("message", "")))
        descripcion = self._sin_secreto(str(cuerpo.get("description", "")))
        return codigo, descripcion

    def _retry_after(self, respuesta: RespuestaHttp) -> float | None:
        valor = respuesta.headers.get("Retry-After")
        try:
            return max(0.0, float(valor)) if valor is not None else None
        except ValueError:
            return None

    def _sin_secreto(self, texto: str) -> str:
        return texto.replace(self._app_id, enmascarar(self._app_id))


def _a_decimal(valor: Any) -> Decimal | None:
    if isinstance(valor, bool):
        return None
    try:
        numero = Decimal(str(valor))
    except InvalidOperation:
        return None
    return numero if numero.is_finite() else None
