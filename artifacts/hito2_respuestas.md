# Hito 2 — corridas del agente que decide

Fecha: 20/11/2026 · `qwen3.5:4b` (Ollama, think=false) · BGE-M3 + Qdrant local · CORPUS=demo (6 manuales + 24 casos sintéticos).
Comando: `USE_REAL_LLM=true uv run python -m troubleshooting_agent.agent "<consulta>"`.

Las líneas numeradas son la traza del router: acción elegida, quién decidió (`LLM`, `reglas` o `guarda`) y el motivo.
El historial es **sintético** (`data/catalog/fallas_sinteticas.jsonl`); los casos se citan como `[historial, caso S-NNN]`.

## Observaciones

- **Decisión real del agente:** el LLM elige la acción en cada paso y explica el motivo. Con la versión final siguió el orden de la skill (historial → manual → responder) en q1–q3, y en q2 pidió el modelo antes de buscar. En versiones previas del prompt del router decidió distinto: en q1 fue primero al manual, y en q2 buscó dos veces en el manual sin consultar el historial, que tenía el caso exacto (S-016). Eso motivó agregar "FUENTES SIN CONSULTAR" al prompt.
- **Pedir datos (no es el HITL):** q2 pausa con `interrupt()`, el técnico responde y el grafo retoma desde `identificar_equipo` con el modelo y el código nuevos.
- **Guardas:** q4 (compresor, sin manuales en el corpus demo) el LLM quería pedir el código de falla; la guarda lo cambió por `responder` sin evidencia. Antes de agregar esa guarda pedía datos inútiles.
- **El historial aporta:** en q1, q2 y q3 los casos sintéticos dieron las causas de campo (contrapesos, humedad, parámetros de cañería) que el retrieval de manuales no trajo.
- **Problema principal que queda — retrieval denso:** q1 no recuperó la p. 87 de `rok-20b-um001-en` (fila "OverVoltage 5" de la tabla de fallas) ni q3 la p. 96 de `flexim-fluxus-f532wd-es` (signo de interrogación / LED rojo). → BM25 + RRF en el hito 3.
- **Fidelidad:** hay afirmaciones con cita válida que la página no respalda. En q1, la explicación de F5 OverVoltage cita `[rok-pflex-um-es, p. 188]`, que trata del control vectorial sin encoder; la tabla de fallas real está en la p. 87 de `rok-20b-um001-en` y no se recuperó. En q3, "el signo de interrogación indica..." cita la portada (p. 1). El chequeo actual solo verifica que la página haya sido recuperada → chequeo por afirmación en el hito 3.
- Tiempos: router 1–8 s en total (2–4 llamadas), respuesta 15–23 s.

## q1 — equipo y código completos

