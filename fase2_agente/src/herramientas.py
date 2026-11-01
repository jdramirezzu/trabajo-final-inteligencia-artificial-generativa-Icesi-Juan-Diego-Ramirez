"""Herramientas (tools) del agente de EcoMarket.

Cada herramienta tiene dos partes:
- Una función normal de Python con la lógica (ej. revisar_elegibilidad). Se puede probar sin el modelo.
- Una función con @tool que el modelo puede llamar (ej. verificar_elegibilidad_producto). El texto de
  su docstring es lo que el modelo lee para decidir cuándo usarla.

Las herramientas simulan los sistemas de la empresa (pedidos y transportadora). Todas devuelven un
diccionario. Si algo falla devuelven ok=False con un código y un mensaje, y no lanzan excepciones.
Así el modelo siempre recibe una respuesta que puede explicarle al cliente.
"""
import json
import re
from datetime import date, datetime, timedelta
from functools import lru_cache, wraps
from typing import Optional

from langchain_core.tools import tool

import config
from indexar import abrir_base_vectorial

PATRON_TRACKING = re.compile(r"^ECM-\d{4}$")
MOTIVOS_DEFECTO = {"producto_danado", "producto_vencido", "producto_equivocado"}
MOTIVOS_VALIDOS = MOTIVOS_DEFECTO | {"otro"}
CATEGORIA_PERECEDEROS = "alimentos_perecederos"
CATEGORIA_HIGIENE = "higiene"


def _error(codigo: str, mensaje: str) -> dict:
    return {"ok": False, "codigo": codigo, "mensaje": mensaje}


def _no_elegible(codigo: str, mensaje: str) -> dict:
    return {"ok": True, "elegible": False, "codigo": codigo, "mensaje": mensaje}


def _normalizar(tracking_number: str) -> str:
    return tracking_number.strip().upper()


def _buscar_en_json(tracking_number: str) -> Optional[dict]:
    with open(config.RUTA_PEDIDOS_JSON, encoding="utf-8") as f:
        pedidos = json.load(f)
    for pedido in pedidos:
        if pedido["tracking_number"] == tracking_number:
            return pedido
    return None


def _obtener_pedido(tracking_number: str) -> dict:
    """Valida el número y busca el pedido. Devuelve {"pedido": ...} o un error."""
    numero = _normalizar(tracking_number)
    if not PATRON_TRACKING.match(numero):
        return _error("formato_invalido", "El número de seguimiento debe tener el formato ECM-XXXX, por ejemplo ECM-1005.")
    pedido = _buscar_en_json(numero)
    if pedido is None:
        return _error("pedido_no_encontrado", f"No existe ningún pedido con el número {numero}.")
    return {"ok": True, "pedido": pedido}


# --- Lógica de las herramientas ---


def buscar_datos_pedido(tracking_number: str) -> dict:
    encontrado = _obtener_pedido(tracking_number)
    if not encontrado["ok"]:
        return encontrado
    pedido = encontrado["pedido"]
    return {
        "ok": True,
        "tracking_number": pedido["tracking_number"],
        "cliente": pedido["customer_name"],
        "producto": pedido["product"],
        "estado": pedido["status"],
        "fecha_pedido": pedido["order_date"],
        "entrega_estimada": pedido["estimated_delivery"],
        "entrega_real": pedido["actual_delivery"],
        "ciudad": pedido["delivery_city"],
        "detalle": pedido["notes"],
    }


