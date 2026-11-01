# Proyecto Final: Agente de IA para devoluciones en EcoMarket

Entrega final de la materia de Inteligencia Artificial Generativa. Autores: Juan Diego Ramírez y Mike Martínez.

Extiende el sistema RAG del Taller 2 con un **agente** que automatiza el proceso de devolución de productos: verifica si el pedido se puede devolver, genera la etiqueta y responde al cliente. Funciona en una aplicación web hecha con Streamlit.

## Contenido

| Fase | Archivo | Qué contiene |
|---|---|---|
| Fase 1: Diseño | [`fase1_diseno/diseno_agente.md`](fase1_diseno/diseno_agente.md) | RAG como herramienta, las 4 herramientas, LangChain y el diagrama de flujo |
| Fase 2: Implementación | [`fase2_agente/README.md`](fase2_agente/README.md) | Código, explicación, manejo de errores y evaluación |
| Fase 2: Evaluación | [`fase2_agente/resultados/evaluacion_agente.md`](fase2_agente/resultados/evaluacion_agente.md) | Respuestas reales del agente en 18 casos |
| Fase 3: Análisis crítico | [`fase3_analisis/analisis_critico.md`](fase3_analisis/analisis_critico.md) | Riesgos de seguridad y ética, monitoreo y mejoras |
| Fase 4: Despliegue | [`fase4_despliegue/README.md`](fase4_despliegue/README.md) | Streamlit, cómo ejecutar y demostración |

## Componentes

| Componente | Elección |
|---|---|
| Marco de agentes | LangChain (`create_agent`) |
| Modelo | DeepSeek Flash (`deepseek-flash`, por API) |
| RAG | ChromaDB + `paraphrase-multilingual-MiniLM-L12-v2` (del Taller 2) |
| Herramientas | `consultar_pedido`, `verificar_elegibilidad_producto`, `generar_etiqueta_devolucion`, `consultar_base_conocimiento` |
| Interfaz | Streamlit |

## Ejecución rápida

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp fase2_agente/.env.example fase2_agente/.env   # escribir la API key de DeepSeek
python fase2_agente/src/indexar.py
streamlit run fase4_despliegue/app.py
```

## Resultados

- **33 pruebas automáticas** de reglas y errores, sin gastar saldo. Todas pasan.
- **17 de 18 casos** de comportamiento pasaron con el modelo real. El caso que falla está explicado en la Fase 2.
- **Costo:** unos 0.02 USD por correr toda la evaluación.
