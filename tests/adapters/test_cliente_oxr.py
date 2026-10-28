"""Cliente de Open Exchange Rates probado sin red: se inyecta una sesión HTTP falsa."""

from __future__ import annotations

import json
import logging
import traceback
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
import requests
from requests.auth import AuthBase

from xpendit.adapters.tasas import ClienteOpenExchangeRates
from xpendit.adapters.tasas.open_exchange_rates import AutenticacionToken, enmascarar
from xpendit.domain import ConversorMoneda
from xpendit.domain.errores import (
    AccesoRestringido,
    ConfiguracionInvalida,
    CuotaExcedida,
    ErrorCredencialesProveedor,
    ErrorFatalProveedor,
    ErrorFechaProveedor,
    ErrorPlanNoPermitido,
    ErrorProveedorTasas,
    MonedaNoSoportada,
)
from xpendit.domain.tasas import ProveedorTasas

APP_ID = "clave-super-secreta-1234567890"
FECHA = date(2026, 10, 7)


@dataclass
class Respuesta:
    status_code: int
    text: str
    headers: Mapping[str, str] = field(default_factory=dict)


def ok(rates: dict[str, Any] | None = None) -> Respuesta:
    cuerpo = {"base": "USD", "timestamp": 1, "rates": rates or {"USD": 1, "CLP": 950.123456}}
    return Respuesta(200, json.dumps(cuerpo))


def error_oxr(status: int, message: str, **headers: str) -> Respuesta:
    cuerpo = {"error": True, "status": status, "message": message, "description": "Detalle."}
    return Respuesta(status, json.dumps(cuerpo), headers)


class SesionFalsa:
    """Devuelve (o lanza) las respuestas en orden y registra cada llamada."""

    def __init__(self, *respuestas: Respuesta | Exception) -> None:
        self._respuestas = list(respuestas)
        self.llamadas: list[dict[str, Any]] = []

    def get(self, url: str, *, auth: AuthBase, timeout: float) -> Respuesta:
        self.llamadas.append({"url": url, "auth": auth, "timeout": timeout})
        siguiente = self._respuestas.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return siguiente


def cliente(
    *respuestas: Respuesta | Exception, **kwargs: Any
) -> tuple[ClienteOpenExchangeRates, SesionFalsa, list[float]]:
    sesion = SesionFalsa(*respuestas)
    esperas: list[float] = []
    c = ClienteOpenExchangeRates(APP_ID, sesion=sesion, dormir=esperas.append, **kwargs)
    return c, sesion, esperas


# --- Éxito ---------------------------------------------------------------------------


def test_exito_devuelve_tasas_en_decimal_exacto() -> None:
    c, _, esperas = cliente(ok())
    tasas = c.obtener_tasas(FECHA)
    assert tasas == {"USD": Decimal("1"), "CLP": Decimal("950.123456")}
    assert isinstance(tasas["CLP"], Decimal)
    assert esperas == []


def test_usa_el_endpoint_historico_con_app_id_en_header_y_timeout() -> None:
    c, sesion, _ = cliente(ok(), timeout=4.5)
    c.obtener_tasas(FECHA)
    (llamada,) = sesion.llamadas
    # Sin query string: ni app_id (va en el header) ni 'base' (el plan gratuito no lo permite).
    assert llamada["url"] == "https://openexchangerates.org/api/historical/2026-10-07.json"
    # El header lo pone el objeto `auth=` al preparar la solicitud (ver AutenticacionToken).
    preparada = requests.Request("GET", llamada["url"], auth=llamada["auth"]).prepare()
    assert preparada.headers["Authorization"] == f"Token {APP_ID}"
    assert llamada["timeout"] == 4.5


def test_cumple_el_puerto() -> None:
    c, _, _ = cliente()
    assert isinstance(c, ProveedorTasas)


def test_moneda_ausente_en_la_respuesta_lanza_moneda_no_soportada_al_convertir() -> None:
    c, _, _ = cliente(ok({"USD": 1, "CLP": 950}))
    with pytest.raises(MonedaNoSoportada):
        ConversorMoneda(c).convertir(Decimal("100"), "ARS", "USD", FECHA)


