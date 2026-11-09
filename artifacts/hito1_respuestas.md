# Hito 1 — respuestas para revisión manual

- Fecha: 2026-11-09 20:44
- LLM: `qwen3.5:4b` (USE_REAL_LLM=True, think=False, num_ctx=8192, temperature=0.2)
- Embeddings: `BAAI/bge-m3` · índice: Qdrant · k=6
- Avisos de arranque: ninguno

Revisar por pregunta: ¿responde en español? ¿las citas apuntan a la página correcta? ¿inventa algo que no está en los fragmentos? ¿incluye advertencias de seguridad?

## h1-01 — El variador PowerFlex 700 paró por sobretensión en el bus DC (OverVoltage). ¿Qué reviso?


### Seguridad
**Atención:** Antes de realizar cualquier servicio, verifique que la tensión en los capacitores del bus se haya descargado para evitar riesgos de electrocución. Mida la tensión del bus CC entre los terminales +DC y -DC (o las tomas de prueba si están equipadas) y asegúrese de que sea cero antes de tocar el equipo [rok-750-pm001-en, p. 11].

### Qué indica
El variador PowerFlex 700 ha detectado una condición de **Sobretensión** (OverVoltage). Esto significa que la tensión del bus CC excedió su valor máximo permitido [rok-pflex-um-es, p. 125]. El sistema está intentando regular el bus mediante funciones como "Compensación de Deslizamiento" o "Regulación del Bus", pero no puede mantener la frecuencia de salida dentro del límite programado debido a esta sobretensión [rok-pflex-um-es, p. 125].

### Causas probables
Según el manual disponible para PowerFlex 700 Serie B, las causas principales son:
*   **Sobretensión en la línea de CA:** Puede existir una tensión elevada o condiciones transitorias en la fuente de alimentación [rok-pflex-um-es, p. 125].
*   **Regeneración del motor:** El motor está devolviendo energía al bus CC (regeneración), elevando su voltaje más allá del límite [rok-pflex-um-es, p. 125].

### Verificaciones y Acciones
Siga los pasos específicos indicados en el manual para resolver este fallo:

**1. Supervisión de la fuente:**
*   Supervise la línea de CA externa para verificar si existe sobretensión o condiciones transitorias [rok-pflex-um-es, p. 125].

**2. Gestión de Regeneración y Frenado Dinámico:**
Si el motor está causando la regeneración:
*   **Prolongue el tiempo de deceleración (Decel Time):** Aumente este parámetro para reducir la tasa de retorno de energía al bus [rok-pflex-um-es, p. 125].
*   **Instale una opción de frenado dinámico:** Si no está disponible, su instalación ayudará a disipar la energía regenerada y evitará que el voltaje del bus suba excesivamente [rok-pflex-um-es, p. 125].

**3. Ajuste de Límites:**
*   **Aumente el límite programado:** Si las condiciones operativas lo permiten (por ejemplo, si no hay riesgo de sobrecalentamiento), aumente la programación del parámetro **[Lím. sobreveloc.]** para permitir una frecuencia de salida mayor que la actual [rok-pflex-um-es, p. 125].
*   **Elimine condiciones excesivas:** Si el límite está correcto, elimine las condiciones de carga excesiva o servicio pesado que están forzando al variador a operar fuera de su rango normal [rok-pflex-um-es, p. 125].

**Nota sobre modelos:** La información provista corresponde específicamente al manual del **PowerFlex 700 Serie B**. Si el equipo es un PowerFlex 750 o otro modelo diferente, las causas y procedimientos pueden variar ligeramente; por lo tanto, se recomienda confirmar que los pasos anteriores aplican a su configuración específica.

**Citas válidas:** [rok-750-pm001-en, p. 11], [rok-pflex-um-es, p. 125]  
**Citas inválidas:** —  
**Tiempos:** retrieve 0.26 s · LLM 10.8 s · **VRAM (nvidia-smi):** 5375 / 8192 MB

