# Skill: troubleshooting de equipos industriales

Guía que el agente sigue para diagnosticar una falla. Cada sección `##` se carga en
el prompt que la necesita (router o respuesta). Mantenerla corta: el modelo por
defecto trabaja con 8k de contexto.

## Procedimiento

1. Identificar el equipo: clase, fabricante, modelo exacto y código o nombre de falla.
   Si no se sabe qué equipo es, pedirlo antes de buscar. Si falta el modelo exacto y hay
   manuales de varios modelos de esa clase, pedirlo (los códigos cambian entre modelos).
2. Buscar casos similares en el historial de fallas resueltas: muestran causas reales
   frecuentes en campo, pero no reemplazan al manual.
3. Buscar en el manual del fabricante la descripción de la falla, sus causas y las
   acciones recomendadas. Si hay un código de falla, incluirlo en la consulta.
4. Si la evidencia es de otro modelo o no menciona la falla, reformular la búsqueda
   una vez o pedir el dato que falta. No repetir la misma búsqueda.
5. Responder cuando haya evidencia suficiente, o cuando ya no haya más fuentes útiles
   (decir qué faltó). Ordenar las verificaciones de la menos a la más invasiva.

## Seguridad

- Antes de abrir tableros o tocar bornes: bloqueo y etiquetado (LOTO) y verificación
  de ausencia de tensión.
- Variadores: el bus DC queda cargado después de cortar la alimentación; esperar el
  tiempo de descarga que indique el manual y medir antes de intervenir.
- Equipos con presión o gas: despresurizar y aislar antes de desarmar.
- AIB / equipos rotantes: asegurar que no puedan arrancar ni moverse por inercia o
  contrapesos.
- Citar las advertencias que aparecen en los fragmentos. Si no hay advertencias en la
  evidencia, recordar LOTO de forma genérica sin inventar valores.

## Escalamiento

Recomendar escalar al supervisor o al especialista cuando:
- la falla se repite después de resetear y corregir la causa evidente;
- el manual indica reemplazar placas, el variador completo o equipos de potencia;
- hace falta intervenir con el equipo energizado o presurizado;
- hay riesgo para personas, ambiente o integridad del pozo (presión, gas, BOP);
- la evidencia disponible no alcanza para un diagnóstico confiable.
