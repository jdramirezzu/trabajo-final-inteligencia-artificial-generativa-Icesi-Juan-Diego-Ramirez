"""Indexación: fragmentos -> vectores (embeddings) -> base de datos vectorial (ChromaDB).

Pasos:
1. Cargar y cortar los documentos (cargar_documentos.py).
2. Cargar el modelo de embeddings de Hugging Face.
3. Convertir cada fragmento en un vector y guardarlo en Chroma, en la carpeta chroma_db/.

Se ejecuta una sola vez, o cada vez que cambien los documentos de data/:
    python indexar.py
"""
import shutil

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

import config
from cargar_documentos import cargar_todos


def obtener_embeddings() -> HuggingFaceEmbeddings:
    # normalize_embeddings=True deja todos los vectores con largo 1,
    # así la similitud coseno compara solo la dirección (el significado) y no el tamaño.
    return HuggingFaceEmbeddings(
        model_name=config.MODELO_EMBEDDINGS,
        encode_kwargs={"normalize_embeddings": True},
    )


def abrir_base_vectorial() -> Chroma:
    """Abre la base de datos que ya fue creada con indexar.py."""
    if not config.CHROMA_DIR.exists():
        raise SystemExit("No existe chroma_db/. Primero ejecuta: python indexar.py")
    return Chroma(
        collection_name=config.NOMBRE_COLECCION,
        embedding_function=obtener_embeddings(),
        persist_directory=str(config.CHROMA_DIR),
    )


def main():
    fragmentos = cargar_todos()
    print(f"Fragmentos cargados: {len(fragmentos)}")

    # Se borra la base anterior para no tener fragmentos repetidos si se indexa dos veces
    if config.CHROMA_DIR.exists():
        shutil.rmtree(config.CHROMA_DIR)

    print(f"Cargando modelo de embeddings: {config.MODELO_EMBEDDINGS}")
    embeddings = obtener_embeddings()

    print("Convirtiendo fragmentos en vectores y guardándolos en Chroma...")
    Chroma.from_documents(
        documents=fragmentos,
        embedding=embeddings,
        collection_name=config.NOMBRE_COLECCION,
        persist_directory=str(config.CHROMA_DIR),
        collection_metadata={"hnsw:space": "cosine"},  # medir similitud con coseno
        ids=[f"{doc.metadata['tipo']}-{doc.metadata['id']}-{i}" for i, doc in enumerate(fragmentos)],
    )

    dimension = len(embeddings.embed_query("prueba"))
    print(f"Listo. {len(fragmentos)} vectores de {dimension} dimensiones guardados en {config.CHROMA_DIR}")


if __name__ == "__main__":
    main()