```
── Diagnóstico 4ee4ebfcf5ef ──
  · equipo: clase=variador_frecuencia, modelo=PowerFlex 700, fabricante=Rockwell Automation (Allen-Bradley), código=F5
  1. decide buscar_historial [LLM]: Se busca casos previos de fallas F5 OverVoltage en PowerFlex 700 para identificar causas comunes antes de consultar el manual específico.  «El PowerFlex 700 del pozo para por F5 OverVoltage cuando baja el balancín»
     → 4 resultados · mejor score 0.77 · 4 del modelo PowerFlex 700 · filtros clase_equipo=variador_frecuencia
  2. decide buscar_manual [LLM]: Se identificó el equipo (PowerFlex 700) y se encontró evidencia en el historial, pero aún no hay la descripción técnica oficial de la falla F5 OverVoltage ni las acciones recomendadas específicas para este modelo.  «F5 OverVoltage PowerFlex 700 variador frecuencia»
     → 6 resultados · mejor score 0.65 · 6 del modelo PowerFlex 700 · filtros clase_equipo=variador_frecuencia, modelos=PowerFlex 700
  3. decide responder [LLM]: Ya se han consultado el historial de fallas y los manuales del fabricante para la falla F5 OverVoltage en PowerFlex 700, obteniendo suficiente evidencia técnica; ahora es necesario ordenar las acciones correctivas basándose en esos hallazgos.

# Seguridad
Antes de realizar cualquier intervención en el variador o su entorno, se debe aplicar bloqueo y etiquetado (LOTO) y verificar la ausencia de tensión. Si existe riesgo de movimiento del AIB debido a contrapesos desbalanceados, asegurar que no pueda arrancar ni moverse por inercia antes de intervenir [guía interna].

# Qué indica
El código **F5 OverVoltage** en el variador PowerFlex 700 indica una tensión superior al valor máximo permitido en la entrada del convertidor. Según los manuales disponibles, este estado se activa cuando la energía regenerada por el motor excede la capacidad de absorción interna o externa [rok-pflex-um-es, p. 188].

# Causas probables
Basado en casos resueltos similares y principios generales:
*   **Regeneración del motor:** El variador puede no tener suficiente capacidad para absorber la energía regenerada cuando el motor actúa como generador durante la bajada del balancín, especialmente si hay contrapesos desbalanceados [historial, caso S-001].
*   **Tiempo de desaceleración insuficiente:** Un tiempo muy corto puede generar picos de tensión que superen los límites aceptables debido a la inercia del sistema [historial, caso S-002].
*   **Configuración incorrecta de contrapesos:** La posición incorrecta o desbalanceado de los contrapesos genera regeneración no controlada en la carrera descendente [historial, case S-014].

# Casos similares del historial
Se han documentado casos sintéticos con síntomas y causas relevantes:
*   **Caso S-002:** Síntoma F5 OverVoltage al detener el pozo. Causa identificada como tiempo de desaceleración muy corto para la inercia del AIB [historial, caso S-002]. Solución aplicada fue aumentar el tiempo de desaceleración.
*   **Caso S-001:** Síntoma F5 OverVoltage en la carrera descendente varias veces por día. Causa: regeneración del motor debido a contrapesos desbalanceados y falta de resistencia de frenado [historial, caso S-001]. Solución incluyó rebalancear el AIB y extender el tiempo de desaceleración.
*   **Caso S-014:** Síntoma F5 OverVoltage tras cambio de contrapesos. Causa: posición incorrecta generando regeneración [historial, caso S-014]. Solución fue corregir la posición según planilla de balanceo.

# Verificaciones
*   **Verificar tensión de entrada y estabilidad:** Asegurar que no haya caídas de tensión en la línea (corte distribuidora) que puedan influir en el comportamiento del variador, aunque esto suele manifestarse como F4 UnderVoltage [historial, caso S-003]. Sin embargo, verificar la normalización es parte del diagnóstico general tras eventos externos.
*   **Revisar configuración de desaceleración:** Medir o revisar los parámetros configurados para el tiempo de desaceleración (Decel Time) y compararlos con las especificaciones requeridas por la inercia actual [rok-pflex-um-es, p. 188].
*   **Inspección física del AIB:** Verificar visualmente si hay contrapesos montados en posición incorrecta o desbalanceado aparente [historial, caso S-014].

# Acciones
Según la evidencia disponible y los casos resueltos:
1.  **Aumentar el tiempo de desaceleración:** Extender el parámetro de Decel Time para permitir una transición más suave que reduzca la regeneración excesiva [historial, caso S-002].
2.  **Rebalancear los contrapesos:** Si se sospecha desequilibrio en el AIB, realizar un balanceo adecuado antes o durante las pruebas de bajada del balancín [historial, caso S-001; historial, caso S-014].
3.  **Evaluar resistencia de frenado dinámico:** Si la regeneración persiste a pesar de ajustar el tiempo de desaceleración y los contrapesos están equilibrados, considerar la instalación o configuración de una resistencia externa para absorber energía [historial, caso S-001].

# Escalar
Se recomienda escalar al supervisor o especialista si:
*   La falla se repite después de ajustar el tiempo de desaceleración y verificar/rebalancear los contrapesos.
*   Se requiere intervención con el equipo energizado para realizar ajustes en la configuración del variador (si no está programado) o inspección interna [guía interna].
*   El diagnóstico sugiere que es necesario instalar una resistencia externa de frenado, lo cual implica reemplazo de componentes potenciales.

Fuentes:
  - [rok-pflex-um-es, p. 188] PowerFlex 700 – Variador de Frecuencia Ajustable de CA, Serie B, Manual del Usuario (FW 4.001)
  - [historial, caso S-001] Historial de fallas sintético (demo) · SIM-101 (AIB) · 2025-03-04 · caso sintético
  - [historial, caso S-002] Historial de fallas sintético (demo) · SIM-114 (AIB) · 2025-04-11 · caso sintético
  - [historial, caso S-014] Historial de fallas sintético (demo) · SIM-175 (AIB) · 2025-11-10 · caso sintético
  - [historial, caso S-003] Historial de fallas sintético (demo) · SIM-120 (AIB) · 2025-05-02 · caso sintético

(router 4.2 s · retrieve 0.36 s · LLM 14.9 s)
```