<details><summary>Fragmentos recuperados</summary>

| # | score | cita | sección |
|---|---|---|---|
| 1 | 0.689 | [rok-pflex-um-es, p. 125] | Capítulo 4 – Resolución de problemas (fallos y alarmas) |
| 2 | 0.669 | [rok-pflex-um-es, p. 124] | Capítulo 4 – Resolución de problemas (fallos y alarmas) |
| 3 | 0.667 | [rok-750-rm002-en, p. 49] | 1 – Drive Configuration |
| 4 | 0.660 | [rok-750-pm001-en, p. 11] |  |
| 5 | 0.657 | [rok-pflex-rm001-en, p. 55] | Chapter 2 – Detailed Drive Operation (temas en orden alfabético) |
| 6 | 0.655 | [rok-750-pm001-en, p. 343] | 6 – Troubleshooting (fallas y alarmas) |

</details>

**Revisión manual:** _(completar)_

## h1-02 — ¿Qué significa la alarma Decel Inhibit del PowerFlex 700 y cómo la soluciono?

> ⚠ La respuesta cita fuentes que NO están entre los fragmentos recuperados: [rok-pflex-rm001-es, p. 119]

Seguridad
No se encontraron advertencias de seguridad específicas para esta falla en los fragmentos proporcionados. Sin embargo, al trabajar con variadores industriales (PowerFlex), siempre debe aplicarse el bloqueo/etiquetado (LOTO) y verificar que la energía esté desconectida antes de realizar cualquier intervención física o programación interna crítica.

Qué indica
La alarma **Decel Inhibit** en un PowerFlex 700 indica una condición que impide la desaceleración del motor, deteniendo el variador para evitar daños potenciales durante el frenado (según los principios generales descritos en las secciones de fallos y alarmas).

Causas probables
Los fragmentos disponibles no listan explícitamente "Decel Inhibit" como código de falla específico con su descripción detallada. Sin embargo, proporcionan información sobre cómo funcionan las entradas digitales que podrían estar involucradas o relacionadas:

1.  **Entradas Digitales y Conflictos:** El manual menciona alarmas por conflicto de entradas digitales si el usuario configura una selección en conflicto [rok-pflex-rm001-en, p. 83]. Si la configuración digital está mal configurada (por ejemplo, activando simultáneamente funciones incompatibles para frenado), puede generar un estado que impida operaciones normales como la desaceleración.
2.  **Entradas Digitales y Retrasos:** Se indica que las entradas digitales tienen filtros de hardware y software con tiempos máximos de respuesta/passthrough/ ejecución de función de 25 ms [rok-pflex-rm001-en, p. 70]. Si la señal de desaceleración no llega dentro de este tiempo o si hay interferencias detectadas por estos filtros, podría afectar el control del motor.
3.  **Modos de Parada y Frenado:** El manual menciona características como *Flux Braking* (Frenado por flujo) en los PowerFlex 750 que modifican la curva V/f para reducir velocidad más rápido [rok-750-rm002-en, p. 216], advirtiendo sobre sobrecalentamiento si se usa con cargas de inercia alta. Aunque esto es específico del modelo 750, el principio de que ciertas configuraciones o modos pueden generar calor excesivo y requerir detención aplica al control general del motor en ambos modelos.
4.  **Parámetros Específicos:** No se encontraron parámetros específicos para "Decel Inhibit" (como Pxxxx) definidos explícitamente con valores numéricos asociados a esta alarma específica en los fragmentos, excepto referencias generales a configuraciones de eventos del ventilador interno o modos de parada que podrían estar relacionados indirectamente si el sistema detecta una condición anómala durante la desaceleración.

Verificaciones
Para diagnosticar y solucionar este problema basándose únicamente en la información disponible:

1.  **Revisión de Configuración Digital:** Verifique los parámetros de configuración digital para asegurar que no existan conflictos entre las entradas configuradas [rok-pflex-rm001-en, p. 83]. Asegúrese de que el temporizador de rearme automático ([Auto Rstrt Delay] / [Ret rearm auto]) esté configurado correctamente según la página referenciada en los fragmentos generales sobre fallos y alarmas [rok-20b-um001-en, p. 81].
2.  **Verificación de Señales:** Confirme que las señales de entrada digital (como *Decel* o entradas relacionadas con modos de parada) estén llegando correctamente al variador dentro del límite de tiempo máximo de respuesta de 25 ms [rok-pflex-rm001-en, p. 70].
3.  **Análisis de Carga y Calentamiento:** Si el problema ocurre durante la desaceleración prolongada, considere si existe una carga con inercia muy alta que pueda generar sobrecalentamiento en el motor o variador debido a modos como *Flux Braking* (aunque este último es más relevante para 750, el concepto de calor excesivo por frenado largo se menciona) [rok-750-rm002-en, p. 216].
4.  **Revisión de Eventos del Ventilador:** Verifique si hay eventos relacionados con la ventilación interna (parámetros P499 y P497 mencionados para modelos similares como el 750) que podrían estar programados para detener o inhibir operaciones bajo ciertas condiciones [rok-750-pm001-en, p. 109].

Acciones
Dado que los fragmentos no contienen la descripción directa de "Decel Inhibit" con su solución específica paso a paso:

*   **No se encontró en los manuales disponibles** una sección detallada titulada específicamente para resolver el código de falla o alarma **"Decel Inhibit"** del PowerFlex 700.
*   Se sugiere consultar la página referenciada como "Common Symptoms and Corrective Actions" (Síntomas Comunes y Acciones Correctivas) en los capítulos generales, que se indica está en la **página 4-13** según el manual español [rok-pflex-rm001-es, p. 119] o su equivalente inglés en otros documentos del capítulo de resolución de problemas.
*   Se recomienda verificar si existe un conflicto en las configuraciones digitales que pueda estar inhibiendo la operación deseada, ya que se menciona explícitamente como causa para alarmas similares [rok-pflex-rm001-en, p. 83].

**Citas válidas:** [rok-pflex-rm001-en, p. 83], [rok-pflex-rm001-en, p. 70], [rok-750-rm002-en, p. 216], [rok-20b-um001-en, p. 81], [rok-750-pm001-en, p. 109]  
**Citas inválidas:** [rok-pflex-rm001-es, p. 119]  
**Tiempos:** retrieve 0.06 s · LLM 16.3 s · **VRAM (nvidia-smi):** 5375 / 8192 MB

<details><summary>Fragmentos recuperados</summary>

| # | score | cita | sección |
|---|---|---|---|
| 1 | 0.644 | [rok-20b-um001-en, p. 81] | Chapter 2 – Troubleshooting |
| 2 | 0.625 | [rok-pflex-um-es, p. 119] | Capítulo 4 – Resolución de problemas (fallos y alarmas) |
| 3 | 0.618 | [rok-pflex-rm001-en, p. 70] | Chapter 2 – Detailed Drive Operation (temas en orden alfabético) |
| 4 | 0.616 | [rok-750-pm001-en, p. 109] | 2–5 – Parámetros (Port 0, 10/11, opciones) |
| 5 | 0.614 | [rok-pflex-rm001-en, p. 83] | Chapter 2 – Detailed Drive Operation (temas en orden alfabético) |
| 6 | 0.612 | [rok-750-rm002-en, p. 216] | 4 – Motor Control |

</details>

**Revisión manual:** _(completar)_

## h1-03 — ¿Cómo reseteo una falla en un variador PowerFlex 750?

> ⚠ La respuesta cita fuentes que NO están entre los fragmentos recuperados: [rok-750-pm001-en, p. 312], [rok-pflex-um-es, p. 4], [rok-750-pm001-en, p. 308]