def test_conversion_cruzada_con_tasas_del_cliente() -> None:
    c, _, _ = cliente(ok({"USD": 1, "CLP": 950, "EUR": 0.95}))
    assert ConversorMoneda(c).convertir(Decimal("95000"), "CLP", "EUR", FECHA) == Decimal("95.00")


# --- Errores HTTP de OXR --------------------------------------------------------------


def test_401_app_id_invalido_no_se_reintenta() -> None:
    c, sesion, esperas = cliente(error_oxr(401, "invalid_app_id"))
    with pytest.raises(ErrorCredencialesProveedor) as error:
        c.obtener_tasas(FECHA)
    assert "401" in str(error.value) and "invalid_app_id" in str(error.value)
    assert "OXR_APP_ID" in str(error.value)
    assert isinstance(error.value, ErrorFatalProveedor)
    assert len(sesion.llamadas) == 1 and esperas == []


# La tabla de errores de OXR identifica cada caso por el campo `message`; el status HTTP no
# basta (p. ej. `not_allowed` llega con un status de "demasiadas solicitudes" pero es un
# problema de plan, que no se arregla reintentando).


@pytest.mark.parametrize("message", ["missing_app_id", "invalid_app_id"])
@pytest.mark.parametrize("status", [401, 403, 429])
def test_app_id_faltante_o_invalido_es_error_de_credenciales(status: int, message: str) -> None:
    c, sesion, esperas = cliente(error_oxr(status, message))
    with pytest.raises(ErrorCredencialesProveedor, match=message) as error:
        c.obtener_tasas(FECHA)
    assert "OXR_APP_ID" in str(error.value)
    assert len(sesion.llamadas) == 1 and esperas == []


@pytest.mark.parametrize("status", [403, 429])
def test_not_allowed_es_error_de_plan_sin_reintentos(status: int) -> None:
    c, sesion, esperas = cliente(error_oxr(status, "not_allowed"))
    with pytest.raises(ErrorPlanNoPermitido, match="not_allowed") as error:
        c.obtener_tasas(FECHA)
    assert "plan" in str(error.value)
    assert not isinstance(error.value, (CuotaExcedida, ErrorCredencialesProveedor))
    assert isinstance(error.value, ErrorFatalProveedor)  # todas las fechas fallarían igual
    assert len(sesion.llamadas) == 1 and esperas == []


@pytest.mark.parametrize("status", [403, 429])
def test_access_restricted_es_acceso_restringido_sin_reintentos(status: int) -> None:
    c, sesion, esperas = cliente(error_oxr(status, "access_restricted"))
    with pytest.raises(AccesoRestringido, match="access_restricted") as error:
        c.obtener_tasas(FECHA)
    # No se afirma que sea cuota agotada: OXR explica el motivo en `description`.
    assert "acceso restringido" in str(error.value)
    assert "cuota" not in str(error.value).lower()
    assert not isinstance(error.value, CuotaExcedida)
    assert isinstance(error.value, ErrorFatalProveedor)
    assert len(sesion.llamadas) == 1 and esperas == []


def test_access_restricted_muestra_la_description_de_oxr_sin_el_secreto() -> None:
    cuerpo = {
        "error": True,
        "status": 403,
        "message": "access_restricted",
        "description": f"Access restricted for repeated over-use (status: 429). App ID {APP_ID}",
    }
    c, _, _ = cliente(Respuesta(403, json.dumps(cuerpo)))
    with pytest.raises(AccesoRestringido) as error:
        c.obtener_tasas(FECHA)
    assert "repeated over-use" in str(error.value)
    assert APP_ID not in str(error.value)
    assert enmascarar(APP_ID) in str(error.value)


def test_access_restricted_sin_description_no_inventa_el_motivo() -> None:
    cuerpo = {"error": True, "status": 403, "message": "access_restricted"}
    c, _, _ = cliente(Respuesta(403, json.dumps(cuerpo)))
    with pytest.raises(AccesoRestringido, match="no indicó el motivo"):
        c.obtener_tasas(FECHA)


@pytest.mark.parametrize("message", ["invalid_date", "not_available"])
def test_fecha_invalida_o_no_disponible_es_error_de_fecha_no_fatal(message: str) -> None:
    c, sesion, esperas = cliente(error_oxr(400, message))
    with pytest.raises(ErrorFechaProveedor, match=message) as error:
        c.obtener_tasas(FECHA)
    assert "2026-10-07" in str(error.value)
    assert not isinstance(error.value, ErrorFatalProveedor)  # solo afecta a esa fecha
    assert len(sesion.llamadas) == 1 and esperas == []