## q2 — falta el modelo: pide datos, pausa y reanuda

Respuesta del técnico (por stdin): `Es un PowerFlex 755, muestra falla 13 Ground Fault`.

```
── Diagnóstico bb29ffed4fb0 ──
  · equipo: clase=variador_frecuencia, modelo=¿?, fabricante=¿?, código=-
  1. decide pedir_datos [LLM]: Falta el modelo exacto del variador de frecuencia para poder buscar en los manuales específicos o casos históricos, ya que las causas y códigos varían entre modelos.  «Para seguir necesito: el modelo exacto del equipo.»

❓ Para seguir necesito: el modelo exacto del equipo.
»   · técnico: Es un PowerFlex 755, muestra falla 13 Ground Fault
  · equipo: clase=variador_frecuencia, modelo=PowerFlex 755, fabricante=Rockwell Automation (Allen-Bradley), código=F13
  2. decide buscar_historial [LLM]: Se busca casos previos de fallas tipo F13 (Ground Fault) en variadores PowerFlex 755 para identificar causas comunes antes de consultar el manual.  «PowerFlex 755 falla Ground Fault F13»
     → 4 resultados · mejor score 0.73 · 2 del modelo PowerFlex 755 · filtros clase_equipo=variador_frecuencia
  3. decide buscar_manual [LLM]: Se ha consultado el historial de fallas y se encontraron casos similares, pero falta la descripción técnica oficial del fabricante para confirmar las causas raíz específicas y obtener los pasos de reparación recomendados; además, es necesario verificar si este código F13 tiene variaciones entre modelos dentro de la clase 'variador_frecuencia' antes de proceder a acciones correctivas.  «el variador de la bomba de inyección se dispara cuando llueve Es un PowerFlex 755, muestra falla 13 Ground Fault F13»
     → 6 resultados · mejor score 0.58 · 6 del modelo PowerFlex 755 · filtros clase_equipo=variador_frecuencia, modelos=PowerFlex 755
  4. decide responder [LLM]: Ya se identificó el equipo (PowerFlex 755), la falla específica (F13 Ground Fault) y existen resultados relevantes tanto en el historial de fallas resueltas como en los manuales del fabricante, por lo que hay suficiente evidencia para proceder con las acciones correctivas sin necesidad de más búsquedas o datos.

# Seguridad
Antes de realizar cualquier intervención en el tablero o tocar bornes, es obligatorio aplicar bloqueo y etiquetado (LOTO) y verificar la ausencia de tensión. Si se requiere abrir componentes internos del variador, recordar que el bus DC queda cargado tras cortar la alimentación; esperar el tiempo de descarga indicado por el fabricante antes de intervenir. Para equipos con presión o gas asociados a esta bomba, despresurizar e aislar antes de cualquier trabajo interno. AIB / equipos rotantes: asegurar que no puedan arrancar ni moverse por inercia o contrapesos durante las pruebas eléctricas.

# Qué indica
La falla **F13 Ground Fault** (Código 10xxx) en el variador PowerFlex 755 indica una condición de tierra detectada, específicamente cuando la corriente de tierra excede el nivel configurado en el parámetro P467 [Ground Warn Lvl] y supera el umbral para activar un fallo mayor. Según los manuales disponibles:
*   "This fault will be asserted if an attempt to flash the FPGA configuration device fails" (para códigos 10xxx relacionados con fallas de configuración, aunque en este caso específico se refiere a tierra). [rok-750-pm001-en, p. 339]
*   Para el parámetro P466 [Ground Fault]: "The Ground Warning feature detects a ground current that exceeds the level set in P467". [rok-750-pm001-en, p. 105]

# Causas probables
Basado en la evidencia disponible y los casos del historial similares para PowerFlex 755/700:
*   **Falla de aislación interna o externa:** El caso S-016 muestra que un "Motor con humedad en el bobinado" puede causar una falla F13 Ground Fault. [historial, caso S-016]
*   **Problemas de cableado y entrada de agua:** El caso S-007 describe fallas intermitentes de tierra ("días de lluvia") causadas por "Cable de salida al motor con aislación dañada... ingresaba agua". [historial, caso S-007]
*   **Falla en el variador o interfaz:** El manual indica que si la falla persiste tras verificar cargas externas, se debe revisar la fuente de alimentación del tablero ("inverter power supply board") o las placas de control. [rok-750-pm001-en, p. 339]
*   **Configuración incorrecta:** Si el variador detecta una fuente de alimentación incompatible (código Ixxx Incompat PS), esto podría interferir con la operación normal y generar alarmas secundarias al intentar reconfigurar o reiniciar. [rok-750-pm001-en, p. 339]

# Casos similares del historial
*   **Caso S-016 (PowerFlex 755):** Síntoma de F13 Ground Fault en bomba de inyección; causa identificada como humedad/bobinado a tierra en el motor. [historial, caso S-016]
*   **Caso S-024 (PowerFlex 700):** Falla F13 que no se resetea y reaparece inmediatamente debido al bobinado del AIB a tierra; requirió reemplazo de motor o rebobinado. [historial, caso S-024]
*   **Caso S-007 (PowerFlex 700):** Falla F13 intermitente en días lluviosos debido al ingreso de agua por cable dañado; solución fue secado y sellado del tramo afectado. [historial, caso S-007]
*   **Caso S-015 (PowerFlex 755):** Falla inicial F12 HW OverCurrent durante aceleración que llevó a verificar fallas de aislación del motor antes de ajustar parámetros de tiempo de aceleración. [historial, caso S-015]

# Verificaciones
Para diagnosticar la causa raíz sin inventar datos:
*   **Medición de aislamiento:** Realizar medición con megóhmetro en el bobinado del motor (con energía desconectada) para verificar si hay fuga a tierra o humedad. [basado en caso S-016 y S-024]
*   **Inspección visual e ingreso ambiental:** Verificar cables de salida al motor, cajas de conexiones y tramos expuestos que puedan estar dañados por agua (especialmente relevante si la falla es intermitente o ocurre con lluvia). [basado en caso S-007]
*   **Verificación de fuente de alimentación interna:** Si el cableado externo está limpio, medir voltajes internos del tablero para descartar fallas en la placa "inverter power supply board" que alimenta las placas PLI y drivers. [rok-750-pm001-en, p. 339]
*   **Verificación de parámetros:** Confirmar el valor actual de P467 [Ground Warn Lvl] para asegurar que la configuración no esté demasiado baja comparada con las condiciones reales del sistema. [rok-750-pm001-en, p. 105]

# Acciones
Las acciones deben realizarse siguiendo los procedimientos técnicos descritos en el manual y priorizando la seguridad:
*   **Si se detecta humedad o falla de aislación:** Secar el bobinado con calefactor (como se hizo en caso S-016) antes de volver a ponerlo en servicio. [historial, caso S-016]
*   **Si hay daño por agua/cable dañado:** Medir la resistencia de aislamiento del cable/motor desconectado; reemplazar el tramo de cable y sellar las cajas de conexiones afectadas (como se hizo en caso S-007). [historial, caso S-007]
*   **Si falla una fase específica:** Reemplazar la placa correspondiente del driver gate (ej. U-Brd, V-Brd, W-Brd) según el código específico de falla Ixxx UBrd/VBrd/WBrd Fault. [rok-750-pm001-en, p. 339]
*   **Si la fuente interna es sospechosa:** Desconectar cargas individuales para buscar cortocircuitos en las placas PLI o backplane; si no hay corto visible, reemplazar el tablero de alimentación del variador ("inverter power supply board"). [rok-750-pm001-en, p. 339]
*   **Si persiste tras reset:** Si la falla se repite inmediatamente después de corregir una causa evidente (como secar un motor), proceder al reemplazo del equipo o escalar según corresponda. [guía interna - Escalamiento]

# Escalar
Se recomienda escalar a supervisor o especialista si:
*   La falla se repite tras intentar resetear y corregir la causa aparente (ej. secado de motor).
*   El manual indica reemplazo del variador completo, placas internas específicas ("inverter power supply board") o equipos de potencia que requieren herramientas especializadas para su extracción segura.
*   Se requiere intervenir con el equipo energizado o presurizado para confirmar la causa raíz sin riesgo.
*   Hay riesgo potencial para personas, ambiente (agua en sistema eléctrico) o integridad del pozo si se trata de un AIB crítico. [guía interna - Escalamiento]

Fuentes:
  - [rok-750-pm001-en, p. 339] Programming Manual, PowerFlex 750-Series AC Drives · 6 – Troubleshooting (fallas y alarmas)
  - [rok-750-pm001-en, p. 105] Programming Manual, PowerFlex 750-Series AC Drives · 2–5 – Parámetros (Port 0, 10/11, opciones)
  - [historial, caso S-016] Historial de fallas sintético (demo) · Planta SIM-PIA (bomba inyección) · 2025-06-15 · caso sintético
  - [historial, caso S-007] Historial de fallas sintético (demo) · SIM-150 (AIB) · 2025-07-08 · caso sintético
  - [historial, caso S-024] Historial de fallas sintético (demo) · SIM-114 (AIB) · 2025-11-18 · caso sintético
  - [historial, caso S-015] Historial de fallas sintético (demo) · Planta SIM-PIA (bomba inyección) · 2025-04-02 · caso sintético

(router 6.0 s · retrieve 0.35 s · LLM 22.1 s)
```