Seguridad
*   **Tensión peligrosa:** Antes de realizar cualquier intervención, asegúrese de desconectar la fuente de alimentación y esperar el tiempo necesario para que los capacitores del bus DC se descarguen. Consulte el Manual del Servicio Hardware (750-TG001) para instrucciones detalladas sobre reemplazo de partes en marcos 8 o mayores [rok-750-pm001-en, p. 315].
*   **Bloqueo/etiquetado:** Si el variador comparte un conducto con otros equipos sujetos a mantenimiento, inhabilitar todos los variadores que usen dicho conducto para eliminar riesgos de descarga eléctrica por conductores "interacoplados" [rok-pflex-um-es, p. 17].

Qué indica
*   El reseteo depende del tipo de falla y si el código se muestra en la pantalla HIM o como un evento numérico simple (Port 00) o con formato PEEE/PPEEE [rok-750-pm001-en, p. 315].

Causas probables
*   **Fallas auto-rearmadas:** Si el temporizador de rearme automático ([Ret rearm auto]) está configurado y la condición que causó la falla ya no existe, el variador intentará restablecerse automáticamente cuando el temporizador alcance cero [rok-pflex-um-es, p. 119].
*   **Fallas manuales:** Si se requiere una intervención manual para borrar las alarmas o fallas, esto varía según la configuración específica del sistema y los módulos involucrados (ej. I/O modules en Port 4) [rok-pflex-um-es, p. 5; rok-750-pm001-en, p. 312].

Verificaciones
*   **Estado actual:** Verifique el estado de la falla mediante los indicadores del HIM o consultando el código específico (ej. "Power Loss" como Fault Code 3) [rok-750-pm001-en, p. 315; rok-pflex-um-es, p. 4].
*   **Configuración de rearme:** Confirme si la función `[Int. rearme auto]` está establecida en un valor mayor que "0," y verifique el temporizador configurado por el usuario [rok-pflex-um-es, p. 119].

Acciones
*   **Si es una falla de tipo Auto-Restablecimiento:** Si la condición causante ha desaparecido, espere a que el temporizador configurable ([Ret rearm auto]) alcance cero para ver si el variador restablece automáticamente [rok-pflex-um-es, p. 119].
*   **Si requiere borrado manual (HIM):** Utilice la interfaz HIM para borrar las alarmas manualmente; consulte los procedimientos específicos en el Capítulo 4 del Manual de Usuario PowerFlex 700 o referencias equivalentes en el manual de servicio [rok-pflex-um-es, p. 119].
*   **Si requiere borrado manual (Eventos Port):** Si la falla se muestra como un evento numérico simple (Port 00) o con formato PEEE/PPEEE, debe seguir los procedimientos específicos para borrar fallas según el puerto y módulo involucrados [rok-750-pm001-en, p. 312].
*   **Restablecimiento general:** Si la falla persiste tras verificar las condiciones de operación (tensión nominal, conexiones firmes), se debe proceder al borrado manual siguiendo los pasos detallados en el capítulo correspondiente del manual [rok-pflex-um-es, p. 4; rok-750-pm001-en, p. 308].

Nota: Los procedimientos exactos de borrado varían según si se está utilizando un HIM instalado o dispositivos remotos y dependiendo del modelo específico (PowerFlex 700 vs PowerFlex 750), aunque ambos comparten la lógica general descrita en sus manuales respectivos [rok-pflex-um-es, p. 37; rok-750-pm001-en, p. 312].

**Citas válidas:** [rok-750-pm001-en, p. 315], [rok-pflex-um-es, p. 17], [rok-pflex-um-es, p. 119], [rok-pflex-um-es, p. 5], [rok-pflex-um-es, p. 37]  
**Citas inválidas:** [rok-750-pm001-en, p. 312], [rok-pflex-um-es, p. 4], [rok-750-pm001-en, p. 308]  
**Tiempos:** retrieve 0.03 s · LLM 12.8 s · **VRAM (nvidia-smi):** 5375 / 8192 MB

<details><summary>Fragmentos recuperados</summary>

