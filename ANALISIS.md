# Análisis del lote de gastos históricos

> Archivo generado con `python -m xpendit analizar data/gastos_historicos.csv --fecha-referencia 2026-10-26`. No editar a mano: regenerar.

| Parámetro | Valor |
|---|---|
| Archivo de gastos | `data/gastos_historicos.csv` |
| Política | `config/politica.json` (moneda base USD) |
| Fecha de referencia | **2026-10-26** — la antigüedad (30/60 días) se mide contra esta fecha; con otra fecha el desglose cambia |
| Tasas de cambio | Open Exchange Rates, endpoint histórico (tasa del día de cada gasto), con caché en disco en .cache/tasas |

## Resumen

- **Desglose:** **8 APROBADOS, 18 PENDIENTES y 24 RECHAZADOS** de 50 gastos.
- **Anomalías:** **7 grupos de duplicados exactos** (9 copias marcadas); 5 mezclan empleados distintos, p. ej. `g_001` / `g_011`: 50 USD el 2026-10-07. Ningún monto negativo ni cero.
- **Optimización N+1:** **9 consultas** a la API para 50 gastos, una por fecha única con gastos en moneda distinta de USD, en vez de una por gasto.

## 1. Desglose por estado

Filas leídas: **50** · gastos válidos evaluados: **50** · filas inválidas omitidas: **0**.

| Estado | Gastos | % | Monto (USD) |
|---|---|---|---|
| **APROBADO** | 8 | 16.0 % | 915.00 |
| **PENDIENTE** | 18 | 36.0 % | 2041.55 |
| **RECHAZADO** | 24 | 48.0 % | 2412.38 |
| Total | 50 | 100.0 % | 5368.93 |

Todos los gastos tienen monto en USD (convertido con la tasa del día de cada gasto cuando la moneda es otra).

### Motivos (alertas)

Un gasto puede tener varias alertas; se conservan todas, no solo la que decidió el estado.

| Código | Gastos con la alerta | …en RECHAZADO | …en PENDIENTE | Significado |
|---|---|---|---|---|
| `LIMITE_ANTIGUEDAD` | 34 | 20 | 14 | Antigüedad sobre el umbral de la política |
| `LIMITE_CATEGORIA` | 13 | 7 | 6 | Monto (en moneda base) sobre el límite de la categoría |
| `DUPLICADO_EXACTO` | 9 | 5 | 4 | Mismo monto, moneda y fecha que un gasto anterior |
| `POLITICA_CENTRO_COSTO` | 4 | 4 | 0 | Categoría prohibida para el centro de costo |

## 2. Anomalías

### 2.1 Duplicados exactos (mismo monto, moneda y fecha)

Se aplica la definición del enunciado. En cada grupo el primer gasto del archivo se considera el original y no se marca; cada copia recibe la alerta `DUPLICADO_EXACTO` y queda al menos **PENDIENTE** (revisión humana: no se rechaza en automático). Si otra regla la rechaza, sigue rechazada.

Resultado: **7 grupos**, **9 gastos marcados** como copia.

