"""Agente de EcoMarket: une el modelo (DeepSeek Flash), las herramientas y el manejo de errores.

Cómo funciona el ciclo del agente en cada mensaje:
1. El modelo recibe el prompt de sistema, la conversación y la lista de herramientas.
2. El modelo responde con texto o pide usar una herramienta.
3. Si pide una herramienta, LangChain la ejecuta y le devuelve el resultado al modelo.
4. Se repite el paso 2 hasta que el modelo responde con texto. Esa es la respuesta para el cliente.

Ejemplos:
    python agente.py --mensaje "Quiero devolver mi pedido ECM-1005, no me sirvió"
    python agente.py --interactivo
"""
import argparse
import json
import re
from dataclasses import dataclass, field

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError

import config
from herramientas import HERRAMIENTAS, registrar
from prompts import PROMPT_AGENTE

PATRON_ETIQUETA = re.compile(r"RMA-\d{4}")

# Precios de deepseek-flash en USD por millón de tokens (hora pico, el caso más caro).
# Fuente: https://api-docs.deepseek.com/quick_start/pricing (consultado el 2026-10-16)
PRECIO_ENTRADA_USD = 0.30
PRECIO_SALIDA_USD = 1.20

MENSAJE_ERROR_MODELO = (
    "Lo siento, tuve un problema técnico y no pude completar tu solicitud. "
    "Intenta de nuevo en unos minutos o escribe al chat de la tienda."
)
MENSAJE_RESPUESTA_BLOQUEADA = (
    "Lo siento, no pude confirmar que tu etiqueta se haya generado. "
    "Intenta de nuevo o escribe al chat de la tienda para que un agente te ayude."
)


@dataclass
class Paso:
    """Una llamada a una herramienta durante la respuesta."""

    herramienta: str
    entrada: dict
    resultado: dict


@dataclass
class Resultado:
    respuesta: str
    pasos: list[Paso] = field(default_factory=list)
    tokens_entrada: int = 0
    tokens_salida: int = 0
    hubo_error: bool = False

    @property
    def costo_usd(self) -> float:
        return (self.tokens_entrada * PRECIO_ENTRADA_USD + self.tokens_salida * PRECIO_SALIDA_USD) / 1_000_000

    @property
    def etiqueta(self) -> dict | None:
        """La etiqueta creada en esta respuesta, si hubo una."""
        for paso in self.pasos:
            if paso.herramienta == "generar_etiqueta_devolucion" and paso.resultado.get("ok"):
                return paso.resultado
        return None


def crear_llm() -> ChatOpenAI:
    if not config.DEEPSEEK_API_KEY:
        raise SystemExit("Falta DEEPSEEK_API_KEY. Copia .env.example a .env y pon tu API key.")
    return ChatOpenAI(
        model=config.MODELO_LLM,
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        temperature=config.TEMPERATURA,
        max_tokens=config.MAX_TOKENS_RESPUESTA,
        timeout=60,
        max_retries=2,
        extra_body={"thinking": {"type": "disabled"}},  # igual que en el Taller 2, para gastar menos
    )


def leer_resultado(mensaje: ToolMessage) -> dict:
    try:
        return json.loads(mensaje.content)
    except (TypeError, json.JSONDecodeError):
        return {"ok": False, "codigo": "respuesta_invalida", "mensaje": str(mensaje.content)}


def extraer_pasos(mensajes: list) -> list[Paso]:
    """Une cada pedido de herramienta del modelo con el resultado que recibió."""
    pedidos = {}
    pasos = []
    for mensaje in mensajes:
        if isinstance(mensaje, AIMessage):
            for llamada in mensaje.tool_calls:
                pedidos[llamada["id"]] = llamada
        elif isinstance(mensaje, ToolMessage):
            llamada = pedidos.get(mensaje.tool_call_id, {})
            pasos.append(Paso(llamada.get("name", "?"), llamada.get("args", {}), leer_resultado(mensaje)))
    return pasos


