"""Pruebas del manejo de errores del agente. Usan un modelo falso, así que no gastan saldo.

    pytest fase2_agente/tests
"""
import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config
import herramientas
from agente import MENSAJE_ERROR_MODELO, MENSAJE_RESPUESTA_BLOQUEADA, AgenteEcoMarket


@pytest.fixture(autouse=True)
def carpeta_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SALIDAS_DIR", tmp_path)
    monkeypatch.setattr(config, "RUTA_REGISTRO", tmp_path / "registro.jsonl")


class GrafoFalso:
    """Reemplaza al agente real: devuelve mensajes fijos o lanza un error."""

    def __init__(self, nuevos=None, error=None):
        self.nuevos = nuevos or []
        self.error = error

    def invoke(self, entrada, config=None):
        if self.error:
            raise self.error
        return {"messages": entrada["messages"] + self.nuevos}


def agente_con(grafo) -> AgenteEcoMarket:
    agente = AgenteEcoMarket.__new__(AgenteEcoMarket)  # sin crear el modelo real
    agente.agente = grafo
    return agente


def llamada_etiqueta(id_llamada="1"):
    return AIMessage(
        content="",
        tool_calls=[{"name": "generar_etiqueta_devolucion", "args": {"tracking_number": "ECM-1005"}, "id": id_llamada}],
    )


def test_falla_de_la_api_da_mensaje_amable_y_queda_registrada():
    r = agente_con(GrafoFalso(error=RuntimeError("sin saldo"))).responder("hola")
    assert r.respuesta == MENSAJE_ERROR_MODELO
    assert r.hubo_error is True
    assert "error_modelo" in config.RUTA_REGISTRO.read_text(encoding="utf-8")


def test_limite_de_pasos_da_mensaje_amable():
    r = agente_con(GrafoFalso(error=GraphRecursionError("ciclo"))).responder("hola")
    assert r.respuesta == MENSAJE_ERROR_MODELO
    assert "limite_de_pasos" in config.RUTA_REGISTRO.read_text(encoding="utf-8")


def test_respuesta_vacia_del_modelo_da_mensaje_amable():
    r = agente_con(GrafoFalso([AIMessage(content="")])).responder("hola")
    assert r.respuesta == MENSAJE_ERROR_MODELO


def test_bloquea_un_numero_de_etiqueta_que_no_vino_de_una_herramienta():
    r = agente_con(GrafoFalso([AIMessage(content="Tu etiqueta es RMA-1005.")])).responder("hola")
    assert r.respuesta == MENSAJE_RESPUESTA_BLOQUEADA
    assert r.hubo_error is True


def test_acepta_un_numero_de_etiqueta_que_si_vino_de_la_herramienta():
    nuevos = [
        llamada_etiqueta(),
        ToolMessage(content='{"ok": true, "numero_etiqueta": "RMA-1005"}', tool_call_id="1"),
        AIMessage(content="Tu etiqueta es RMA-1005."),
    ]
    r = agente_con(GrafoFalso(nuevos)).responder("Quiero devolver ECM-1005")
    assert r.respuesta == "Tu etiqueta es RMA-1005."
    assert r.etiqueta["numero_etiqueta"] == "RMA-1005"
    assert r.pasos[0].herramienta == "generar_etiqueta_devolucion"


def test_la_conversacion_anterior_llega_al_modelo():
    grafo = GrafoFalso([AIMessage(content="ok")])
    historial = [{"role": "user", "content": "Quiero devolver ECM-1001"}, {"role": "assistant", "content": "¿Lo abriste?"}]
    r = agente_con(grafo).responder("No", historial)
    assert r.respuesta == "ok"


def test_rag_sin_base_vectorial_devuelve_error_y_no_tumba_el_agente(monkeypatch):
    def sin_base():
        raise SystemExit("No existe chroma_db/")

    herramientas._base_vectorial.cache_clear()
    monkeypatch.setattr(herramientas, "abrir_base_vectorial", sin_base)
    r = herramientas.buscar_en_documentos("hola")
    herramientas._base_vectorial.cache_clear()
    assert r["ok"] is False
    assert r["codigo"] == "base_no_disponible"


def test_mensaje_del_cliente_se_envia_como_mensaje_humano():
    grafo = GrafoFalso([AIMessage(content="ok")])
    enviados = {}
    invocar = grafo.invoke

    def espiar(entrada, config=None):
        enviados.update(entrada)
        return invocar(entrada, config)

    grafo.invoke = espiar
    agente_con(grafo).responder("hola")
    assert isinstance(enviados["messages"][-1], HumanMessage)
