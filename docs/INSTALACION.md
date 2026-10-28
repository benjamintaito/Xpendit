# Instalación detallada

Guía por sistema operativo para clonar, instalar y ejecutar el proyecto. El resumen está en el
[README](../README.md#quickstart).

## Requisitos

- **Python 3.12 o superior** (la CI lo prueba con 3.12 y 3.13 en Linux, Windows y macOS) y
  **Git**.
- **Windows:** instala Python desde <https://www.python.org/downloads/> y, en la primera
  pantalla del instalador, marca **«Add python.exe to PATH»**; o bien, en PowerShell,
  `winget install Python.Python.3.12`. Ambas vías instalan el lanzador **`py`**: `py --list`
  muestra las versiones instaladas y `py -3` usa la versión 3 más reciente (debe ser 3.12 o
  superior). Git: <https://git-scm.com/download/win> o `winget install Git.Git`.
- **macOS:** Python desde <https://www.python.org/downloads/> o con Homebrew
  (`brew install python@3.12`). En Mac el comando es **`python3`**. El `python3` de las
  herramientas de Xcode puede ser más antiguo: si `python3 --version` es menor que 3.12, usa
  `python3.12` para crear el entorno. Git viene con `xcode-select --install` (o `brew install git`).
- **Linux:** el Python 3.12+ de tu distribución; en Debian/Ubuntu, además,
  `sudo apt install python3-venv`.

Todos los comandos se ejecutan desde la raíz del repositorio. Con el entorno virtual activado,
`python` es el del entorno en cualquier sistema, así que desde ahí los comandos son los mismos
en los tres, salvo la barra de las rutas (Python acepta también `/` en Windows).

## Windows (PowerShell)

```powershell
# 1. Clonar el repositorio y entrar
git clone https://github.com/benjamintaito/Xpendit.git
cd Xpendit

# 2. Crear y activar el entorno virtual
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Instalar dependencias
python -m pip install -r requirements-dev.txt

# 4. API key (opcional: sin ella se usa --offline)
copy .env.example .env
notepad .env

# 5. Tests
python -m pytest

# 6. Analizador, con la API real y sin API key
python -m xpendit analizar data\gastos_historicos.csv --fecha-referencia 2026-10-26
python -m xpendit analizar data\gastos_historicos.csv --offline --fecha-referencia 2026-10-26
```

Al activar el entorno, el prompt muestra `(.venv)`; `deactivate` lo desactiva. En el paso 4,
completa `OXR_APP_ID=` con tu App ID y guarda.

> **Si `Activate.ps1` falla con «la ejecución de scripts está deshabilitada en este sistema»**,
> permite los scripts locales para tu usuario (una sola vez):
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. Para cambiarlo solo en esa ventana:
> `Set-ExecutionPolicy -Scope Process RemoteSigned`. O usa `cmd`, que no tiene esa restricción.

## Windows (cmd)

Todo igual que en PowerShell salvo la activación del entorno:

```bat
py -3 -m venv .venv
.venv\Scripts\activate.bat
```

## macOS (Terminal)

```bash
git clone https://github.com/benjamintaito/Xpendit.git
cd Xpendit
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
open -e .env
python -m pytest
python -m xpendit analizar data/gastos_historicos.csv --fecha-referencia 2026-10-26
python -m xpendit analizar data/gastos_historicos.csv --offline --fecha-referencia 2026-10-26
```

`open -e .env` abre el archivo en TextEdit; en la terminal, `nano .env` (Ctrl+O guarda, Ctrl+X
sale). La penúltima línea usa la API real y la última, `--offline`.

## Linux

Igual que en macOS, editando `.env` con `nano .env` o el editor que prefieras.

## El archivo `.env`

```
# App ID de Open Exchange Rates
OXR_APP_ID=tu_app_id
```

Cada línea debe ser `CLAVE=valor`, estar vacía o empezar con `#`. En Windows, guárdalo en
**UTF-8** (el Bloc de notas actual lo hace por defecto) y con el nombre exacto `.env`, sin
`.txt` al final.

El plan gratuito de Open Exchange Rates tiene base USD fija (las demás conversiones se hacen
con tasas cruzadas) y unas 1000 solicitudes al mes; el analizador hace 9 la primera vez y 0 las
siguientes gracias a la caché en `.cache/tasas/`.

## Atajos con `tareas.py`

Con el entorno activado, en cualquier sistema:

| Comando | Qué hace |
|---|---|
| `python tareas.py install` | Instala las dependencias |
| `python tareas.py test` / `cov` | Tests / tests con cobertura |
| `python tareas.py lint` / `format` | Verifica / aplica el formato y lint de ruff |
| `python tareas.py typecheck` | `mypy --strict` |
| `python tareas.py check` | lint + tipos + tests (lo mismo que la CI) |
| `python tareas.py analizar-offline` / `analizar` | Reporte con tasas de ejemplo / con la API real |

`--fecha AAAA-MM-DD` cambia la fecha de referencia y `--salida RUTA` el reporte.

## Solución de problemas

| Síntoma | Solución |
|---|---|
| Windows: `python` (o `py`) «no se reconoce como comando», o `python` abre la Microsoft Store | Usa `py` para crear el entorno. Si tampoco existe, reinstala Python desde python.org marcando «Add python.exe to PATH» y abre una terminal nueva. Para que `python` deje de abrir la Store, desactiva los «Alias de ejecución de aplicaciones» de `python.exe` y `python3.exe` en Configuración. |
| PowerShell: «la ejecución de scripts está deshabilitada en este sistema» | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, o usa `cmd` con `.venv\Scripts\activate.bat`. |
| Caracteres raros (`Ã³`, `?`) en la consola | El programa ya escribe en UTF-8 y no falla. En una consola antigua, ejecuta antes `chcp 65001` (cmd) o usa Windows Terminal. |
| Aviso `python-dotenv could not parse statement starting at line N` | La línea N de `.env` no es `CLAVE=valor` ni un comentario: los comentarios empiezan con `#`. |
| `No se encontró la variable de entorno OXR_APP_ID` teniendo un `.env` | El Bloc de notas puede haberlo guardado como `.env.txt`: revisa con `Get-ChildItem -Force` y renómbralo (`ren .env.txt .env`). Ejecuta el comando desde la raíz del repositorio. |
| `El archivo …\.env no está guardado en UTF-8` | Ábrelo con el Bloc de notas y usa Guardar como → Codificación: UTF-8. Pasa si se creó con `echo ... > .env` en Windows PowerShell 5.1, que escribe UTF-16. |
| `Open Exchange Rates rechazó el App ID (HTTP 401 …)` | El App ID está mal copiado. Revisa también que no haya una variable `OXR_APP_ID` antigua en el sistema, que tiene prioridad sobre `.env`: `Remove-Item Env:OXR_APP_ID` (PowerShell) o `unset OXR_APP_ID` (macOS/Linux). |
| `Open Exchange Rates rechazó la solicitud por exceso de uso (HTTP 429 …)` | Se agotó la cuota mensual. Las fechas ya consultadas salen de la caché; mientras tanto, usa `--offline`. |
| Linux: `ensurepip is not available` | `sudo apt install python3-venv` (Debian/Ubuntu). |