def revisar_elegibilidad(tracking_number: str, motivo: str = "otro", producto_abierto: Optional[bool] = None) -> dict:
    """Aplica las reglas de la política en orden. El modelo no decide: solo recibe el resultado."""
    if motivo not in MOTIVOS_VALIDOS:
        return _error("motivo_invalido", f"El motivo debe ser uno de: {', '.join(sorted(MOTIVOS_VALIDOS))}.")

    encontrado = _obtener_pedido(tracking_number)
    if not encontrado["ok"]:
        return encontrado
    pedido = encontrado["pedido"]
    estado = pedido["status"]

    # 1. El estado del pedido
    if estado == "devuelto":
        return _no_elegible("ya_devuelto", "Este pedido ya fue devuelto.")
    if estado == "cancelado":
        return _no_elegible("pedido_cancelado", "Este pedido fue cancelado, así que no hay nada que devolver.")
    if estado != "entregado" or not pedido["actual_delivery"]:
        return _no_elegible(
            "no_entregado",
            f"El pedido está '{estado}'. Solo se puede devolver un pedido que ya fue entregado.",
        )

    entrega = date.fromisoformat(pedido["actual_delivery"])
    dias = (config.FECHA_ACTUAL - entrega).days

    # 2. Producto dañado, vencido o equivocado (sección 6): aplica a todas las categorías
    if motivo in MOTIVOS_DEFECTO and dias <= config.DIAS_PARA_REPORTAR_DEFECTO:
        return {
            "ok": True,
            "elegible": True,
            "tipo": "producto_defectuoso",
            "producto": pedido["product"],
            "requiere_foto": True,
            "soluciones": ["cambio por el mismo producto", "reembolso completo"],
            "mensaje": "Es elegible por producto dañado, vencido o equivocado. El cliente debe adjuntar una foto.",
        }

    # 3. Productos que no se devuelven (sección 3)
    if pedido["product_category"] == CATEGORIA_PERECEDEROS:
        return _no_elegible("perecedero", "Los alimentos perecederos no se pueden devolver por norma sanitaria.")
    if pedido["product_category"] == CATEGORIA_HIGIENE:
        if producto_abierto is None:
            return _no_elegible("falta_informacion", "Falta saber si el producto de higiene ya fue abierto o usado.")
        if producto_abierto:
            return _no_elegible("higiene_abierto", "Los productos de higiene abiertos o usados no se pueden devolver.")
    elif not pedido["returnable"]:
        return _no_elegible("no_devolvible", "Este producto no admite devolución.")

    # 4. Plazo de 30 días desde la entrega (sección 2)
    fecha_limite = entrega + timedelta(days=config.DIAS_PARA_DEVOLVER)
    if dias > config.DIAS_PARA_DEVOLVER:
        return _no_elegible(
            "fuera_de_plazo",
            f"El plazo de {config.DIAS_PARA_DEVOLVER} días terminó el {fecha_limite.isoformat()}.",
        )

    return {
        "ok": True,
        "elegible": True,
        "tipo": "devolucion_normal",
        "producto": pedido["product"],
        "requiere_foto": False,
        "fecha_limite": fecha_limite.isoformat(),
        "mensaje": "El pedido cumple las condiciones para la devolución.",
    }


def _leer_etiquetas() -> dict:
    if not config.RUTA_ETIQUETAS.exists():
        return {}
    return json.loads(config.RUTA_ETIQUETAS.read_text(encoding="utf-8"))