| Grupo | Gasto | Rol | Empleado | Categoría | Monto | Fecha | Estado final |
|---|---|---|---|---|---|---|---|
| 1 | `g_001` | original | Bruno Soto | food | 50 USD | 2026-10-07 | APROBADO |
| 1 | `g_011` | copia de `g_001` | Ana Reyes | food | 50 USD | 2026-10-07 | RECHAZADO |
| 2 | `g_002` | original | Bruno Soto | food | 120 USD | 2026-10-02 | PENDIENTE |
| 2 | `g_012` | copia de `g_002` | Ana Reyes | food | 120 USD | 2026-10-02 | RECHAZADO |
| 3 | `g_025` | original | Bruno Soto | food | 120 USD | 2026-07-19 | RECHAZADO |
| 3 | `g_029` | copia de `g_025` | Ana Reyes | food | 120 USD | 2026-07-19 | RECHAZADO |
| 4 | `g_036` | original | Bruno Soto | transport | 70 USD | 2026-10-07 | APROBADO |
| 4 | `g_041` | copia de `g_036` | Eva Luna | transport | 70 USD | 2026-10-07 | PENDIENTE |
| 5 | `g_037` | original | Eva Luna | other | 150 USD | 2026-07-19 | RECHAZADO |
| 5 | `g_039` | copia de `g_037` | David Paz | other | 150 USD | 2026-07-19 | RECHAZADO |
| 5 | `g_047` | copia de `g_037` | David Paz | other | 150 USD | 2026-07-19 | RECHAZADO |
| 6 | `g_038` | original | Carla Mora | lodging | 130 EUR | 2026-08-28 | PENDIENTE |
| 6 | `g_050` | copia de `g_038` | Carla Mora | lodging | 130 EUR | 2026-08-28 | PENDIENTE |
| 7 | `g_042` | original | Bruno Soto | food | 90 USD | 2026-10-12 | APROBADO |
| 7 | `g_043` | copia de `g_042` | Bruno Soto | food | 90 USD | 2026-10-12 | PENDIENTE |
| 7 | `g_044` | copia de `g_042` | Bruno Soto | food | 90 USD | 2026-10-12 | PENDIENTE |

**Ojo con la definición.** Monto + moneda + fecha no mira quién rindió el gasto, así que en este archivo **5 de los 7 grupos** mezclan empleados distintos (probables coincidencias, no duplicados):

- `g_001` (Bruno Soto) / `g_011` (Ana Reyes): 50 USD el 2026-10-07
- `g_002` (Bruno Soto) / `g_012` (Ana Reyes): 120 USD el 2026-10-02
- `g_025` (Bruno Soto) / `g_029` (Ana Reyes): 120 USD el 2026-07-19
- `g_036` (Bruno Soto) / `g_041` (Eva Luna): 70 USD el 2026-10-07
- `g_037` (Eva Luna) / `g_039` (David Paz) / `g_047` (David Paz): 150 USD el 2026-07-19

Una versión más estricta agregaría empleado y categoría a la clave. Comparación:

| Criterio | Grupos | Gastos marcados |
|---|---|---|
| Enunciado: monto + moneda + fecha (aplicado) | 7 | 9 |
| Estricto: + empleado + categoría (informativo) | 3 | 4 |

Grupos que sobreviven al criterio estricto: `g_038` = `g_050`, `g_039` = `g_047`, `g_042` = `g_043` = `g_044`.

### 2.2 Montos negativos o cero

**No hay montos negativos ni cero en este archivo.** El detector existe y está cubierto por tests: un monto `<= 0` recibe la alerta `MONTO_INVALIDO` y queda **RECHAZADO** (no hay nada que reembolsar; una devolución o nota de crédito debe ir por otro flujo). Un monto no numérico se reporta como fila inválida.

### 2.3 Filas inválidas

Ninguna: todas las filas tienen el formato esperado.

## 3. Optimización N+1 de tasas de cambio

Sin agrupar, se pediría la tasa al convertir cada gasto (una llamada por gasto). El analizador, en cambio, agrupa las **fechas únicas** de los gastos que necesitan conversión, consulta **una sola vez por fecha** y evalúa todo contra esa instantánea en memoria (la evaluación no hace red). Los gastos ya expresados en la moneda base no necesitan tasa, así que sus fechas no se consultan.

| Métrica | Valor |
|---|---|
| Gastos evaluados | 50 |
| Gastos en moneda distinta de USD | 11 |
| Fechas únicas en el lote | 25 |
| Fechas únicas con gastos en moneda distinta de USD | 9 |
| **Consultas al proveedor de tasas** | **9** |
| Solicitudes HTTP reales (incluye reintentos; 0 si todo vino de caché) | 9 |
| Fechas sin tasas (sus gastos reciben `TASA_NO_DISPONIBLE`) | 0 |

Con el plan gratuito (~1000 solicitudes/mes) esto significa 9 solicitudes en vez de 50. Además, las tasas de días cerrados se guardan en una caché en disco (`.cache/tasas`), así que volver a correr el análisis no gasta cuota (la fila de solicitudes HTTP muestra 0 cuando todo vino de la caché).

## 4. Hallazgos de negocio