@pytest.mark.parametrize("cuerpo", ["", "<html>Too Many Requests</html>", '{"message": "otro"}'])
def test_429_sin_message_conocido_se_reintenta(cuerpo: str) -> None:
    c, sesion, esperas = cliente(Respuesta(429, cuerpo), ok())
    assert "CLP" in c.obtener_tasas(FECHA)
    assert len(sesion.llamadas) == 2 and esperas == [0.5]


@pytest.mark.parametrize("cuerpo", ['{"message": "otro_codigo"}', '{"message": "unauthorized"}'])
def test_401_con_message_desconocido_es_error_de_credenciales(cuerpo: str) -> None:
    # El 401 es el respaldo: un `message` que OXR agregue en el futuro no debe volverlo
    # un error no fatal que deje el lote lleno de fechas sin tasa.
    c, sesion, esperas = cliente(Respuesta(401, cuerpo))
    with pytest.raises(ErrorCredencialesProveedor, match="HTTP 401") as error:
        c.obtener_tasas(FECHA)
    assert "OXR_APP_ID" in str(error.value)
    assert isinstance(error.value, ErrorFatalProveedor)
    assert len(sesion.llamadas) == 1 and esperas == []


@pytest.mark.parametrize(
    ("status", "tipo"), [(401, ErrorCredencialesProveedor), (403, ErrorCredencialesProveedor)]
)
def test_401_y_403_sin_message_no_se_reintentan(status: int, tipo: type[Exception]) -> None:
    c, sesion, _ = cliente(Respuesta(status, "Forbidden"))
    with pytest.raises(tipo, match=f"HTTP {status}"):
        c.obtener_tasas(FECHA)
    assert len(sesion.llamadas) == 1


def test_404_no_se_reintenta_y_no_es_fatal() -> None:
    c, sesion, _ = cliente(error_oxr(404, "not_found"))
    with pytest.raises(ErrorProveedorTasas, match="not_found") as error:
        c.obtener_tasas(FECHA)
    assert not isinstance(error.value, ErrorFatalProveedor)
    assert len(sesion.llamadas) == 1


def test_429_se_reintenta_respetando_retry_after() -> None:
    c, sesion, esperas = cliente(error_oxr(429, "too_many_requests", **{"Retry-After": "2"}), ok())
    assert c.obtener_tasas(FECHA)["CLP"] == Decimal("950.123456")
    assert len(sesion.llamadas) == 2
    assert esperas == [2.0]


def test_429_persistente_termina_en_cuota_excedida() -> None:
    respuestas = [error_oxr(429, "too_many_requests") for _ in range(3)]
    c, sesion, esperas = cliente(*respuestas, max_intentos=3)
    with pytest.raises(CuotaExcedida, match="1000 solicitudes"):
        c.obtener_tasas(FECHA)
    assert len(sesion.llamadas) == 3
    assert esperas == [0.5, 1.0]  # backoff exponencial, sin esperar tras el último intento


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_5xx_se_reintenta_con_backoff(status: int) -> None:
    c, sesion, esperas = cliente(Respuesta(status, "<html>error</html>"), ok())
    assert "CLP" in c.obtener_tasas(FECHA)
    assert len(sesion.llamadas) == 2 and esperas == [0.5]


def test_5xx_persistente_agota_reintentos() -> None:
    c, sesion, _ = cliente(*(Respuesta(503, "") for _ in range(3)))
    with pytest.raises(ErrorProveedorTasas, match="HTTP 503"):
        c.obtener_tasas(FECHA)
    assert len(sesion.llamadas) == 3


def test_retry_after_se_acota_a_la_espera_maxima() -> None:
    c, _, esperas = cliente(error_oxr(429, "x", **{"Retry-After": "3600"}), ok(), espera_maxima=5.0)
    c.obtener_tasas(FECHA)
    assert esperas == [5.0]


# --- Red ------------------------------------------------------------------------------


def test_timeout_se_reintenta() -> None:
    c, sesion, esperas = cliente(requests.Timeout("lento"), ok())
    assert "CLP" in c.obtener_tasas(FECHA)
    assert len(sesion.llamadas) == 2 and esperas == [0.5]