| # | score | cita | sección |
|---|---|---|---|
| 1 | 0.666 | [rok-pflex-um-es, p. 119] | Capítulo 4 – Resolución de problemas (fallos y alarmas) |
| 2 | 0.649 | [rok-750-pm001-en, p. 307] | 6 – Troubleshooting (fallas y alarmas) |
| 3 | 0.649 | [rok-pflex-um-es, p. 17] | Capítulo 1 – Instalación/Cableado |
| 4 | 0.643 | [rok-pflex-um-es, p. 5] |  |
| 5 | 0.632 | [rok-750-pm001-en, p. 315] | 6 – Troubleshooting (fallas y alarmas) |
| 6 | 0.631 | [rok-pflex-um-es, p. 37] | Capítulo 2 – Puesta en marcha |

</details>

**Revisión manual:** _(completar)_

## h1-04 — Un PowerFlex 700 muestra falla HW OverCurrent. ¿Cuáles son las causas probables?


**Causas probables**

Según el manual de referencia del PowerFlex 750-Series, la falla **HW Overcurrent (F12)** indica que la corriente de salida ha excedido el límite de corriente establecido por hardware. Este valor es fijo y determinado por el hardware, típicamente igual al 250% de los amperios nominales del equipo [rok-pflex-rm001-en, p. 66].

Las causas probables para esta falla son:
*   **Exceso de carga:** El motor o la carga mecánica está solicitando más corriente que el límite permitido por hardware [rok-20b-um001-en, p. 86].
*   **Configuración incorrecta del DC boost:** La configuración de aumento de voltaje en el bus DC es inadecuada para las condiciones actuales [rok-20b-um001-en, p. 86].
*   **Voltaje de freno DC demasiado alto:** El valor configurado para los volts de frenado DC está establecido demasiado alto, generando corriente excesiva [rok-20b-um001-en, p. 86].

Es importante notar que esta falla no puede ser derrotada ni mitigada una vez ocurrida; el equipo se triplicará instantáneamente si la corriente supera este umbral fijo de hardware [rok-pflex-rm001-en, p. 66].

**Citas válidas:** [rok-pflex-rm001-en, p. 66], [rok-20b-um001-en, p. 86]  
**Citas inválidas:** —  
**Tiempos:** retrieve 0.02 s · LLM 5.4 s · **VRAM (nvidia-smi):** 5375 / 8192 MB

<details><summary>Fragmentos recuperados</summary>

| # | score | cita | sección |
|---|---|---|---|
| 1 | 0.634 | [rok-750-rm002-en, p. 53] | 1 – Drive Configuration |
| 2 | 0.626 | [rok-20b-um001-en, p. 86] | Chapter 2 – Troubleshooting |
| 3 | 0.621 | [rok-pflex-rm001-en, p. 66] | Chapter 2 – Detailed Drive Operation (temas en orden alfabético) |
| 4 | 0.616 | [rok-750-pm001-en, p. 540] |  |
| 5 | 0.611 | [rok-pflex-um-es, p. 190] |  |
| 6 | 0.608 | [rok-pflex-rm001-en, p. 55] | Chapter 2 – Detailed Drive Operation (temas en orden alfabético) |

</details>

**Revisión manual:** _(completar)_

## h1-05 — ¿Qué parámetro define el tiempo de aceleración en el PowerFlex 700?


Seguridad
No se identificaron advertencias específicas (tensión peligrosa, capacitores cargados, bloqueo/etiquetado) en los fragmentos proporcionados para este tema. Sin embargo, al manipular un variador industrial siempre debe considerarse la seguridad eléctrica general y el riesgo de movimiento del motor si está conectado a una carga mecánica.

Qué indica
El tiempo de aceleración define la duración necesaria para que el variador acelere desde 0 hasta la velocidad nominal (frecuencia o RPM) del motor. Según los manuales, este parámetro se programa en función de la frecuencia nominal (**P27 [Motor NP Hertz]**) o la velocidad nominal (**P28 [Motor NP RPM]**).

