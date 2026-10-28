# Registro de decisiones

Formato tipo ADR corto: **contexto → decisión → alternativas → consecuencias**. Cada
decisión indica dónde vive en el código.

## Resumen

| # | Decisión | Por qué |
|---|---|---|
| 1 | Python 3.12+, `requests` y `python-dotenv` como únicas dependencias de ejecución | Dominio pequeño: dataclasses y validación explícita bastan, sin Pydantic. |
| 2 | Arquitectura hexagonal con un único *composition root* | Probar las reglas sin red y cambiar proveedor o fuente con un adaptador. |
| 3 | Reglas como Strategy; `None` = «no aplica» | Agregar una regla no toca el motor. |
| 4 | `Decimal` para dinero; montos convertidos redondeados a centavos | Bordes exactos (100 vs 100,01) sin errores de `float`. |
| 5 | Fecha de referencia inyectada (2026-10-26 en el análisis) | Resultados reproducibles; el dominio no llama a `date.today()`. |
| 6 | RECHAZADO > PENDIENTE > APROBADO; sin reglas aplicables, PENDIENTE | Lo pide el enunciado; sin evidencia para aprobar, decide una persona. |
| 7 | Antigüedad en días calendario, umbrales inclusivos; fecha futura → PENDIENTE | Coincide con los rangos del enunciado; una fecha futura suele ser un error corregible. |
| 8 | Límite por categoría en USD con la tasa del día del gasto | El valor del gasto es el del día en que se hizo. |
| 9 | Sin tasa → regla propia, al menos PENDIENTE con `TASA_NO_DISPONIBLE` | No aprobar un monto que no se pudo convertir, en ninguna categoría. |
| 10 | Duplicado = monto + moneda + fecha; copias → PENDIENTE | Definición del enunciado; amplia, así que no se rechaza en automático. |
| 11 | Monto ≤ 0 → RECHAZADO con `MONTO_INVALIDO` | No hay nada que reembolsar; una devolución va por otro flujo. |
| 12 | Anomalías como detectores que entran en la misma resolución | Un duplicado no puede quedar APROBADO. |
| 13 | Una consulta por fecha única, instantánea en memoria y caché en disco | Evita N+1: 9 solicitudes para 50 gastos, 0 en la segunda corrida. |
| 14 | Key en `.env` y en el header `Authorization`, nunca en la URL ni en logs | La URL completa aparece en los logs DEBUG de `urllib3`. |
| 15 | Reintentos solo para lo transitorio; errores clasificados por el `message` de OXR | Fallar rápido sin gastar cuota en errores definitivos. |
| 16 | Excepciones de dominio; filas inválidas reportadas sin detener el lote | Mensajes accionables; una fila mala no bota el análisis. |
| 17 | Modo `--offline` con tasas fijas de ejemplo | Probar el flujo sin key ni red. |
| 18 | `ANALISIS.md` generado y determinista | Regenerar es un comando; no queda desactualizado. |
| 19 | Portabilidad explícita: codificación, consola, fin de línea, `tareas.py` | Mismo resultado y mismo `ANALISIS.md` en Windows, macOS y Linux. |

Índice:

1. [Python 3.12+ con dependencias mínimas](#1-python-312-con-dependencias-mínimas)
2. [Arquitectura hexagonal (puertos y adaptadores)](#2-arquitectura-hexagonal-puertos-y-adaptadores)
3. [Reglas como Strategy y motor cerrado a modificaciones](#3-reglas-como-strategy-y-motor-cerrado-a-modificaciones)
4. [`Decimal` para dinero, nunca `float`](#4-decimal-para-dinero-nunca-float)
5. [Fecha de referencia inyectada](#5-fecha-de-referencia-inyectada)
6. [Resolución de estado: prioridad y PENDIENTE por defecto](#6-resolución-de-estado-prioridad-y-pendiente-por-defecto)
7. [Antigüedad: días calendario, umbrales inclusivos, fecha futura](#7-antigüedad-días-calendario-umbrales-inclusivos-fecha-futura)
8. [Límite por categoría en moneda base, con la tasa del día](#8-límite-por-categoría-en-moneda-base-con-la-tasa-del-día)
9. [Moneda o fecha sin tasa → alerta `TASA_NO_DISPONIBLE`](#9-moneda-o-fecha-sin-tasa--alerta-tasa_no_disponible)
10. [Duplicados exactos](#10-duplicados-exactos)
11. [Montos negativos o cero](#11-montos-negativos-o-cero)
12. [Anomalías como detectores que declaran su estado](#12-anomalías-como-detectores-que-declaran-su-estado)
13. [N+1: una consulta por fecha única, instantánea en memoria y caché en disco](#13-n1-una-consulta-por-fecha-única-instantánea-en-memoria-y-caché-en-disco)
14. [Manejo de secretos](#14-manejo-de-secretos)
15. [Cliente HTTP: timeout, reintentos y mapeo de errores](#15-cliente-http-timeout-reintentos-y-mapeo-de-errores)
16. [Errores: excepciones de dominio y lotes tolerantes a filas malas](#16-errores-excepciones-de-dominio-y-lotes-tolerantes-a-filas-malas)
17. [Modo offline con tasas de ejemplo](#17-modo-offline-con-tasas-de-ejemplo)
18. [`ANALISIS.md` generado desde los datos](#18-analisismd-generado-desde-los-datos)
19. [Portabilidad: Windows, macOS y Linux](#19-portabilidad-windows-macos-y-linux)

---

## 1. Python 3.12+ con dependencias mínimas

**Contexto.** El enunciado permite Python o JavaScript. Se evalúa claridad, pruebas y manejo
de errores, no rendimiento.

**Decisión.** Python 3.12+ con `requests`, `python-dotenv` y, para desarrollo, `pytest`,
`pytest-cov`, `ruff` y `mypy --strict`. Modelos con `dataclasses(frozen=True, slots=True)`.

**Alternativas.** *Pydantic* daría validación declarativa, pero suma una dependencia pesada para
un dominio pequeño y mezcla validación de entrada con el modelo; la validación quedó explícita
en `Politica.desde_dict` y en el lector CSV, donde se pueden acumular errores con mensajes en
español. *httpx* sería equivalente a `requests`; no se necesita async.

**Consecuencias.** Modelos inmutables y tipados, sin magia. `mypy --strict` pasa sobre `src/`.

## 2. Arquitectura hexagonal (puertos y adaptadores)

**Contexto.** El desafío pide separar lógica pura (motor), I/O (API de tasas) y orquestación
(lote), y se espera agregar reglas, anomalías, fuentes y proveedores.

**Decisión.** Tres capas con dependencias hacia adentro:

- `domain/`: modelos, política, reglas, motor, detectores y el **puerto** `ProveedorTasas`.
  Solo biblioteca estándar, sin I/O.
- `application/`: caso de uso `AnalizarLote` y el puerto `LectorGastos`.
- `adapters/`: CSV, JSON de política, cliente OXR, caché, proveedor fijo, reportes.

`composicion.py` es el *composition root*: único lugar donde se eligen e instancian adaptadores.
La CLI solo parsea argumentos, llama a la composición y muestra resultados.

**Alternativas.** Un script monolítico sería más corto, pero mezclaría red y reglas y haría
imposible probar las reglas sin red. Un framework de inyección de dependencias es excesivo:
la inyección por constructor basta.

**Consecuencias.** El motor se prueba con tasas en memoria; el cliente HTTP con una sesión
falsa; el caso de uso con un proveedor espía. Cambiar OXR por otro proveedor o el CSV por una
base de datos es escribir un adaptador y cambiar una línea en `composicion.py`.

## 3. Reglas como Strategy y motor cerrado a modificaciones

**Contexto.** Hay tres reglas y "debe ser fácil anexar otras".

**Decisión.** Cada regla es una clase pequeña con
`evaluar(gasto, empleado, contexto) -> ResultadoRegla | None` (`domain/reglas/`): las tres del
enunciado más `ReglaConversionMoneda` (ver decisión 9).
`MotorReglas` recibe la lista de reglas y un resolvedor; no conoce ninguna regla concreta.
`None` significa **"no aplica"**, que es distinto de APROBADO (p. ej., categoría sin límite o
centro de costo sin prohibición). `reglas_por_defecto()` es el registro.

**Alternativas.** Un `if/elif` por regla dentro del motor (viola Open/Closed); reglas
declarativas en JSON (más flexible, pero la regla cruzada y la conversión de moneda necesitan
código igual).

**Consecuencias.** Agregar una regla = una clase + una línea en el registro. Hay un test que
agrega una regla de "fin de semana" sin tocar el motor
(`tests/domain/test_motor.py::test_agregar_una_regla_nueva_no_requiere_tocar_el_motor`).

## 4. `Decimal` para dinero, nunca `float`

**Contexto.** Los bordes del enunciado son exactos (100 vs 100.01, 150 vs 150.01) y se
comparan montos convertidos.

**Decisión.** Todos los montos, límites y tasas son `decimal.Decimal`. El JSON de la política
y la respuesta de OXR se parsean con `parse_float=Decimal`, así que los números nunca pasan por
`float`. El monto convertido se redondea a centavos con `ROUND_HALF_UP` antes de comparar
(`ConversorMoneda`); los montos ya en moneda base no se redondean.

**Alternativas.** `float` (`0.1 + 0.2 != 0.3`: un borde podría caer del lado equivocado);
enteros en centavos (exacto, pero incómodo con tasas de 6 decimales y monedas sin centavos como
CLP).

**Consecuencias.** Comparaciones de borde deterministas. Redondear a centavos significa que,
p. ej., 90 004 CLP a 900 CLP/USD = 100,0044 → 100,00 USD → APROBADO (cubierto por test): un
monto monetario no tiene fracciones de centavo.

## 5. Fecha de referencia inyectada

**Contexto.** La antigüedad depende de "hoy", y el CSV tiene fechas de mayo a octubre de 2026.

**Decisión.** `ContextoEvaluacion.fecha_referencia` se inyecta; el dominio nunca llama a
`date.today()`. La CLI la recibe con `--fecha-referencia` y solo si falta usa la fecha del
sistema (en la capa más externa), dejándola explícita en el comando que imprime `ANALISIS.md`.
El análisis entregado usa 2026-10-26, fecha en que se recibió el desafío.

**Alternativas.** `date.today()` dentro de la regla (tests frágiles que cambian con el
calendario); inyectar un "reloj" (callable) — equivalente, pero una fecha fija es más simple
y basta porque un lote se evalúa contra un único instante.

**Consecuencias.** Resultados reproducibles y tests de bordes exactos. El desglose cambia con
la fecha (con 2026-10-26 y tasas reales, 19 de los 24 rechazos tienen más de 60 días y 13 se
rechazan solo por eso).

## 6. Resolución de estado: prioridad y PENDIENTE por defecto

**Contexto.** Varias reglas pueden opinar sobre un mismo gasto.

**Decisión.** `ResolvedorPorPrioridad`: RECHAZADO > PENDIENTE > APROBADO, independiente del
orden de las reglas. Si ninguna regla aplica, **PENDIENTE sin alertas** (lo pide el enunciado y
es lo seguro: sin evidencia para aprobar, decide una persona). Las alertas de *todas* las reglas
se conservan, en el orden de registro, aunque no hayan definido el estado.

**Alternativas.** Quedarse solo con las alertas de la regla "ganadora" (oculta información al
revisor); APROBADO por defecto (aprobaría gastos que ninguna regla miró).

**Consecuencias.** Un gasto de `core_engineering` en `food` con 99 días muestra a la vez
`LIMITE_ANTIGUEDAD`, `LIMITE_CATEGORIA` y `POLITICA_CENTRO_COSTO`. El resolvedor es inyectable
por si el negocio cambia la prioridad.

## 7. Antigüedad: días calendario, umbrales inclusivos, fecha futura

**Contexto.** Rangos del enunciado: 0–30 aprobado, 31–60 pendiente, >60 rechazado.

**Decisión.** `días = (fecha_referencia - fecha_gasto).days` (días calendario). Umbrales
inclusivos leídos de la política (`pendiente_dias`, `rechazado_dias`), no fijos en el código.
**Fecha futura (días < 0) → PENDIENTE** con alerta `FECHA_FUTURA`.

**Alternativas.** Días hábiles (no lo pide el enunciado y requiere calendario de feriados);
rechazar fechas futuras (suelen ser errores de digitación corregibles: mejor que lo vea una
persona); aprobarlas (sería aprobar algo inconsistente).

**Consecuencias.** Tests en 0, 1, 29, 30, 31, 45, 60, 61, 365, −1, −30, umbrales
personalizados, umbrales iguales y cruce de febrero bisiesto.

## 8. Límite por categoría en moneda base, con la tasa del día

**Contexto.** Los límites están en la moneda base (USD) y los gastos vienen en CLP, MXN, EUR y USD.

**Decisión.** `ReglaLimiteCategoria` convierte con la tasa **de la fecha del gasto** y compara:
`<= aprobado_hasta` → APROBADO; `<= pendiente_hasta` → PENDIENTE ("Requiere revisión");
mayor → RECHAZADO ("Excede límite aprobado"). Es genérica: cualquier categoría de
`limites_por_categoria`. Si `aprobado_hasta == pendiente_hasta` (transport 200/200) el tramo
pendiente queda vacío y se pasa directo a RECHAZADO, sin caso especial. Categoría sin límite →
`None`. Sin tasa para convertir → `None` (la alerta la emite `ReglaConversionMoneda`).

**Alternativas.** Usar la tasa del día del análisis (el valor del gasto es el del día en que se
hizo); comparar en moneda original (los límites dejarían de tener sentido).

**Consecuencias.** El resultado de gastos en moneda extranjera depende de las tasas reales;
`ANALISIS.md` muestra para cada uno la distancia al umbral más cercano.

## 9. Moneda o fecha sin tasa → alerta `TASA_NO_DISPONIBLE`

**Contexto.** Puede faltar la tasa de una moneda poco común o fallar la consulta de una fecha.
En la primera versión la alerta la emitía la regla de límite por categoría, así que en una
categoría **sin límite** (p. ej. `software`) el error de conversión se descartaba y un gasto
reciente en EUR sin tasa quedaba APROBADO sin alertas (lo detectó la revisión de código).

**Decisión.** La falta de conversión es un hallazgo propio, **independiente de la categoría**:

- `ReglaConversionMoneda` (`domain/reglas/conversion_moneda.py`), registrada en
  `reglas_por_defecto()` como una estrategia más: si la moneda del gasto no es la base y la
  conversión lanza `ConversionNoDisponible` (`MonedaNoSoportada`, `TasasNoDisponibles`),
  devuelve PENDIENTE con `TASA_NO_DISPONIBLE`; si no, `None`. Es la **única dueña** de esa
  alerta: `ReglaLimiteCategoria` devuelve `None` cuando no hay tasa (sin monto en moneda base
  no hay nada que comparar), así que la alerta no se duplica.
- El estado final sigue la prioridad general: el gasto queda **al menos PENDIENTE**, pero si
  otra regla lo rechaza (p. ej. más de 60 días) sigue **RECHAZADO**, con ambas alertas.
- Su monto no entra en los totales en moneda base; el reporte dice cuántos quedaron fuera
  (fila *Total* y nota bajo la tabla del desglose).
- `ErrorProveedorTasas` es una falla de infraestructura y ninguna regla la oculta. En el lote,
  si falla una fecha puntual (5xx persistente, red, fecha no disponible en OXR) se registra y
  sus gastos reciben la alerta anterior; si la falla es **fatal** (`ErrorFatalProveedor`:
  credenciales, plan sin permiso, cuota) el lote se aborta, porque todas las fechas fallarían
  igual y seguir solo gastaría cuota.

**Alternativas.** Mantener la alerta en la regla de categoría y agregar un parche en el caso de
uso (la lógica de negocio quedaría fuera del motor y la librería seguiría aprobando el caso);
deduplicar alertas en el motor (esconde que dos reglas hacen lo mismo); rechazar (castiga al
empleado por un problema nuestro); aprobar (deja pasar montos sin verificar); abortar siempre
(una fecha caída botaría todo el análisis).

**Consecuencias.** Coherente con el patrón Strategy: una regla nueva y una línea en el
registro, sin tocar el motor. Quien use `ReglaLimiteCategoria` sin `ReglaConversionMoneda`
pierde la alerta, por eso ambas vienen en `reglas_por_defecto()` y un test lo verifica. El
reporte lista las fechas sin tasas y su motivo.

## 10. Duplicados exactos

**Contexto.** El enunciado define duplicado como mismo monto, moneda y fecha. En este CSV hay
coincidencias entre personas distintas (p. ej. 50 USD el 2026-10-07 de Bruno Soto y Ana Reyes).

**Decisión.** Se implementa **exactamente** la definición del enunciado (`clave_enunciado`). En
cada grupo, el **primero en el orden del archivo** es el original (en este CSV coincide con el
menor id) y no se marca; cada copia recibe `DUPLICADO_EXACTO` con referencia al original y queda
**PENDIENTE** (revisión humana), no rechazada: la coincidencia puede ser legítima. Si otra regla
rechaza la copia, sigue rechazada. Existe además `clave_estricta` (+ empleado + categoría), que
se usa solo de forma informativa en el reporte.

**Alternativas.** Rechazar duplicados (demasiado agresivo con una definición tan amplia); marcar
también el original (duplica el trabajo de revisión); aplicar el criterio estricto (se aparta
del enunciado).

**Consecuencias.** Con la definición del enunciado: 7 grupos y 9 gastos marcados, de los cuales
5 grupos mezclan empleados distintos. Con el criterio estricto: 3 grupos y 4 marcados. Ambas
cifras están en `ANALISIS.md`. Cambiar de criterio es pasar otra función de clave.

## 11. Montos negativos o cero

**Contexto.** El enunciado pide detectar montos negativos. Este CSV no trae ninguno.

**Decisión.** `Gasto` **permite** montos ≤ 0 (no se validan en el modelo ni en el lector) para
que el detector `DetectorMontoInvalido` los encuentre y aparezcan en el reporte. Un monto ≤ 0
queda **RECHAZADO** con `MONTO_INVALIDO`: no hay nada que reembolsar, y si es una devolución o
nota de crédito debe ir por otro flujo. Un monto **no numérico** (o `NaN`/`Infinity`) es una
fila inválida.

**Alternativas.** PENDIENTE (razonable si se quiere que alguien investigue, pero el gasto no
puede aprobarse nunca tal como está; rechazar lo devuelve al empleado para que lo corrija);
rechazar la fila en el lector (la anomalía se perdería como "error de formato").

**Consecuencias.** Cubierto con tests (−50, −0.01, 0) aunque el CSV no tenga casos.

## 12. Anomalías como detectores que declaran su estado

**Contexto.** Las reglas miran un gasto aislado; los duplicados requieren ver el lote completo.

**Decisión.** Interfaz `DetectorAnomalias`: `codigo`, `estado` y
`detectar(gastos) -> dict[gasto_id, list[Alerta]]`. El caso de uso convierte cada detección en
un `ResultadoRegla(estado, alertas)` y lo pasa al motor como `hallazgos_adicionales`, que entran
a la **misma** resolución de prioridad.

**Alternativas.** Reportar anomalías aparte sin afectar el estado (un duplicado quedaría
APROBADO); meterlas como reglas (una regla no ve el lote).

**Consecuencias.** Agregar una anomalía = una clase + registrarla en `detectores_por_defecto()`.

## 13. N+1: una consulta por fecha única, instantánea en memoria y caché en disco

**Contexto.** Convertir cada gasto consultando la API sería una llamada por gasto; el plan
gratuito tiene ~1000 solicitudes/mes.

**Decisión.** `AnalizarLote` trabaja en dos fases:

1. Agrupa las **fechas únicas de los gastos en moneda distinta de la base** y consulta una vez
   por fecha. Los gastos ya en USD no necesitan tasa.
2. Congela el resultado en `TasasPrecargadas` (implementa el mismo puerto) y evalúa todo contra
   esa instantánea: la evaluación no hace red y una fecha fallida no se reintenta por cada gasto.

Además, `ProveedorTasasConCache` (decorador del puerto) memoiza por fecha y persiste en
`.cache/tasas/AAAA-MM-DD.json` las tasas de **días ya cerrados** (las históricas no cambian; las
del día en curso sí, por eso solo quedan en memoria). Escritura atómica. Al leer, el archivo se
trata como entrada no confiable: el campo `fecha` debe coincidir con la fecha pedida (un archivo
sin fecha, o copiado bajo el nombre de otro día, se descarta), cada código debe tener 3 letras
mayúsculas y cada tasa debe ser finita y > 0 (se rechazan `NaN`, `Infinity`, `0`, negativos, booleanos); ante cualquier
problema, o JSON roto, se ignora **el archivo completo** y se vuelve a pedir la fecha.

**Alternativas.** Solo memoización (no separa I/O de evaluación ni evita reintentar fechas
fallidas); `functools.lru_cache` (no persiste entre corridas); consultar
todas las fechas únicas (25 en vez de 9, sin beneficio).

**Consecuencias.** En el CSV: 50 gastos, 25 fechas únicas, 9 con moneda extranjera → **9
consultas**. Una segunda corrida con la API real hace 0 solicitudes HTTP. Hay un test con un
proveedor espía: N gastos en K fechas → exactamente K llamadas. La explicación de la caché en
`ANALISIS.md` se genera según el modo realmente usado (`--offline`, `--sin-cache` o caché en
disco con su directorio), para no prometer un ahorro que esa corrida no tuvo.

## 14. Manejo de secretos

**Contexto.** La API key de OXR es un secreto: no puede quedar en el repositorio, en la URL
ni en los logs, y el proyecto debe poder probarse sin ella.

**Decisión.**

- Se lee de `OXR_APP_ID` (entorno o `.env` vía `python-dotenv`; el entorno tiene prioridad).
  `.env` está en `.gitignore`; se versiona solo `.env.example` vacío.
- Sin key y sin `--offline`, la CLI termina con código 2 y un mensaje que explica cómo
  obtenerla y configurarla, sin traceback.
- La key viaja en el header **`Authorization: Token <app_id>`** (método de autenticación
  documentado por OXR), no en la query string `?app_id=`. Motivo: `urllib3` registra en nivel
  DEBUG la línea de cada solicitud **con la URL completa, incluida la query**; cualquiera que
  active `logging.DEBUG` (o que revise el historial de URLs de un servidor intermedio) habría
  visto la key. En el header no forma parte de la URL, y `requests` lo descarta si una
  redirección lleva a otro host.
- El header lo pone un objeto **`auth=`** propio (`AutenticacionToken`, subclase de
  `requests.auth.AuthBase`, con `repr` enmascarado), no `headers=`: con `trust_env=True` (el
  valor por omisión de `requests.Session`) `requests` reemplaza un `Authorization` pasado por
  `headers=` con las credenciales de `~/.netrc` si hay una entrada para el host, y la
  autenticación fallaría. Un `auth=` explícito tiene prioridad sobre `.netrc`.
- La key tampoco aparece en nuestros logs (se loguea solo la ruta), mensajes de error, `repr`
  (se enmascara: `********ab12`) ni tracebacks: de las excepciones de `requests` se usa solo
  el tipo y las originales no se encadenan. Los textos de error de OXR se sanean por si la
  contienen.
- **Alcance de la garantía.** Se garantiza (y se prueba) que la key no va en la URL, que no
  aparece en los logs de `urllib3` en DEBUG y que no aparece en los mensajes, logs, `repr` ni
  trazas del propio programa. No se puede garantizar frente a un proxy que inspeccione el
  tráfico, un APM o cualquier herramienta que registre los headers de las solicitudes: eso
  depende de cómo se configuren, no de este código.

**Alternativas.** `?app_id=` en la query (es lo que muestra el enunciado y la forma más común
en los ejemplos de OXR; la primera versión lo usaba y confiaba en el saneamiento, pero el
saneamiento no alcanza a los logs de `urllib3`, que no controlamos: lo detectó la revisión de
código). Enmascarar con un filtro de logging sobre `urllib3` (frágil: depende del formato de
mensajes de otra librería).

**Consecuencias.** Tres tests: uno con sesión falsa provoca error de red, 401, 500 y JSON
malformado con la key "filtrada" en las respuestas y verifica que no aparece en el mensaje, el
traceback ni los logs; otro (`tests/adapters/test_cliente_oxr_http.py`) recorre el camino HTTP
real (`requests` + `urllib3`) contra un servidor local en `127.0.0.1`, con `urllib3` en DEBUG,
y verifica que la URL no lleva query, que el header es `Token <app_id>` y que la key no aparece
en ningún registro. Un tercero usa la sesión real (`trust_env=True`) con un `.netrc` falso en un
`HOME` temporal y verifica que al servidor llega `Token <app_id>` y no las credenciales de
`.netrc`.

## 15. Cliente HTTP: timeout, reintentos y mapeo de errores

**Contexto.** La red falla; OXR responde errores con un JSON `{status, message, description}`.

**Decisión.** `ClienteOpenExchangeRates`:

- Timeout configurable (10 s por defecto, `OXR_TIMEOUT`).
- Hasta 3 intentos con backoff exponencial (0,5 s, 1 s, acotado a 30 s) **solo para lo
  transitorio**: 5xx, timeouts, errores de conexión y 429 **sin** un `message` conocido. En
  429 se respeta `Retry-After`.
- El error se clasifica por el campo **`message`** del cuerpo JSON de OXR (tabla de
  <https://docs.openexchangerates.org/reference/errors>), no solo por el status HTTP, y
  **ninguno de estos se reintenta**:

  | `message` | Excepción | ¿Fatal para el lote? |
  |---|---|---|
  | `missing_app_id`, `invalid_app_id` | `ErrorCredencialesProveedor` ("revisa OXR_APP_ID") | sí |
  | `not_allowed` | `ErrorPlanNoPermitido` (el plan no permite esa ruta o función) | sí |
  | `access_restricted` | `AccesoRestringido` (acceso restringido; el motivo, p. ej. uso excesivo, viene en `description` y se muestra) | sí |
  | `invalid_date`, `not_available` | `ErrorFechaProveedor` (sin tasas para esa fecha) | no: la fecha queda sin tasas |

  Sin `message` conocido se usa el status: 401/403 → `ErrorCredencialesProveedor` (un 401 lo
  es siempre, aunque traiga un `message` que no está en la tabla); 429 →
  se reintenta y, si persiste, `CuotaExcedida`; 5xx → se reintenta y luego
  `ErrorProveedorTasas`; otros 4xx (p. ej. 404 `not_found`) → `ErrorProveedorTasas` sin
  reintento.
- JSON malformado no se reintenta (reintentar no lo arregla).
- Las tasas se validan (objeto `rates` no vacío, valores numéricos finitos > 0).
- La sesión HTTP y la función `dormir` se inyectan: los tests no tocan la red ni esperan.

**Alternativas.** Mapear solo por status (la primera versión lo hacía: trataba 403 como
credenciales y todo 429 como cuota con reintentos; pero OXR usa `not_allowed` para "tu plan no
incluye esto", que no es cuota y no mejora reintentando — lo detectó la revisión de código);
`urllib3.Retry` montado en la sesión (reintenta por status sin mirar el cuerpo y es más
difícil de probar); `tenacity` (otra dependencia).

**Consecuencias.** Los errores definitivos fallan rápido y sin gastar cuota; los fatales
abortan el lote con un mensaje accionable (código 2, sin traceback). Un 429 persistente se
informa como `CuotaExcedida` y se sugiere la caché o `--offline`; `access_restricted` se
informa como `AccesoRestringido` con la `description` de OXR, sin afirmar que sea cuota.

## 16. Errores: excepciones de dominio y lotes tolerantes a filas malas

**Contexto.** Se evalúa el manejo de errores y una fila mala no debe botar el lote.

**Decisión.** Jerarquía bajo `XpenditError`: `PoliticaInvalida` (acumula todos los problemas
con su ruta, p. ej. `limites_por_categoria.food.pendiente_hasta`), `ArchivoInvalido`,
`FilaInvalida` (línea, gasto_id y motivo), `ConfiguracionInvalida`, `ConversionNoDisponible` y
`ErrorProveedorTasas`. El lector CSV acumula `FilaInvalida` (monto no numérico, moneda o fecha
inválida, campos faltantes, columnas de más, id repetido) y sigue; el reporte las lista. La CLI
captura `XpenditError` y muestra solo el mensaje.

**Alternativas.** Abortar ante la primera fila mala; ignorarla en silencio.

**Consecuencias.** Errores accionables para el usuario y bugs reales (excepciones no previstas)
siguen mostrando traceback, como debe ser.

## 17. Modo offline con tasas de ejemplo

**Contexto.** Quien evalúa puede no tener API key, y los tests y la CI no deben depender de
la red; aun así, el análisis completo debe poder generarse.

**Decisión.** `--offline` usa `ProveedorTasasFijas` con tasas redondas aproximadas, iguales para
todas las fechas: 900 CLP, 17,5 MXN y 0,92 EUR por USD. Se eligieron porque los montos del CSV
parecen construidos sobre esos valores (81 000 / 126 000 / 144 000 CLP = 90 / 140 / 160 USD;
1 750 / 2 100 / 3 500 MXN = 100 / 120 / 200 USD; 92 EUR = 100 USD). Un `ANALISIS.md` generado
con `--offline` lo advierte en un recuadro y en un anexo.

**Alternativas.** Inventar cotizaciones "realistas" por fecha (aparentarían una precisión que no
tienen).

**Consecuencias.** Con tasas reales pueden cambiar algunos gastos: el reporte incluye una tabla
de sensibilidad (p. ej. `g_006`, 144 000 CLP, pasa de RECHAZADO a PENDIENTE si el USD vale
unos 960 CLP o más). El análisis definitivo se obtiene corriendo el mismo comando sin `--offline`.

**Resultado con la API real.** El `ANALISIS.md` versionado se regeneró con Open Exchange Rates
(9 solicitudes HTTP; 0 en la segunda corrida, por la caché) y es el resultado oficial:
**8 APROBADOS / 18 PENDIENTES / 24 RECHAZADOS**, frente a 8 / 17 / 25 en modo `--offline`. El
único gasto que cambia de estado es el que anticipaba la tabla: el 2026-09-17 el USD valía
960,57 CLP, así que `g_006` son 149,91 USD, 9 centavos bajo el máximo de 150 de `food`, y pasa de
RECHAZADO a PENDIENTE (por antigüedad de 39 días y por límite de categoría). Los demás montos
en moneda extranjera se mueven (p. ej. 1 750 MXN = 103,12 USD en vez de 100) sin cambiar de
estado.

## 18. `ANALISIS.md` generado desde los datos

**Contexto.** El análisis debe poder regenerarse con la API real o con otra fecha.

**Decisión.** Todo `ANALISIS.md` (cifras, tablas y frases de hallazgos) sale de
`adapters/reporte/markdown.py` a partir del `ReporteLote`; las agregaciones viven en
`application/hallazgos.py` como funciones puras. No incluye la hora de generación, así que la
salida es determinista (hay un test que lo verifica).

**Alternativas.** Escribir el análisis a mano (quedaría desactualizado al cambiar tasas o fecha).

**Consecuencias.** Regenerar es un comando. Los textos interpretativos son prudentes y se
apoyan en los números que calculan.

---

## 19. Portabilidad: Windows, macOS y Linux

**Contexto.** El desarrollo fue en Linux, pero el proyecto se puede clonar en Windows o macOS. Las
diferencias que rompen un programa Python son pocas y conocidas: la codificación por defecto
(cp1252 en Windows), la página de códigos de la consola, el fin de línea (CRLF), el separador de
rutas, la falta de `make` y los detalles de `os.replace`.

**Decisión.**
- Todo archivo se abre con `encoding=` explícito; el CSV de entrada con `utf-8-sig` y
  `newline=""` (tolera el BOM y el CRLF de Excel) y `.env` con `utf-8-sig`. En la CI,
  `PYTHONWARNDEFAULTENCODING=1` hace fallar un test ante cualquier `open()` sin codificación.
- `cli.main` reconfigura `stdout`/`stderr` a UTF-8 con `errors="replace"`: una consola cp1252 o
  cp850 no puede terminar la corrida con `UnicodeEncodeError`.
- Los reportes y la caché se escriben con `newline="\n"`, y `.gitattributes` fija LF en el
  checkout; el reporte muestra las rutas con `/`. El mismo comando produce el mismo
  `ANALISIS.md` byte a byte en los tres sistemas.
- Caché: `os.replace` sobre un temporal ya cerrado (en Windows no se puede reemplazar con un
  archivo abierto); si falla, se borra el temporal y solo se pierde esa escritura.
- Los atajos de desarrollo están en `tareas.py` (solo biblioteca estándar y `sys.executable`)
  y no en un `Makefile`, porque `make` no viene en Windows.
- La CI corre los tests y la CLI en `ubuntu-latest`, `windows-latest` y `macos-latest` con
  Python 3.12 y 3.13.

**Alternativas.** Exigir WSL o Docker en Windows (más fricción para quien evalúa); activar el
modo UTF-8 de Python (`PYTHONUTF8=1`) en vez de corregir el código (depende de que cada persona lo
configure); `tox`/`nox` o `just` en vez de `tareas.py` (una dependencia más para cuatro comandos).

**Consecuencias.** Lo específico de Windows está cubierto por tests que en Linux se ejercitan
simulándolo (consola cp1252, `os.replace` bloqueado, CSV de Excel, `.env` en UTF-16), y por un
test y pasos de la CI que solo corren en Windows (rutas con `\`, PowerShell). Además, la suite
completa (413 tests), `ruff`, `mypy` y el analizador se ejecutaron en Windows 11; la CI los
repite en los tres sistemas.

---

## Limitaciones conocidas y próximos pasos

- El flujo real contra la API ya se validó con una key (9 solicitudes HTTP, resultado 8/18/24);
  los tests siguen usando respuestas simuladas con el formato documentado por OXR, para no
  depender de la red ni gastar cuota.
- El empleado se toma de cada fila del CSV; si un mismo `empleado_id` trae datos distintos en
  filas diferentes, no se detecta.
- La caché en disco no expira ni tiene límite de tamaño (las tasas históricas no cambian, así
  que no es un problema práctico).
- Si el volumen creciera mucho, el plan pagado de OXR permite `time-series` (un rango de fechas
  en una sola solicitud) y `symbols` para reducir el payload; ambos encajan como otro adaptador
  del mismo puerto.