def respuesta_es_segura(respuesta: str, pasos: list[Paso]) -> bool:
    """Revisa que todo número de etiqueta en la respuesta venga de una herramienta y no del modelo."""
    reales = {p.resultado.get("numero_etiqueta") for p in pasos}
    return all(numero in reales for numero in PATRON_ETIQUETA.findall(respuesta))


class AgenteEcoMarket:
    def __init__(self):
        self.agente = create_agent(crear_llm(), HERRAMIENTAS, system_prompt=PROMPT_AGENTE)

    def responder(self, mensaje: str, historial: list[dict] | None = None) -> Resultado:
        """historial es la conversación anterior: [{"role": "user" | "assistant", "content": "..."}]."""
        entrada = list(historial or []) + [HumanMessage(content=mensaje)]
        try:
            estado = self.agente.invoke(
                {"messages": entrada},
                config={"recursion_limit": config.MAX_PASOS_AGENTE},
            )
        except GraphRecursionError:
            registrar("agente", {"mensaje": mensaje}, {"ok": False, "codigo": "limite_de_pasos"})
            return Resultado(MENSAJE_ERROR_MODELO, hubo_error=True)
        except Exception as error:  # sin internet, sin saldo, key inválida, etc.
            registrar("agente", {"mensaje": mensaje}, {"ok": False, "codigo": "error_modelo", "mensaje": str(error)})
            return Resultado(MENSAJE_ERROR_MODELO, hubo_error=True)

        nuevos = estado["messages"][len(entrada):]
        pasos = extraer_pasos(nuevos)
        usos = [m.usage_metadata for m in nuevos if isinstance(m, AIMessage) and m.usage_metadata]
        respuesta = str(nuevos[-1].content).strip() if nuevos else ""

        hubo_error = False
        if not respuesta:
            respuesta, hubo_error = MENSAJE_ERROR_MODELO, True
        elif not respuesta_es_segura(respuesta, pasos):
            registrar("agente", {"mensaje": mensaje}, {"ok": False, "codigo": "etiqueta_inventada", "mensaje": respuesta})
            respuesta, hubo_error = MENSAJE_RESPUESTA_BLOQUEADA, True

        return Resultado(
            respuesta=respuesta,
            pasos=pasos,
            tokens_entrada=sum(u["input_tokens"] for u in usos),
            tokens_salida=sum(u["output_tokens"] for u in usos),
            hubo_error=hubo_error,
        )


def imprimir(resultado: Resultado):
    for paso in resultado.pasos:
        print(f"  [herramienta] {paso.herramienta}({paso.entrada})")
        print(f"     -> {paso.resultado.get('codigo') or paso.resultado.get('mensaje') or 'ok'}")
    print(f"EcoMarket: {resultado.respuesta}")
    print(f"  (tokens: {resultado.tokens_entrada} + {resultado.tokens_salida}, costo: {resultado.costo_usd:.6f} USD)")


def main():
    parser = argparse.ArgumentParser(description="Agente de EcoMarket")
    parser.add_argument("--mensaje", help="Mensaje del cliente")
    parser.add_argument("--interactivo", action="store_true", help="Conversación en la terminal")
    args = parser.parse_args()
    if not args.mensaje and not args.interactivo:
        parser.error('Usa --mensaje "..." o --interactivo')

    agente = AgenteEcoMarket()
    if args.mensaje:
        imprimir(agente.responder(args.mensaje))
        return

    historial: list[dict] = []
    print("Agente EcoMarket. Escribe 'salir' para terminar.")
    while True:
        mensaje = input("\nCliente: ").strip()
        if mensaje.lower() in {"salir", "exit", ""}:
            break
        resultado = agente.responder(mensaje, historial)
        imprimir(resultado)
        historial += [{"role": "user", "content": mensaje}, {"role": "assistant", "content": resultado.respuesta}]


if __name__ == "__main__":
    main()
