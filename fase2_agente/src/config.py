"""Configuración del agente de EcoMarket.

Todos los valores que se pueden cambiar para experimentar están aquí,
para no tener que buscarlos dentro del código.
"""
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

# Carpetas del proyecto
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR = BASE_DIR / "chroma_db"  # aquí Chroma guarda los vectores en disco
RESULTADOS_DIR = BASE_DIR / "resultados"
SALIDAS_DIR = BASE_DIR / "salidas"  # lo que el agente genera mientras funciona

# Archivos que escribe el agente
RUTA_ETIQUETAS = SALIDAS_DIR / "etiquetas_generadas.json"
RUTA_REGISTRO = SALIDAS_DIR / "registro_acciones.jsonl"

# Documentos de la base de conocimiento
RUTA_POLITICA_PDF = DATA_DIR / "politica_devoluciones_y_envios.pdf"
RUTA_CATALOGO_CSV = DATA_DIR / "catalogo_productos.csv"
RUTA_FAQ_JSON = DATA_DIR / "preguntas_frecuentes.json"
RUTA_PEDIDOS_JSON = DATA_DIR / "pedidos.json"  # no se indexa, se consulta por número exacto

# Modelo de embeddings (open source, Hugging Face, corre local y gratis)
MODELO_EMBEDDINGS = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Base de datos vectorial
NOMBRE_COLECCION = "ecomarket_conocimiento"

# Chunking de la política (el PDF es el único documento que se corta con splitter)
CHUNK_SIZE = 700
CHUNK_OVERLAP = 100

# Recuperación: cuántos fragmentos se le pasan al modelo
K_FRAGMENTOS = 4

# Los pedidos de prueba son de septiembre de 2026. Se fija la fecha de "hoy" para que los plazos
# de 30 y 5 días den siempre el mismo resultado, sin importar el día en que se ejecute.
FECHA_ACTUAL = date(2026, 9, 17)

# Reglas de la política de devoluciones (secciones 2 y 6 del PDF)
DIAS_PARA_DEVOLVER = 30
DIAS_PARA_REPORTAR_DEFECTO = 5

# Si es True, la herramienta de etiquetas falla a propósito (para probar el manejo de errores)
SIMULAR_FALLA_TRANSPORTADORA = False

# Máximo de pasos del agente en una respuesta. Evita ciclos que gasten saldo.
MAX_PASOS_AGENTE = 12

# Modelo generativo: DeepSeek Flash por API (compatible con el formato de OpenAI)
load_dotenv(BASE_DIR / ".env")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MODELO_LLM = "deepseek-flash"
MAX_TOKENS_RESPUESTA = 400  # límite de salida para gastar poco saldo
TEMPERATURA = 0.0  # respuestas más estables entre ejecuciones
