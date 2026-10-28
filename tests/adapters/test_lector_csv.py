from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from xpendit.adapters.csv_gastos import COLUMNAS, LectorCsvGastos
from xpendit.domain.errores import ArchivoInvalido

ENCABEZADO = ",".join(COLUMNAS)
FILA_OK = "g_001,e_002,Bruno,Soto,sales_team,food,50,USD,2026-10-07"
CSV_REAL = Path(__file__).resolve().parents[2] / "data" / "gastos_historicos.csv"


def escribir(tmp_path: Path, *lineas: str, encoding: str = "utf-8") -> Path:
    ruta = tmp_path / "gastos.csv"
    ruta.write_text("\n".join(lineas) + "\n", encoding=encoding)
    return ruta


def test_lee_una_fila_valida(tmp_path: Path) -> None:
    lote = LectorCsvGastos(escribir(tmp_path, ENCABEZADO, FILA_OK)).leer()
    (registro,) = lote.registros
    g, e = registro.gasto, registro.empleado
    assert (g.id, g.empleado_id, g.monto, g.moneda, g.fecha, g.categoria) == (
        "g_001",
        "e_002",
        Decimal("50"),
        "USD",
        date(2026, 10, 7),
        "food",
    )
    assert (e.id, e.nombre, e.apellido, e.cost_center) == ("e_002", "Bruno", "Soto", "sales_team")
    assert lote.filas_invalidas == ()


def test_lee_el_csv_del_desafio() -> None:
    lote = LectorCsvGastos(CSV_REAL).leer()
    assert len(lote.registros) == 50
    assert lote.filas_invalidas == ()
    assert {r.gasto.moneda for r in lote.registros} == {"USD", "CLP", "MXN", "EUR"}


def test_normaliza_espacios_y_mayusculas(tmp_path: Path) -> None:
    ruta = escribir(
        tmp_path,
        ENCABEZADO,
        "g_1 , e_1 ,Ana,Reyes, Core_Engineering , FOOD , 50.5 , usd ,2026-10-07",
    )
    g = LectorCsvGastos(ruta).leer().registros[0]
    assert (g.gasto.id, g.gasto.categoria, g.gasto.moneda, g.gasto.monto) == (
        "g_1",
        "food",
        "USD",
        Decimal("50.5"),
    )
    assert g.empleado.cost_center == "core_engineering"


def test_tolera_bom_de_excel(tmp_path: Path) -> None:
    ruta = escribir(tmp_path, ENCABEZADO, FILA_OK, encoding="utf-8-sig")
    assert len(LectorCsvGastos(ruta).leer().registros) == 1


def test_csv_guardado_por_excel_en_windows(tmp_path: Path) -> None:
    # "CSV UTF-8" de Excel en Windows: BOM al inicio, CRLF y tildes/ñ en los nombres.
    ruta = tmp_path / "excel.csv"
    ruta.write_bytes(
        b"\xef\xbb\xbf"
        + "\r\n".join(
            [ENCABEZADO, "g_1,e_1,José,Núñez,sales_team,food,50,USD,2026-10-07", ""]
        ).encode("utf-8")
    )
    lote = LectorCsvGastos(ruta).leer()
    (registro,) = lote.registros
    assert lote.filas_invalidas == ()
    assert registro.gasto.id == "g_1"  # el BOM no quedó pegado a la primera columna
    assert (registro.empleado.nombre, registro.empleado.apellido) == ("José", "Núñez")
    assert registro.gasto.fecha == date(2026, 10, 7)  # sin "\r" colgando del último campo


def test_montos_negativos_y_cero_se_cargan_para_el_detector(tmp_path: Path) -> None:
    ruta = escribir(
        tmp_path,
        ENCABEZADO,
        "g_1,e_1,A,B,cc,food,-50,USD,2026-10-07",
        "g_2,e_1,A,B,cc,food,0,USD,2026-10-07",
    )
    lote = LectorCsvGastos(ruta).leer()
    assert [r.gasto.monto for r in lote.registros] == [Decimal("-50"), Decimal("0")]


