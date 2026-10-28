"""Cliente OXR por el camino HTTP real (requests + urllib3) contra un servidor local.

No sale a Internet: el servidor escucha en 127.0.0.1 y responde como Open Exchange Rates.
Sirve para comprobar lo que una sesión falsa no ve: qué URL y qué headers arma
``requests`` y qué registra ``urllib3`` en nivel DEBUG (registra la URL con su query).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest
import requests

from xpendit.adapters.tasas import ClienteOpenExchangeRates

APP_ID = "clave-super-secreta-1234567890"


class _Manejador(BaseHTTPRequestHandler):
    recibidas: ClassVar[list[dict[str, str]]] = []

    def do_GET(self) -> None:
        _Manejador.recibidas.append(
            {"ruta": self.path, "authorization": self.headers.get("Authorization", "")}
        )
        cuerpo = json.dumps({"base": "USD", "rates": {"USD": 1, "CLP": 950.5}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, format: str, *args: object) -> None:  # silencia stderr
        pass


@pytest.fixture
def servidor() -> Iterator[str]:
    _Manejador.recibidas = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Manejador)
    hilo = threading.Thread(target=httpd.serve_forever, daemon=True)
    hilo.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/api"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_app_id_va_en_header_y_no_aparece_en_la_url_ni_en_logs_de_urllib3(
    servidor: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)  # incluye urllib3.connectionpool
    sesion = requests.Session()
    sesion.trust_env = False  # sin proxies del entorno: la solicitud va directo al servidor local
    cliente = ClienteOpenExchangeRates(APP_ID, sesion=sesion, url_base=servidor)

    tasas = cliente.obtener_tasas(date(2026, 10, 7))

    assert tasas["CLP"] == Decimal("950.5")
    (recibida,) = _Manejador.recibidas
    assert recibida["ruta"] == "/api/historical/2026-10-07.json"  # sin query string
    assert recibida["authorization"] == f"Token {APP_ID}"
    # urllib3 sí registró la solicitud (el camino real se ejerció)...
    assert any(r.name.startswith("urllib3") for r in caplog.records)
    assert "/api/historical/2026-10-07.json" in caplog.text
    # ...pero ni en sus registros ni en los nuestros aparece la key.
    assert APP_ID not in caplog.text
    assert all(APP_ID not in r.getMessage() for r in caplog.records)


def test_el_token_gana_a_las_credenciales_de_netrc_con_trust_env(
    servidor: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Con trust_env=True (el valor por omisión de requests.Session, que es lo que usa el
    # cliente real), requests busca credenciales en .netrc y, si las encuentra, reemplaza un
    # header Authorization pasado por `headers=`. Un objeto `auth=` explícito tiene prioridad.
    netrc = tmp_path / ".netrc"
    netrc.write_text(
        "machine 127.0.0.1\n  login usuario-netrc\n  password clave-netrc\n", encoding="utf-8"
    )
    netrc.chmod(0o600)  # en Windows solo controla el atributo de solo lectura; no molesta
    # NETRC fija el archivo en cualquier sistema. Además se aíslan los directorios de usuario:
    # en Windows requests busca %USERPROFILE%\.netrc y %USERPROFILE%\_netrc, no $HOME.
    monkeypatch.setenv("NETRC", str(netrc))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(variable, raising=False)
        monkeypatch.delenv(variable.lower(), raising=False)
    # Con trust_env, en Windows y macOS requests también lee el proxy del sistema (registro o
    # configuración de red); NO_PROXY garantiza que la solicitud vaya directo a 127.0.0.1.
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    # Control: requests sí ve el .netrc falso para este host.
    assert requests.utils.get_netrc_auth(servidor) == ("usuario-netrc", "clave-netrc")

    cliente = ClienteOpenExchangeRates(APP_ID, url_base=servidor)  # sesión real, trust_env=True
    assert cliente.obtener_tasas(date(2026, 10, 7))["CLP"] == Decimal("950.5")

    (recibida,) = _Manejador.recibidas
    assert recibida["authorization"] == f"Token {APP_ID}"