def crear_etiqueta(tracking_number: str, motivo: str = "otro", producto_abierto: Optional[bool] = None) -> dict:
    """Crea la etiqueta. Vuelve a revisar la elegibilidad aunque el modelo diga que ya lo hizo."""
    numero = _normalizar(tracking_number)

    # Si ya existe, se devuelve la misma. Evita etiquetas repetidas si el modelo llama dos veces.
    etiquetas = _leer_etiquetas()
    if numero in etiquetas:
        return {"ok": True, "ya_existia": True, **etiquetas[numero]}

    revision = revisar_elegibilidad(numero, motivo, producto_abierto)
    if not revision["ok"]:
        return revision
    if not revision["elegible"]:
        return _error(revision["codigo"], f"No se generó la etiqueta. {revision['mensaje']}")

    if config.SIMULAR_FALLA_TRANSPORTADORA:
        return _error(
            "servicio_no_disponible",
            "El sistema de la transportadora no responde. La etiqueta no se generó.",
        )

    etiqueta = {
        "numero_etiqueta": f"RMA-{numero.removeprefix('ECM-')}",
        "tracking_number": numero,
        "producto": revision["producto"],
        "motivo": motivo,
        "transportadora": "EcoEnvíos",
        "fecha_generacion": config.FECHA_ACTUAL.isoformat(),
        "envio_gratis": True,
        "instrucciones": "Imprime la etiqueta, pégala en el paquete y entrégalo en un punto de EcoEnvíos.",
    }
    etiquetas[numero] = etiqueta
    config.SALIDAS_DIR.mkdir(exist_ok=True)
    config.RUTA_ETIQUETAS.write_text(json.dumps(etiquetas, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "ya_existia": False, **etiqueta}


@lru_cache(maxsize=1)
def _base_vectorial():
    """Abre la base una sola vez. Cargar el modelo de embeddings en cada pregunta sería muy lento."""
    return abrir_base_vectorial()


def buscar_en_documentos(pregunta: str, k: int = config.K_FRAGMENTOS) -> dict:
    """Esta es la parte RAG del Taller 2, ahora como herramienta."""
    try:
        fragmentos = _base_vectorial().similarity_search(pregunta, k=k)
    except (Exception, SystemExit) as error:  # abrir_base_vectorial usa SystemExit si no existe chroma_db
        return _error("base_no_disponible", f"No se pudo consultar la base de conocimiento: {error}")
    return {
        "ok": True,
        "fragmentos": [{"fuente": doc.metadata["fuente"], "texto": doc.page_content} for doc in fragmentos],
    }


# --- Registro de acciones ---


def registrar(herramienta: str, entrada: dict, resultado: dict):
    """Guarda una línea JSON por cada llamada a una herramienta."""
    config.SALIDAS_DIR.mkdir(exist_ok=True)
    resumen = {k: v for k, v in resultado.items() if k != "fragmentos"}
    evento = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "herramienta": herramienta,
        "entrada": entrada,
        "resultado": resumen,
    }
    with open(config.RUTA_REGISTRO, "a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")


def con_registro(funcion):
    """Agrega a una herramienta el registro de la llamada y la captura de errores inesperados."""

    @wraps(funcion)
    def envoltura(**entrada) -> dict:
        try:
            resultado = funcion(**entrada)
        except Exception as error:
            resultado = _error("error_interno", f"Ocurrió un error inesperado: {error}")
        registrar(funcion.__name__, entrada, resultado)
        return resultado

    return envoltura


# --- Herramientas que ve el modelo ---


@tool
@con_registro
def consultar_pedido(tracking_number: str) -> dict:
    """Consulta el estado y las fechas de un pedido. Úsala cuando el cliente pregunte por su pedido
    y haya dado un número de seguimiento con formato ECM-XXXX."""
    return buscar_datos_pedido(tracking_number)


@tool
@con_registro
def verificar_elegibilidad_producto(
    tracking_number: str, motivo: str = "otro", producto_abierto: Optional[bool] = None
) -> dict:
    """Revisa si un pedido se puede devolver según la política. Úsala siempre antes de generar una etiqueta.

    motivo debe ser producto_danado, producto_vencido, producto_equivocado u otro.
    producto_abierto es true o false si el cliente lo dijo. Si no lo dijo, no lo envíes.
    """
    return revisar_elegibilidad(tracking_number, motivo, producto_abierto)


@tool
@con_registro
def generar_etiqueta_devolucion(
    tracking_number: str, motivo: str = "otro", producto_abierto: Optional[bool] = None
) -> dict:
    """Genera la etiqueta de devolución. Úsala solo si el cliente pidió devolver el producto y
    verificar_elegibilidad_producto respondió elegible=true. Usa el mismo motivo y producto_abierto."""
    return crear_etiqueta(tracking_number, motivo, producto_abierto)


@tool
@con_registro
def consultar_base_conocimiento(pregunta: str) -> dict:
    """Busca en los documentos de EcoMarket: política de devoluciones, reembolsos, envíos, catálogo
    de productos, precios, stock y preguntas frecuentes. Úsala para cualquier pregunta sobre la tienda."""
    return buscar_en_documentos(pregunta)


HERRAMIENTAS = [
    consultar_pedido,
    verificar_elegibilidad_producto,
    generar_etiqueta_devolucion,
    consultar_base_conocimiento,
]