@pytest.mark.parametrize(
    ("fila", "motivo"),
    [
        ("g_2,e_1,A,B,cc,food,abc,USD,2026-10-07", "monto no numérico"),
        ("g_2,e_1,A,B,cc,food,NaN,USD,2026-10-07", "monto no finito"),
        ("g_2,e_1,A,B,cc,food,Infinity,USD,2026-10-07", "monto no finito"),
        ("g_2,e_1,A,B,cc,food,,USD,2026-10-07", "falta el campo 'monto'"),
        ("g_2,e_1,A,B,cc,food,10,DOLAR,2026-10-07", "moneda inválida"),
        ("g_2,e_1,A,B,cc,food,10,US,2026-10-07", "moneda inválida"),
        ("g_2,e_1,A,B,cc,food,10,USD,07/10/2026", "fecha inválida"),
        ("g_2,e_1,A,B,cc,food,10,USD,2026-02-30", "fecha inválida"),
        ("g_2,e_1,A,B,cc,food,10,USD,20261007", "fecha inválida"),
        ("g_2,e_1,A,B,,food,10,USD,2026-10-07", "falta el campo 'empleado_cost_center'"),
        ("g_2,e_1,A,B,cc,,10,USD,2026-10-07", "falta el campo 'categoria'"),
        ("g_2,e_1,A,B,cc,food,10,USD", "falta el campo 'fecha'"),
        ("g_2,e_1,A,B,cc,food,10,USD,2026-10-07,extra", "más columnas"),
        ("g_001,e_1,A,B,cc,food,10,USD,2026-10-07", "gasto_id repetido"),
    ],
)
def test_fila_invalida_se_reporta_y_el_resto_sigue(tmp_path: Path, fila: str, motivo: str) -> None:
    ruta = escribir(tmp_path, ENCABEZADO, FILA_OK, fila, "g_3,e_1,A,B,cc,food,10,USD,2026-10-07")
    lote = LectorCsvGastos(ruta).leer()
    assert [r.gasto.id for r in lote.registros] == ["g_001", "g_3"]
    (invalida,) = lote.filas_invalidas
    assert motivo in invalida.motivo
    assert invalida.numero_linea == 3
    assert lote.filas_leidas == 3


def test_fila_invalida_conserva_el_id_si_existe(tmp_path: Path) -> None:
    ruta = escribir(tmp_path, ENCABEZADO, "g_9,e_1,A,B,cc,food,abc,USD,2026-10-07")
    (invalida,) = LectorCsvGastos(ruta).leer().filas_invalidas
    assert invalida.gasto_id == "g_9"
    assert str(invalida).startswith("Línea 2 (g_9):")


def test_archivo_inexistente(tmp_path: Path) -> None:
    with pytest.raises(ArchivoInvalido, match="No existe"):
        LectorCsvGastos(tmp_path / "nada.csv").leer()


def test_archivo_vacio(tmp_path: Path) -> None:
    ruta = tmp_path / "vacio.csv"
    ruta.write_text("", encoding="utf-8")
    with pytest.raises(ArchivoInvalido, match="vacío"):
        LectorCsvGastos(ruta).leer()


def test_faltan_columnas(tmp_path: Path) -> None:
    ruta = escribir(tmp_path, "gasto_id,monto", "g_1,10")
    with pytest.raises(ArchivoInvalido, match=r"Faltan columnas.*empleado_id"):
        LectorCsvGastos(ruta).leer()


def test_codificacion_incorrecta(tmp_path: Path) -> None:
    ruta = tmp_path / "latin1.csv"
    ruta.write_bytes(
        (ENCABEZADO + "\ng_1,e_1,José,Núñez,cc,food,1,USD,2026-10-07\n").encode("latin-1")
    )
    with pytest.raises(ArchivoInvalido, match="codificado"):
        LectorCsvGastos(ruta).leer()


def test_ultima_linea_sin_salto_de_linea(tmp_path: Path) -> None:
    ruta = tmp_path / "g.csv"
    ruta.write_text(ENCABEZADO + "\n" + FILA_OK, encoding="utf-8")  # como el CSV del desafío
    assert len(LectorCsvGastos(ruta).leer().registros) == 1
