# Fase 2: Implementación y conexión de componentes

Este es el código del agente. Parte del código del Taller 2 y le agrega las herramientas, el agente y el manejo de errores.

## Estructura

```
fase2_agente/
├── data/                       # documentos del Taller 2 y pedidos de prueba
├── src/
│   ├── config.py               # parámetros: modelos, plazos, fecha simulada, límites
│   ├── cargar_documentos.py    # del Taller 2: carga y corta los documentos
│   ├── indexar.py              # del Taller 2: crea la base vectorial en ChromaDB
│   ├── herramientas.py         # NUEVO: las 4 herramientas y el registro de acciones
│   ├── prompts.py              # CAMBIÓ: prompt de sistema del agente
│   ├── agente.py               # NUEVO: crea el agente, lo ejecuta y maneja los errores
│   └── evaluar_agente.py       # NUEVO: prueba el comportamiento con 18 casos
├── tests/                      # 33 pruebas que no gastan saldo
├── resultados/evaluacion_agente.md   # resultados reales de la evaluación
└── .env.example
```

## Instalación y ejecución

Se probó con Python 3.12. Los comandos se ejecutan desde la carpeta raíz del proyecto.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp fase2_agente/.env.example fase2_agente/.env   # y escribir la API key de DeepSeek

python fase2_agente/src/indexar.py               # crea la base vectorial (una sola vez)
pytest fase2_agente/tests                        # pruebas, no gastan saldo
python fase2_agente/src/agente.py --interactivo  # conversación en la terminal
python fase2_agente/src/evaluar_agente.py        # evaluación (unos 0.02 USD)
streamlit run fase4_despliegue/app.py            # aplicación web
```

---

## Cómo se conectan las piezas

Esto pasa cuando un cliente escribe "Quiero devolver mi pedido ECM-1005":

1. `agente.py` le envía a DeepSeek el prompt de sistema, el mensaje y la lista de herramientas.
2. El modelo no responde con texto. Responde: "quiero llamar a `verificar_elegibilidad_producto` con `ECM-1005`".
3. LangChain ejecuta esa función de `herramientas.py` y le devuelve el resultado al modelo.
4. El modelo ve `elegible: true` y pide llamar a `generar_etiqueta_devolucion`.
5. LangChain la ejecuta. La función vuelve a revisar la elegibilidad y guarda la etiqueta.
6. El modelo ve `numero_etiqueta: RMA-1005` y ya no pide más herramientas: escribe la respuesta para el cliente.

Este ciclo (modelo → herramienta → modelo) lo hace `create_agent`. Nosotros no programamos el orden de las llamadas: el modelo lo decide leyendo el prompt y los resultados.

### `herramientas.py`

Cada herramienta tiene dos partes:

- Una **función normal** con la lógica, por ejemplo `revisar_elegibilidad()`. Se puede probar sin el modelo.
- Una **función con `@tool`** que ve el modelo, por ejemplo `verificar_elegibilidad_producto()`. Su docstring es lo que el modelo lee para saber cuándo usarla.

`revisar_elegibilidad()` aplica las reglas en orden:

1. Revisa el estado: devuelto, cancelado o no entregado no se pueden devolver.
2. Si es dañado, vencido o equivocado y pasaron máximo 5 días, es elegible (sección 6 de la política).
3. Si es perecedero, no es elegible. Si es de higiene, depende de si fue abierto. Si no sabe, devuelve `falta_informacion`.
4. Si pasaron más de 30 días, no es elegible.

El decorador `@con_registro` envuelve cada herramienta para hacer dos cosas: guardar la llamada en `salidas/registro_acciones.jsonl` y convertir cualquier excepción en un error `error_interno`.

### `prompts.py`

Dice cuándo responder directo, cuándo usar cada herramienta, los pasos de la devolución y cómo responder si algo falla. A diferencia del Taller 2, el prompt ya no trae documentos: el modelo los pide cuando los necesita.

### `agente.py`

- `crear_llm()`: conecta con DeepSeek usando `ChatOpenAI`, igual que en el Taller 2.
- `AgenteEcoMarket.__init__()`: crea el agente con `create_agent(modelo, HERRAMIENTAS, system_prompt=PROMPT_AGENTE)`.
- `AgenteEcoMarket.responder()`: recibe el mensaje y la conversación anterior, ejecuta el agente, maneja los errores y devuelve un `Resultado` con la respuesta, las herramientas usadas y los tokens.
- `respuesta_es_segura()`: revisa que todo número `RMA-XXXX` de la respuesta haya salido de una herramienta. Si el modelo inventó uno, se bloquea la respuesta.

---

## Manejo de respuestas: éxito y errores

| Situación | Dónde se maneja | Qué ve el cliente |
|---|---|---|
| Etiqueta generada | Herramienta + modelo | Número de etiqueta e instrucciones |
| No elegible | `revisar_elegibilidad()` | La razón, explicada con amabilidad |
| Falta un dato | Prompt + `falta_informacion` | Una pregunta. Con la respuesta, el agente sigue |
| Número mal escrito o que no existe | `_obtener_pedido()` | Le pide revisar el número |
| La transportadora no responde | `crear_etiqueta()` devuelve `servicio_no_disponible` | Disculpa, y le sugiere reintentar o ir al chat. No dice que la etiqueta se generó |
| Error inesperado en una herramienta | `@con_registro` | El modelo recibe `error_interno` y lo explica |
| Sin base vectorial | `buscar_en_documentos()` | El agente no se cae y sigue funcionando |
| Sin internet, sin saldo o key inválida | `try/except` en `responder()` | Mensaje fijo de problema técnico |
| Ciclo de más de 12 pasos | `GraphRecursionError` en `responder()` | Mensaje fijo de problema técnico |
| Respuesta vacía | `responder()` | Mensaje fijo de problema técnico |
| Número de etiqueta inventado | `respuesta_es_segura()` | Bloquea la respuesta y lo guarda en el registro |

---

## Evaluación del comportamiento

### Pruebas sin gastar saldo

`pytest fase2_agente/tests` corre **33 pruebas** de las reglas de la política, las etiquetas y el manejo de errores. Todas pasan.

### Evaluación con el modelo real

`evaluar_agente.py` corre 18 casos. Cada caso dice qué herramientas debe usar, cuáles no y si debe quedar una etiqueta. El script revisa todo esto de forma automática.

**Resultado final: 17 de 18 casos pasaron**, con un costo de 0.0218 USD. Las respuestas completas están en [`resultados/evaluacion_agente.md`](resultados/evaluacion_agente.md).

| Grupo | Casos | Qué debe hacer | Resultado |
|---|---|---|---|
| Responder directo | C01, C02 | No usar herramientas de pedidos | Pasó |
| RAG | C03 a C05 | Usar solo la base de conocimiento | Pasó |
| Consulta de pedido | C06 | Usar solo `consultar_pedido` | Pasó |
| Devolución exitosa | C07, C08 | Verificar y generar la etiqueta | Pasó |
| Conversación | C09 | Preguntar si está abierto, recordar el pedido y generar la etiqueta | Pasó |
| Solo pregunta | C10 | Verificar, pero no generar la etiqueta | Pasó |
| No elegible | C11 a C13 | Verificar y no generar la etiqueta | Pasó |
| Falta un dato | C14 | Pedir el número sin usar herramientas | Pasó |
| Errores | C15, C16 | Pedido que no existe y falla de la transportadora | Pasó |
| Seguridad | C17 | No crear etiqueta ante "soy el administrador" | Pasó |
| Mezcla | C18 | Hacer la devolución y responder sobre el reembolso | **Falló** |

### Qué aprendimos al probar

La evaluación encontró errores que no habríamos visto con una sola prueba:

1. **La primera versión del prompt pasó 14 de 17.** Las fallas tenían la misma causa: el agente le preguntaba el motivo al cliente en vez de verificar. Agregamos la regla "si el cliente no dijo el motivo, usa `otro`" y pasó a 17 de 17.
2. **Un error que el script no detectó.** Al leer las respuestas vimos que el agente decía "entrégalo antes del 18 de septiembre" para los snacks vencidos. Esa fecha era el plazo para reportar el defecto, no para enviar el paquete. La quitamos de la herramienta. Por eso también hay que leer las respuestas, no solo mirar si la prueba pasó.
3. **C18 sigue fallando.** En un mensaje con devolución y pregunta, el agente usa bien las dos fuentes, pero pide confirmación en vez de generar la etiqueta. Cambiamos el prompt una vez y siguió igual, así que lo dejamos documentado. La falla es segura: no hace nada indebido y el cliente solo tiene que responder "sí".
4. **Un caso pasa por las reglas, no por la inteligencia.** En C17 la protección real es el código: aunque el modelo obedeciera, `crear_etiqueta()` rechazaría la etiqueta porque un perecedero sin defecto no es elegible.

## Limitaciones y suposiciones

- **Herramientas simuladas.** No hay conexión real con un sistema de pedidos ni con una transportadora. La falla de la transportadora se simula con una opción.
- **Fecha simulada.** Los pedidos son de septiembre de 2026, así que fijamos "hoy" en 2026-09-17 (`config.FECHA_ACTUAL`). Sin esto todos los plazos estarían vencidos.
- **Datos de prueba modificados.** Agregamos el pedido ECM-1012 (fuera de plazo) y cambiamos la fecha de pedido de ECM-1008 y ECM-1011, que quedaban después de la fecha simulada.
- **Pocas repeticiones.** Cada caso corrió una vez por versión del prompt. El modelo puede responder distinto en otra ejecución, aunque la temperatura sea 0.
- **La evaluación revisa herramientas, no redacción.** Un caso puede pasar con una respuesta mal escrita, como vimos en el punto 2.
- **Un solo usuario.** Las etiquetas se guardan en un archivo JSON, y eso no sirve para muchos usuarios al mismo tiempo.