Causas probables
No hay causas probables para definir qué parámetro controla el tiempo; es una configuración directa del usuario. El valor no se "causa" por fallas, sino que está establecido mediante programación en los registros de parámetros específicos.

Verificaciones
Para verificar la configuración actual:
*   Consulte el registro de parámetros **P535** o **P536**. Según el manual PowerFlex 700 Serie B ([rok-pflex-um-es, p. 210]), estos son los parámetros para **[Accel Time]** (Aceleración). El texto indica que se pueden configurar dos tiempos de aceleración (**[Accel Time 1]**) y **([Accel Time 2])**.
*   Verifique el valor del motor nominal mediante **P43 [Motor NP Hertz]** o **P44 [Motor NP RPM]** ([rok-20b-um001-en, p. 145]). El tiempo de aceleración se define como el tiempo para acelerar desde 0 hasta este valor (frecuencia nominal P27 o velocidad nominal P28) ([rok-750-rm002-en, p. 16], aunque la referencia es al manual Serie A/B).
*   Confirme que **P300 [Speed Units]** esté configurado correctamente para definir si el tiempo se aplica en Hertz o RPM ([rok-pflex-um-es, p. 210]).

Acciones
Para establecer un nuevo tiempo de aceleración:
1.  Acceda a la configuración del variador PowerFlex 700 (Serie B).
2.  Seleccione el parámetro **P535** o **P536**. El manual indica que estos son los registros para **[Accel Time]** ([rok-pflex-um-es, p. 191] menciona la función de aceleración en general y [rok-750-rm002-en, p. 16] detalla P535/P536 como configuración estándar).
    *   Nota: Aunque los fragmentos provienen principalmente del manual Serie A ([rok-20b-um001-en]) y Series B ([rok-pflex-um-es]), la estructura de parámetros para aceleración/deceleración (P5xx) es consistente en las series PowerFlex 700. El texto específico sobre P535/P536 aparece explícitamente en el fragmento del manual Serie A/B generalizado o derivado ([rok-20b-um001-en, p. 145] y [rok-750-rm002-en, p. 16]).
    *   El valor se programa dentro de un rango de **0.00 a 3600.00 segundos** ([rok-pflex-um-es, p. 191], aunque el texto exacto del rango aparece en [rok-750-rm002-en, p. 16] para P535/536).
    *   El tiempo se define como la duración para acelerar desde **0** hasta la frecuencia nominal (**P27**) o velocidad nominal (**P28**) ([rok-pflex-um-es, p. 191]).

**Citas válidas:** [rok-pflex-um-es, p. 210], [rok-20b-um001-en, p. 145], [rok-750-rm002-en, p. 16], [rok-pflex-um-es, p. 191]  
**Citas inválidas:** —  
**Tiempos:** retrieve 0.03 s · LLM 12.1 s · **VRAM (nvidia-smi):** 5375 / 8192 MB

<details><summary>Fragmentos recuperados</summary>

| # | score | cita | sección |
|---|---|---|---|
| 1 | 0.698 | [rok-pflex-um-es, p. 191] |  |
| 2 | 0.676 | [rok-20b-um001-en, p. 145] |  |
| 3 | 0.644 | [rok-pflex-rm001-en, p. 70] | Chapter 2 – Detailed Drive Operation (temas en orden alfabético) |
| 4 | 0.635 | [rok-750-rm002-en, p. 16] | 1 – Drive Configuration |
| 5 | 0.632 | [rok-750-rm002-en, p. 16] | 1 – Drive Configuration |
| 6 | 0.622 | [rok-pflex-um-es, p. 210] |  |

</details>

**Revisión manual:** _(completar)_

## Resumen

| id | citas válidas | citas inválidas | LLM (s) |
|---|---|---|---|
| h1-01 | 2 | 0 | 10.8 |
| h1-02 | 5 | 1 | 16.3 |
| h1-03 | 5 | 3 | 12.8 |
| h1-04 | 2 | 0 | 5.4 |
| h1-05 | 4 | 0 | 12.1 |
