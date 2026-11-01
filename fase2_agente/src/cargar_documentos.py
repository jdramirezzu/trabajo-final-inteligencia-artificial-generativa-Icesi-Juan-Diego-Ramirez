"""Carga los 3 tipos de documentos de EcoMarket y los divide en fragmentos (chunks).

Cada tipo de documento se corta de forma distinta (ver fase2_base_conocimiento):
- Preguntas frecuentes (JSON): 1 fragmento por cada pregunta con su respuesta.
- Catálogo de productos (CSV): 1 fragmento por cada producto (fila).
- Política de devoluciones y envíos (PDF): 1 fragmento por sección numerada.
  Si una sección es más larga que CHUNK_SIZE, se corta con un splitter recursivo.

Se puede ejecutar solo para ver los fragmentos:
    python cargar_documentos.py
"""
import csv
import json
import re

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config


def cargar_faq() -> list[Document]:
    with open(config.RUTA_FAQ_JSON, encoding="utf-8") as f:
        faqs = json.load(f)

    documentos = []
    for faq in faqs:
        texto = f"Pregunta: {faq['pregunta']}\nRespuesta: {faq['respuesta']}"
        documentos.append(
            Document(
                page_content=texto,
                metadata={"fuente": "preguntas_frecuentes.json", "tipo": "faq", "id": faq["id"], "tema": faq["tema"]},
            )
        )
    return documentos


def cargar_catalogo() -> list[Document]:
    with open(config.RUTA_CATALOGO_CSV, encoding="utf-8") as f:
        filas = list(csv.DictReader(f))

    documentos = []
    for fila in filas:
        stock = int(fila["stock"])
        disponibilidad = f"{stock} unidades disponibles" if stock > 0 else "AGOTADO (0 unidades)"
        precio = f"{int(fila['precio_cop']):,}".replace(",", ".")  # 24000 -> 24.000
        # Se escribe la fila como frase para que el embedding entienda mejor el contenido
        texto = (
            f"Producto: {fila['nombre']} (SKU {fila['sku']}).\n"
            f"Categoría: {fila['categoria']}.\n"
            f"Precio: {precio} COP.\n"
            f"Stock: {disponibilidad}.\n"
            f"¿Se puede devolver?: {fila['devolvible']}.\n"
            f"Descripción: {fila['descripcion']}\n"
            f"Materiales: {fila['materiales']}.\n"
            f"Cuidados: {fila['cuidados']}"
        )
        documentos.append(
            Document(
                page_content=texto,
                metadata={"fuente": "catalogo_productos.csv", "tipo": "catalogo", "id": fila["sku"]},
            )
        )
    return documentos


def cargar_politica() -> list[Document]:
    paginas = PyPDFLoader(str(config.RUTA_POLITICA_PDF)).load()
    texto = "\n".join(pagina.page_content for pagina in paginas)

    # El PDF corta las líneas largas y deja " \n" en medio de las frases. Se vuelven a unir.
    texto = texto.replace(" \n", " ")

    # Se separa el texto donde empieza un título de sección, ej. "2. PLAZO PARA DEVOLVER UN PRODUCTO"
    partes = re.split(r"\n(?=\d+\. [A-ZÁÉÍÓÚÑ ,]+\n)", texto)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n", ". ", " "],
    )

    documentos = []
    for parte in partes[1:]:  # partes[0] es el encabezado del documento (título y versión)
        titulo = parte.split("\n", 1)[0].strip()
        for i, pedazo in enumerate(splitter.split_text(parte)):
            # Si la sección se cortó en varios pedazos, cada pedazo lleva el título para no perder el tema
            if i > 0:
                pedazo = f"{titulo} (continuación)\n{pedazo}"
            documentos.append(
                Document(
                    page_content=pedazo,
                    metadata={"fuente": "politica_devoluciones_y_envios.pdf", "tipo": "politica", "id": titulo},
                )
            )
    return documentos


def cargar_todos() -> list[Document]:
    return cargar_politica() + cargar_catalogo() + cargar_faq()


if __name__ == "__main__":
    fragmentos = cargar_todos()
    for doc in fragmentos:
        print("-" * 80)
        print(f"[{doc.metadata['tipo']} | {doc.metadata['id']} | {len(doc.page_content)} caracteres]")
        print(doc.page_content)
    print("=" * 80)
    print(f"Total de fragmentos: {len(fragmentos)}")
