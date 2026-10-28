# Uso de IA

El enunciado incentiva usar IA y valora el criterio con que se usa. Aquí explico cómo la usé,
qué decidí yo y cómo verifiqué el resultado.

## Cómo trabajé

Un agente de IA (Claude Code) escribió gran parte del código, los tests y la documentación a
partir de mis prompts y de las decisiones que fijé en ellos. Otro agente, de otro proveedor
(Codex), revisó el repositorio en modo solo lectura. Yo validé cada hallazgo y cada cambio,
integré el resultado y respondo por él. Los commits están a mi nombre por eso, no porque haya
escrito cada línea.

1. **Especificación.** Leí el enunciado y escribí un prompt de implementación con los requisitos
   y una lista de decisiones ya tomadas que el agente debía respetar. Las que dejé abiertas
   debían justificarse por escrito en [`DECISIONES.md`](DECISIONES.md).
2. **Implementación.** El agente construyó la solución en commits por paso lógico, con tests,
   `ruff` y `mypy --strict`, sin Internet y sin API key (modo `--offline`).
3. **Revisión cruzada.** El agente revisor recibió un prompt propio: correctitud contra el
   enunciado, conversión de moneda, cliente HTTP, secretos, N+1, diseño, tests y documentación,
   incluido recalcular el desglose a mano.
4. **Correcciones.** Revisé cada hallazgo contra el código antes de aceptarlo. Cada corrección
   empezó por un test que fallaba con el código anterior.
5. **Segunda revisión** del mismo revisor sobre las correcciones, con el mismo método.

## Qué decidí yo

Antes de escribir código:

- Python 3.12+, dependencias mínimas y `Decimal` para dinero.
- Arquitectura hexagonal, reglas como Strategy y un motor que no cambia al agregar reglas.
- Fecha de referencia inyectada (nunca `date.today()` en el dominio); el análisis usa
  2026-10-26, la fecha en que recibí el desafío.
- Moneda sin tasa y fecha futura → PENDIENTE con alerta: que lo vea una persona.
- Duplicados con la definición del enunciado, pero mostrando con datos la versión estricta
  (+ empleado + categoría), porque en este CSV hay coincidencias entre personas distintas.
- Una consulta por fecha única, con caché; nunca llamar a la API real sin key.
- La key solo en `.env`, nunca en logs ni en mensajes de error.

Después, validé las decisiones que dejé al agente (monto ≤ 0 → RECHAZADO; duplicado →
PENDIENTE; consultar solo las fechas con gastos en moneda extranjera; caché en disco solo para
días cerrados; fallas fatales que abortan el lote frente a fallas de una fecha que no lo
abortan) y, tras la revisión, elegí que la falta de tasa fuera una regla propia y no un parche
en el caso de uso, y que la key viajara en un header.

## Hallazgos de la revisión y cómo los corregí

Primera revisión (6 hallazgos, todos reales; ninguno descartado):

| Severidad | Hallazgo | Corrección |
|---|---|---|
| Alta | Un gasto en moneda sin tasa, en una categoría sin límite (p. ej. `software` en EUR), quedaba **APROBADO** sin alertas. | Regla propia `ReglaConversionMoneda`: la falta de tasa da al menos PENDIENTE con `TASA_NO_DISPONIBLE` en cualquier categoría. El total del desglose dice cuántos montos quedaron fuera. |
| Alta | El App ID iba en la query de la URL, y `urllib3` registra la URL completa en nivel DEBUG. | Header `Authorization: Token <app_id>`. Test por el camino HTTP real contra un servidor local, con `urllib3` en DEBUG. |
| Media | `not_allowed` (el plan no permite la ruta) se trataba como cuota agotada y se reintentaba. | Errores clasificados por el `message` de OXR; solo se reintentan 5xx, errores de red y 429 sin `message` conocido. |
| Media | La caché en disco aceptaba tasas `NaN`, infinitas, cero o negativas. | Validación al leer; ante cualquier problema se ignora el archivo y se vuelve a consultar. |
| Media | El reporte prometía «quedan PENDIENTE» y caché en disco aunque no siempre fuera así. | Textos según la prioridad real y el modo de tasas usado en la corrida. |
| Media | `OXR_TIMEOUT=NaN` pasaba la validación. | Se exige un número finito y mayor que 0. |

Segunda revisión: un 401 con un `message` desconocido no detenía el lote; `requests` podía
reemplazar el header `Authorization` por credenciales de `~/.netrc`; la caché no comprobaba que
la fecha del archivo fuera la pedida; y la garantía sobre el secreto estaba escrita de forma
demasiado absoluta. Corregí los cuatro, cada uno con su test (el de `.netrc`, con una sesión
real y un `.netrc` falso).

## Cómo lo verifiqué

- **Recálculo independiente.** El revisor recalculó el desglose a mano con las tasas de ejemplo
  (8 / 17 / 25). Después de las correcciones lo recalculé con un script aparte que no importa el
  paquete: mismo resultado, mismos grupos de duplicados y mismas fechas consultadas.
- **API real.** Con mi App ID regeneré `ANALISIS.md`: 9 solicitudes HTTP (0 en la segunda
  corrida, por la caché) y 8 / 18 / 24. El único cambio frente al modo offline es `g_006`
  (144 000 CLP = 149,91 USD con la tasa del día), que pasa de RECHAZADO a PENDIENTE, como
  anticipaba la tabla de sensibilidad del reporte.
- **Tests y calidad.** 413 tests sin Internet, 99 % de cobertura, `ruff` y `mypy --strict`
  limpios. Los corrí en Linux y en Windows; en Windows aparecieron dos tests que dependían del
  sistema o de la versión de Python, y los corregí. La CI los corre en Linux, Windows y macOS.

## Límites

- Contra la API real corrí el CSV del desafío, no sus casos de error (key inválida, cuota
  agotada): esos están probados con respuestas simuladas con el formato documentado por OXR.
- El revisor leyó el código sin ejecutarlo; la ejecución la cubren los tests y el recálculo.
- Una revisión por IA no reemplaza el criterio: los hallazgos los validé uno por uno contra el
  código, y las decisiones de negocio son mías.