- **La antigüedad domina los rechazos:** 19 de 24 rechazos tienen más de 60 días a la fecha de referencia, y 13 de ellos se rechazan *solo* por eso. Son rendiciones tardías más que gastos indebidos: conviene recordar el plazo a los equipos (y el número depende directamente de la fecha de referencia).

- **`core_engineering` rindió `food` 4 veces** (`g_011`, `g_012`, `g_013`, `g_029`; Ana Reyes), todos rechazados por política. Total 336.80 USD. Sugiere que la restricción no es conocida en el equipo.

- **Quién concentra rechazos:** Bruno Soto (`sales_team`) con 7 de 14 gastos rechazados (740.00 USD). Detalle por empleado:

| Empleado | C.C. | Gastos | Aprobados | Pendientes | Rechazados | Monto rechazado (USD) |
|---|---|---|---|---|---|---|
| Bruno Soto | sales_team | 14 | 4 | 3 | 7 | 740.00 |
| Ana Reyes | core_engineering | 11 | 2 | 4 | 5 | 386.80 |
| Carla Mora | marketing | 9 | 0 | 4 | 5 | 535.58 |
| David Paz | finance | 9 | 1 | 3 | 5 | 550.00 |
| Eva Luna | sales_team | 7 | 1 | 4 | 2 | 200.00 |

- **Límites por categoría:** 13 gastos superan el monto de aprobación automática (13 en `food`).

- **Duplicados más probables:** los 3 grupos que coinciden también en empleado y categoría (`g_038` = `g_050` (Carla Mora, lodging, 130 EUR); `g_039` = `g_047` (David Paz, other, 150 USD); `g_042` = `g_043` = `g_044` (Bruno Soto, food, 90 USD)) son los primeros que revisaría un analista.

- **Sensibilidad a la tasa de cambio:** 9 gastos en moneda extranjera caen en una categoría con límite; su monto en USD se calculó con las tasas reales del día de cada gasto. Distancia al umbral más cercano:

| Gasto | Monto original | Monto USD | Umbral más cercano | Margen | Estado final |
|---|---|---|---|---|---|
| `g_004` | 81000 CLP | 85.51 | 100.00 (food) | -14.49 | PENDIENTE |
| `g_005` | 126000 CLP | 131.32 | 150.00 (food) | -18.68 | PENDIENTE |
| `g_006` | 144000 CLP | 149.91 | 150.00 (food) | -0.09 | PENDIENTE |
| `g_007` | 1750 MXN | 103.12 | 100.00 (food) | +3.12 | PENDIENTE |
| `g_008` | 2100 MXN | 123.91 | 100.00 (food) | +23.91 | PENDIENTE |
| `g_009` | 3500 MXN | 206.02 | 150.00 (food) | +56.02 | RECHAZADO |
| `g_010` | 92 EUR | 106.58 | 100.00 (food) | +6.58 | PENDIENTE |
| `g_013` | 45000 CLP | 46.80 | 100.00 (food) | -53.20 | RECHAZADO |
| `g_030` | 500 MXN | 29.56 | 200.00 (transport) | -170.44 | RECHAZADO |

## 5. Detalle por gasto