## q3 — caudalímetro (sin códigos de falla)

```
── Diagnóstico c6f3349e80ca ──
  · equipo: clase=caudalimetro, modelo=FLUXUS F532WD, fabricante=FLEXIM, código=-
  1. decide buscar_historial [LLM]: Se busca casos de fallas resueltas similares en campo para el caudalímetro FLUXUS F532WD con signo de pregunta y LED rojo antes de consultar manuales específicos.  «el caudalímetro FLUXUS de la batería muestra un signo de pregunta y el led en rojo FLUXUS F532WD»
     → 4 resultados · mejor score 0.80 · 4 del modelo FLUXUS F532WD · filtros clase_equipo=caudalimetro
  2. decide buscar_manual [LLM]: Se identificó el equipo exacto (FLUXUS F532WD) y se realizó una búsqueda en historial con resultados relevantes; ahora es necesario consultar los manuales del fabricante para obtener la descripción técnica de las causas raíz y acciones recomendadas específicas para este modelo.  «caudalímetro FLUXUS F532WD LED rojo signo pregunta»
     → 6 resultados · mejor score 0.71 · 6 del modelo FLUXUS F532WD · filtros clase_equipo=caudalimetro, modelos=FLUXUS F532WD
  3. decide responder [LLM]: Ya se consultaron el historial de fallas y los manuales del modelo específico sin encontrar una causa clara ni acciones recomendadas para este síntoma, por lo que no hay más fuentes útiles disponibles.

# Seguridad
Antes de intervenir cualquier parte del instrumento o su entorno, se debe realizar bloqueo y etiquetado (LOTO) y verificar ausencia de tensión. Si hay presión residual en la tubería donde están instalados los transductores, es necesario despresurizar e aislar antes de abrir el equipo. Para equipos con gas, asegurar que no existan fugas ni riesgo de explosión durante las operaciones.
*(guía interna)*

# Qué indica
El símbolo de interrogación junto al caudal y la luz LED roja indican una condición de error o falta de señal válida en el instrumento FLUXUS F532WD [flexim-fluxus-f532wd-es, p. 1]. Según los manuales disponibles para este modelo específico (FLEXIM FLUXUS F532WD), no se detalla explícitamente qué valor numérico exacto representa la "interrogación" ni el código de error correspondiente a esta condición en las páginas consultadas [flexim-fluxus-f532wd-es, p. 1], aunque se menciona que el instrumento muestra información importante sobre su estado y cómo evitar daños al manejarlo correctamente [flexim-fluxus-f532wd-es, p. 7].

# Causas probables
Basado en los casos resueltos del historial para este tipo de equipo (FLUXUS F532WD), una causa probable es que se haya cargado incorrectamente el perímetro de la cañería al reconfigurar el punto de medición, lo cual impide un cálculo correcto [historial, caso S-018]. Otra posibilidad común en estos equipos ultrasónicos es el mal acoplamiento acústico debido a pintura o suciedad debajo de los transductores que bloquea la señal [historial, caso S-019]. También podría deberse a problemas con las baterías (SIM-B3 o SIM-B5) si hay pérdida de datos o errores relacionados con el tiempo y fecha [historial, caso S-021], aunque esto suele manifestarse más en borrado de fechas que en la interrogación del caudal.

# Casos similares del historial
*   **Caso S-018:** Síntoma idéntico (signo de interrogación y LED rojo). Causa: Configuración incorrecta del diámetro externo/perímetro al reconfigurar el punto de medición [historial, caso S-018]. Solución aplicada: Corregir parámetros de cañería (diámetro exterior, espesor) y reposicionar transductores con distancia calculada.
*   **Caso S-024:** Síntoma similar a la pérdida de señal tras intervención en la tubería (pintura). Causa: Mal acoplamiento por suciedad o pintura [historial, caso S-019]. Solución aplicada: Limpiar superficie y reaplicar acoplante.

# Verificaciones
Para diagnosticar el problema, se recomienda verificar los siguientes parámetros según la estructura del menú disponible en el manual [flexim-fluxus-f532wd-es, p. 151]:
*   **Diámetro externo:** Confirmar si coincide con las dimensiones reales de la tubería instalada.
*   **Espesor de pared y Material de la tubería:** Verificar que estos datos estén correctos en el menú "Transductor" > "Entrada de parámetros".
*   **Distancia entre transd.:** Medir físicamente si coincide con los valores configurados o calculados por el software.
*   **Prueba de señal:** Utilizar la función "Probar señal" disponible en el menú principal para verificar si hay retorno acústico [flexim-fluxus-f532wd-es, p. 154].

# Acciones
Si se confirma que los parámetros geométricos (diámetro exterior) son incorrectos:
1.  Corregir los valores de **Diámetro externo** y **Espesor de pared** en el menú correspondiente [flexim-fluxus-f532wd-es, p. 152].
2.  Recalcular la distancia óptima entre transductores si es necesario.

Si se confirma que hay suciedad o pintura bajo los transductores:
1.  Limpiar cuidadosamente la superficie de la cañería debajo del área de instalación de los transductores [historial, caso S-019].
2.   Reaplicar el acoplante adecuado y reinstalar los transductores asegurando un buen contacto acústico.

Si se sospecha que es una configuración previa incorrecta (como en el Caso S-018):
*   Reposicionar físicamente los transductores si la distancia configurada no coincide con la realidad, o ajustar el parámetro de "Distancia entre transd." para coincidir con la instalación actual.

# Escalar
Se recomienda escalar al supervisor o especialista cuando:
*   La falla persiste después de corregir los parámetros geométricos y limpiar las superficies sin que desaparezca la interrogación [historial, caso S-018].
*   Se requiere reemplazar placas internas o componentes electrónicos del instrumento.
*   Hay riesgo para personas o integridad del pozo al intentar acceder a la tubería presurizada.

Fuentes:
  - [flexim-fluxus-f532wd-es, p. 1] FLEXIM FLUXUS F532WD – Caudalímetro ultrasónico (manual de usuario)
  - [flexim-fluxus-f532wd-es, p. 7] FLEXIM FLUXUS F532WD – Caudalímetro ultrasónico (manual de usuario)
  - [historial, caso S-018] Historial de fallas sintético (demo) · Batería SIM-B3 (medición de agua) · 2025-03-20 · caso sintético
  - [historial, caso S-019] Historial de fallas sintético (demo) · Batería SIM-B3 (medición de agua) · 2025-05-27 · caso sintético
  - [historial, caso S-021] Historial de fallas sintético (demo) · Batería SIM-B5 (medición de agua) · 2025-09-09 · caso sintético
  - [flexim-fluxus-f532wd-es, p. 151] FLEXIM FLUXUS F532WD – Caudalímetro ultrasónico (manual de usuario) · 18 / Anexo A – Ajustes y estructura de menú
  - [flexim-fluxus-f532wd-es, p. 154] FLEXIM FLUXUS F532WD – Caudalímetro ultrasónico (manual de usuario) · 18 / Anexo A – Ajustes y estructura de menú
  - [flexim-fluxus-f532wd-es, p. 152] FLEXIM FLUXUS F532WD – Caudalímetro ultrasónico (manual de usuario) · 18 / Anexo A – Ajustes y estructura de menú

(router 4.2 s · retrieve 0.30 s · LLM 15.4 s)
```

## q4 — clase sin documentación en el corpus demo

```
── Diagnóstico 91f443483191 ──
  · equipo: clase=compresor_reciprocante, modelo=¿?, fabricante=¿?, código=-
  1. decide responder [guarda]: No hay documentación indexada para la clase compresor_reciprocante.
     ⚑ pedir_datos descartada: clase sin documentación

No encontré evidencia en el corpus indexado para responder esta consulta, así que no puedo indicar causas ni procedimientos. No hay manuales indexados para la clase de equipo 'compresor_reciprocante'.

(router 1.1 s · retrieve 0.00 s · LLM 0.0 s)
```