def test_timeout_persistente_da_error_claro() -> None:
    c, _, _ = cliente(*(requests.ReadTimeout() for _ in range(2)), max_intentos=2, timeout=3)
    with pytest.raises(ErrorProveedorTasas, match="Tiempo de espera agotado \\(3 s\\)"):
        c.obtener_tasas(FECHA)


def test_error_de_conexion_se_reintenta_y_luego_falla() -> None:
    c, sesion, _ = cliente(*(requests.ConnectionError("dns") for _ in range(3)))
    with pytest.raises(ErrorProveedorTasas, match="Error de red \\(ConnectionError\\)"):
        c.obtener_tasas(FECHA)
    assert len(sesion.llamadas) == 3


# --- Respuestas malformadas ----------------------------------------------------------


@pytest.mark.parametrize(
    "texto",
    [
        "esto no es json",
        "[]",
        json.dumps({"base": "USD"}),
        json.dumps({"rates": {}}),
        json.dumps({"rates": [1, 2]}),
        json.dumps({"rates": {"CLP": "mucho"}}),
        json.dumps({"rates": {"CLP": -1}}),
        json.dumps({"rates": {"CLP": True}}),
    ],
)
def test_json_malformado_da_error_sin_reintentar(texto: str) -> None:
    c, sesion, _ = cliente(Respuesta(200, texto))
    with pytest.raises(ErrorProveedorTasas, match="malformada"):
        c.obtener_tasas(FECHA)
    assert len(sesion.llamadas) == 1


# --- Secretos -------------------------------------------------------------------------


def test_la_api_key_nunca_aparece_en_errores_ni_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    # requests incluye la URL completa (con app_id) en sus mensajes de error.
    fuga = requests.ConnectionError(f"Max retries exceeded with url: /x.json?app_id={APP_ID}")
    escenarios: list[tuple[Respuesta | Exception, ...]] = [
        (fuga, fuga, fuga),
        (error_oxr(401, f"invalid_app_id {APP_ID}"),),
        (Respuesta(500, APP_ID), Respuesta(500, APP_ID), Respuesta(500, APP_ID)),
        (Respuesta(200, f"no json {APP_ID}"),),
    ]
    for respuestas in escenarios:
        c, _, _ = cliente(*respuestas)
        with pytest.raises(ErrorProveedorTasas) as error:
            c.obtener_tasas(FECHA)
        assert APP_ID not in str(error.value)
        # Ni el mensaje ni el traceback completo (con excepciones encadenadas) la exponen.
        assert APP_ID not in "".join(traceback.format_exception(error.value))
        assert error.value.__cause__ is None
    c, _, _ = cliente(ok())
    c.obtener_tasas(FECHA)
    assert caplog.records, "se esperaban logs de depuración/reintentos"
    assert APP_ID not in caplog.text


def test_repr_enmascara_la_api_key() -> None:
    c, _, _ = cliente()
    assert APP_ID not in repr(c)
    assert "7890" in repr(c)


def test_repr_del_objeto_auth_enmascara_la_api_key() -> None:
    c, sesion, _ = cliente(ok())
    c.obtener_tasas(FECHA)
    auth = sesion.llamadas[0]["auth"]
    assert isinstance(auth, AutenticacionToken)
    assert APP_ID not in repr(auth) and APP_ID not in str(auth)
    assert repr(auth) == f"AutenticacionToken(app_id={enmascarar(APP_ID)!r})"


@pytest.mark.parametrize(
    ("secreto", "esperado"), [("abcdefghij", "******ghij"), ("corto", "*****"), ("", "")]
)
def test_enmascarar(secreto: str, esperado: str) -> None:
    assert enmascarar(secreto) == esperado


@pytest.mark.parametrize("app_id", ["", "   "])
def test_sin_app_id_falla_al_construir(app_id: str) -> None:
    with pytest.raises(ConfiguracionInvalida, match="OXR_APP_ID"):
        ClienteOpenExchangeRates(app_id, sesion=SesionFalsa())


def test_cuenta_las_solicitudes_http_incluyendo_reintentos() -> None:
    c, _, _ = cliente(Respuesta(503, ""), ok(), ok())
    c.obtener_tasas(FECHA)
    c.obtener_tasas(date(2026, 10, 8))
    assert c.solicitudes_http == 3