| Gasto | Empleado | C.C. | Categoría | Monto | USD | Fecha | Días | Estado | Alertas |
|---|---|---|---|---|---|---|---|---|---|
| `g_001` | Bruno Soto | sales_team | food | 50 USD | 50.00 | 2026-10-07 | 19 | **APROBADO** | — |
| `g_002` | Bruno Soto | sales_team | food | 120 USD | 120.00 | 2026-10-02 | 24 | **PENDIENTE** | `LIMITE_CATEGORIA`: Requiere revisión: 120 USD supera el límite de aprobación automática de 100 USD para 'food'. |
| `g_003` | Bruno Soto | sales_team | food | 160 USD | 160.00 | 2026-09-27 | 29 | **RECHAZADO** | `LIMITE_CATEGORIA`: Excede límite aprobado: 160 USD supera el máximo de 150 USD para 'food'. |
| `g_004` | Eva Luna | sales_team | food | 81000 CLP | 85.51 | 2026-09-22 | 34 | **PENDIENTE** | `LIMITE_ANTIGUEDAD`: Gasto excede los 30 días. Requiere revisión. |
| `g_005` | Eva Luna | sales_team | food | 126000 CLP | 131.32 | 2026-09-18 | 38 | **PENDIENTE** | `LIMITE_ANTIGUEDAD`: Gasto excede los 30 días. Requiere revisión.<br>`LIMITE_CATEGORIA`: Requiere revisión: 131.32 USD supera el límite de aprobación automática de 100 USD para 'food'. |
| `g_006` | Eva Luna | sales_team | food | 144000 CLP | 149.91 | 2026-09-17 | 39 | **PENDIENTE** | `LIMITE_ANTIGUEDAD`: Gasto excede los 30 días. Requiere revisión.<br>`LIMITE_CATEGORIA`: Requiere revisión: 149.91 USD supera el límite de aprobación automática de 100 USD para 'food'. |
| `g_007` | Carla Mora | marketing | food | 1750 MXN | 103.12 | 2026-09-12 | 44 | **PENDIENTE** | `LIMITE_ANTIGUEDAD`: Gasto excede los 30 días. Requiere revisión.<br>`LIMITE_CATEGORIA`: Requiere revisión: 103.12 USD supera el límite de aprobación automática de 100 USD para 'food'. |
| `g_008` | Carla Mora | marketing | food | 2100 MXN | 123.91 | 2026-09-07 | 49 | **PENDIENTE** | `LIMITE_ANTIGUEDAD`: Gasto excede los 30 días. Requiere revisión.<br>`LIMITE_CATEGORIA`: Requiere revisión: 123.91 USD supera el límite de aprobación automática de 100 USD para 'food'. |
| `g_009` | Carla Mora | marketing | food | 3500 MXN | 206.02 | 2026-09-02 | 54 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 30 días. Requiere revisión.<br>`LIMITE_CATEGORIA`: Excede límite aprobado: 206.02 USD supera el máximo de 150 USD para 'food'. |
| `g_010` | David Paz | finance | food | 92 EUR | 106.58 | 2026-08-28 | 59 | **PENDIENTE** | `LIMITE_ANTIGUEDAD`: Gasto excede los 30 días. Requiere revisión.<br>`LIMITE_CATEGORIA`: Requiere revisión: 106.58 USD supera el límite de aprobación automática de 100 USD para 'food'. |
| `g_011` | Ana Reyes | core_engineering | food | 50 USD | 50.00 | 2026-10-07 | 19 | **RECHAZADO** | `POLITICA_CENTRO_COSTO`: El C.C. 'core_engineering' no puede reportar 'food'.<br>`DUPLICADO_EXACTO`: Posible duplicado de g_001: mismo monto (50 USD) y fecha (2026-10-07). |
| `g_012` | Ana Reyes | core_engineering | food | 120 USD | 120.00 | 2026-10-02 | 24 | **RECHAZADO** | `LIMITE_CATEGORIA`: Requiere revisión: 120 USD supera el límite de aprobación automática de 100 USD para 'food'.<br>`POLITICA_CENTRO_COSTO`: El C.C. 'core_engineering' no puede reportar 'food'.<br>`DUPLICADO_EXACTO`: Posible duplicado de g_002: mismo monto (120 USD) y fecha (2026-10-02). |
| `g_013` | Ana Reyes | core_engineering | food | 45000 CLP | 46.80 | 2026-09-27 | 29 | **RECHAZADO** | `POLITICA_CENTRO_COSTO`: El C.C. 'core_engineering' no puede reportar 'food'. |
| `g_014` | Ana Reyes | core_engineering | software | 75 USD | 75.00 | 2026-09-22 | 34 | **PENDIENTE** | `LIMITE_ANTIGUEDAD`: Gasto excede los 30 días. Requiere revisión. |
| `g_015` | Ana Reyes | core_engineering | transport | 150 USD | 150.00 | 2026-09-18 | 38 | **PENDIENTE** | `LIMITE_ANTIGUEDAD`: Gasto excede los 30 días. Requiere revisión. |
| `g_016` | Bruno Soto | sales_team | software | 50 USD | 50.00 | 2026-08-12 | 75 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad. |
| `g_017` | Carla Mora | marketing | other | 50 USD | 50.00 | 2026-08-02 | 85 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad. |
| `g_018` | David Paz | finance | lodging | 50 USD | 50.00 | 2026-07-28 | 90 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad. |
| `g_019` | Eva Luna | sales_team | software | 50 USD | 50.00 | 2026-06-30 | 118 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad. |
| `g_020` | Ana Reyes | core_engineering | transport | 50 USD | 50.00 | 2026-06-21 | 127 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad. |
| `g_021` | Bruno Soto | sales_team | other | 50 USD | 50.00 | 2026-06-13 | 135 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad. |
| `g_022` | Carla Mora | marketing | software | 50 USD | 50.00 | 2026-05-24 | 155 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad. |
| `g_023` | David Paz | finance | lodging | 50 USD | 50.00 | 2026-05-08 | 171 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad. |
| `g_024` | Ana Reyes | core_engineering | lodging | 50 USD | 50.00 | 2026-10-19 | 7 | **APROBADO** | — |
| `g_025` | Bruno Soto | sales_team | food | 120 USD | 120.00 | 2026-07-19 | 99 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad.<br>`LIMITE_CATEGORIA`: Requiere revisión: 120 USD supera el límite de aprobación automática de 100 USD para 'food'. |
| `g_026` | Bruno Soto | sales_team | food | 160 USD | 160.00 | 2026-07-19 | 99 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad.<br>`LIMITE_CATEGORIA`: Excede límite aprobado: 160 USD supera el máximo de 150 USD para 'food'. |
| `g_027` | Bruno Soto | sales_team | food | 80 USD | 80.00 | 2026-06-03 | 145 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad. |
| `g_028` | Bruno Soto | sales_team | food | 120 USD | 120.00 | 2026-06-03 | 145 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad.<br>`LIMITE_CATEGORIA`: Requiere revisión: 120 USD supera el límite de aprobación automática de 100 USD para 'food'. |
| `g_029` | Ana Reyes | core_engineering | food | 120 USD | 120.00 | 2026-07-19 | 99 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad.<br>`LIMITE_CATEGORIA`: Requiere revisión: 120 USD supera el límite de aprobación automática de 100 USD para 'food'.<br>`POLITICA_CENTRO_COSTO`: El C.C. 'core_engineering' no puede reportar 'food'.<br>`DUPLICADO_EXACTO`: Posible duplicado de g_025: mismo monto (120 USD) y fecha (2026-07-19). |
| `g_030` | Carla Mora | marketing | transport | 500 MXN | 29.56 | 2026-08-23 | 64 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad. |
| `g_031` | David Paz | finance | lodging | 180 USD | 180.00 | 2026-10-17 | 9 | **APROBADO** | — |
| `g_032` | Eva Luna | sales_team | transport | 75 USD | 75.00 | 2026-10-12 | 14 | **APROBADO** | — |
| `g_033` | Carla Mora | marketing | software | 200 USD | 200.00 | 2026-07-10 | 108 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad. |
| `g_034` | David Paz | finance | transport | 85 USD | 85.00 | 2026-09-12 | 44 | **PENDIENTE** | `LIMITE_ANTIGUEDAD`: Gasto excede los 30 días. Requiere revisión. |
| `g_035` | Ana Reyes | core_engineering | software | 120 USD | 120.00 | 2026-08-28 | 59 | **PENDIENTE** | `LIMITE_ANTIGUEDAD`: Gasto excede los 30 días. Requiere revisión. |
| `g_036` | Bruno Soto | sales_team | transport | 70 USD | 70.00 | 2026-10-07 | 19 | **APROBADO** | — |
| `g_037` | Eva Luna | sales_team | other | 150 USD | 150.00 | 2026-07-19 | 99 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad. |
| `g_038` | Carla Mora | marketing | lodging | 130 EUR | 150.60 | 2026-08-28 | 59 | **PENDIENTE** | `LIMITE_ANTIGUEDAD`: Gasto excede los 30 días. Requiere revisión. |
| `g_039` | David Paz | finance | other | 150 USD | 150.00 | 2026-07-19 | 99 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad.<br>`DUPLICADO_EXACTO`: Posible duplicado de g_037: mismo monto (150 USD) y fecha (2026-07-19). |
| `g_040` | Ana Reyes | core_engineering | transport | 90 USD | 90.00 | 2026-09-07 | 49 | **PENDIENTE** | `LIMITE_ANTIGUEDAD`: Gasto excede los 30 días. Requiere revisión. |
| `g_041` | Eva Luna | sales_team | transport | 70 USD | 70.00 | 2026-10-07 | 19 | **PENDIENTE** | `DUPLICADO_EXACTO`: Posible duplicado de g_036: mismo monto (70 USD) y fecha (2026-10-07). |
| `g_042` | Bruno Soto | sales_team | food | 90 USD | 90.00 | 2026-10-12 | 14 | **APROBADO** | — |
| `g_043` | Bruno Soto | sales_team | food | 90 USD | 90.00 | 2026-10-12 | 14 | **PENDIENTE** | `DUPLICADO_EXACTO`: Posible duplicado de g_042: mismo monto (90 USD) y fecha (2026-10-12). |
| `g_044` | Bruno Soto | sales_team | food | 90 USD | 90.00 | 2026-10-12 | 14 | **PENDIENTE** | `DUPLICADO_EXACTO`: Posible duplicado de g_042: mismo monto (90 USD) y fecha (2026-10-12). |
| `g_045` | Bruno Soto | sales_team | food | 100 USD | 100.00 | 2026-10-07 | 19 | **APROBADO** | — |
| `g_046` | David Paz | finance | other | 150 USD | 150.00 | 2026-09-17 | 39 | **PENDIENTE** | `LIMITE_ANTIGUEDAD`: Gasto excede los 30 días. Requiere revisión. |
| `g_047` | David Paz | finance | other | 150 USD | 150.00 | 2026-07-19 | 99 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad.<br>`DUPLICADO_EXACTO`: Posible duplicado de g_037: mismo monto (150 USD) y fecha (2026-07-19). |
| `g_048` | David Paz | finance | other | 150 USD | 150.00 | 2026-06-03 | 145 | **RECHAZADO** | `LIMITE_ANTIGUEDAD`: Gasto excede los 60 días. Rechazado por antigüedad. |
| `g_049` | Ana Reyes | core_engineering | software | 300 USD | 300.00 | 2026-10-17 | 9 | **APROBADO** | — |
| `g_050` | Carla Mora | marketing | lodging | 130 EUR | 150.60 | 2026-08-28 | 59 | **PENDIENTE** | `LIMITE_ANTIGUEDAD`: Gasto excede los 30 días. Requiere revisión.<br>`DUPLICADO_EXACTO`: Posible duplicado de g_038: mismo monto (130 EUR) y fecha (2026-08-28). |

## 6. Supuestos y decisiones

- Estado final por prioridad: RECHAZADO > PENDIENTE > APROBADO; si ninguna regla aplica, PENDIENTE sin alertas.
- Antigüedad = días calendario entre la fecha del gasto y la fecha de referencia (2026-10-26). Fecha futura → PENDIENTE con alerta `FECHA_FUTURA`.
- Límites por categoría comparados en USD, con la tasa del día del gasto y el monto convertido redondeado a centavos. Categorías del lote sin límite configurado (lodging, other, software) no se evalúan por monto.
- Gasto en moneda extranjera sin tasa (para la moneda o la fecha), en cualquier categoría → alerta `TASA_NO_DISPONIBLE`: queda al menos PENDIENTE (no hay base para aprobarlo) y RECHAZADO si otra regla lo rechaza; su monto no entra en los totales.
- Duplicado = mismo monto, moneda y fecha (definición del enunciado); el primero del archivo es el original; las copias quedan al menos PENDIENTE (RECHAZADO si otra regla las rechaza).
- Monto negativo o cero → RECHAZADO con alerta `MONTO_INVALIDO`.
- Detalle y alternativas consideradas: [`docs/DECISIONES.md`](docs/DECISIONES.md).
