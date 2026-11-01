"""Pruebas de las herramientas del agente. No llaman a DeepSeek, así que no gastan saldo.

    pytest fase2_agente/tests
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config
import herramientas


@pytest.fixture(autouse=True)
def carpeta_temporal(tmp_path, monkeypatch):
    """Cada prueba escribe etiquetas y registros en una carpeta temporal."""
    monkeypatch.setattr(config, "SALIDAS_DIR", tmp_path)
    monkeypatch.setattr(config, "RUTA_ETIQUETAS", tmp_path / "etiquetas.json")
    monkeypatch.setattr(config, "RUTA_REGISTRO", tmp_path / "registro.jsonl")
    monkeypatch.setattr(config, "SIMULAR_FALLA_TRANSPORTADORA", False)


def verificar(tracking, motivo="otro", producto_abierto=None):
    return herramientas.revisar_elegibilidad(tracking, motivo, producto_abierto)


# --- verificar elegibilidad ---


def test_devolvible_entregado_dentro_del_plazo_es_elegible():
    r = verificar("ECM-1005")
    assert r["ok"] is True
    assert r["elegible"] is True
    assert r["tipo"] == "devolucion_normal"
    assert r["fecha_limite"] == "2026-10-02"


def test_acepta_minusculas_y_espacios_en_el_numero():
    assert verificar("  ecm-1005 ")["elegible"] is True


def test_numero_con_formato_invalido_es_error():
    r = verificar("1005")
    assert r["ok"] is False
    assert r["codigo"] == "formato_invalido"


def test_pedido_que_no_existe_es_error():
    r = verificar("ECM-9999")
    assert r["ok"] is False
    assert r["codigo"] == "pedido_no_encontrado"


def test_motivo_desconocido_es_error():
    r = verificar("ECM-1005", motivo="porque si")
    assert r["ok"] is False
    assert r["codigo"] == "motivo_invalido"


@pytest.mark.parametrize(
    "tracking, codigo",
    [
        ("ECM-1002", "no_entregado"),  # en tránsito
        ("ECM-1004", "no_entregado"),  # retrasado
        ("ECM-1011", "no_entregado"),  # pendiente de despacho
        ("ECM-1006", "pedido_cancelado"),
        ("ECM-1007", "ya_devuelto"),
    ],
)
def test_estados_que_no_permiten_devolucion(tracking, codigo):
    r = verificar(tracking)
    assert r["ok"] is True
    assert r["elegible"] is False
    assert r["codigo"] == codigo


def test_fuera_del_plazo_de_30_dias_no_es_elegible():
    r = verificar("ECM-1012")
    assert r["elegible"] is False
    assert r["codigo"] == "fuera_de_plazo"


def test_perecedero_sin_defecto_no_es_elegible():
    r = verificar("ECM-1003")
    assert r["elegible"] is False
    assert r["codigo"] == "perecedero"


def test_perecedero_vencido_dentro_de_5_dias_es_elegible():
    r = verificar("ECM-1003", motivo="producto_vencido")
    assert r["elegible"] is True
    assert r["tipo"] == "producto_defectuoso"
    assert r["requiere_foto"] is True


def test_higiene_sin_saber_si_esta_abierto_pide_el_dato():
    r = verificar("ECM-1001")
    assert r["ok"] is True
    assert r["elegible"] is False
    assert r["codigo"] == "falta_informacion"


def test_higiene_abierto_no_es_elegible():
    r = verificar("ECM-1001", producto_abierto=True)
    assert r["elegible"] is False
    assert r["codigo"] == "higiene_abierto"


def test_higiene_sin_abrir_es_elegible():
    assert verificar("ECM-1001", producto_abierto=False)["elegible"] is True


def test_defecto_reportado_tarde_en_producto_devolvible_sigue_como_devolucion_normal():
    r = verificar("ECM-1005", motivo="producto_danado")  # entregado hace 15 días
    assert r["elegible"] is True
    assert r["tipo"] == "devolucion_normal"


def test_defecto_reportado_tarde_en_higiene_abierto_no_es_elegible():
    r = verificar("ECM-1001", motivo="producto_danado", producto_abierto=True)  # entregado hace 12 días
    assert r["elegible"] is False


# --- generar etiqueta ---


def test_genera_etiqueta_para_pedido_elegible():
    r = herramientas.crear_etiqueta("ECM-1005", "otro", None)
    assert r["ok"] is True
    assert r["numero_etiqueta"] == "RMA-1005"
    assert r["ya_existia"] is False
    guardadas = json.loads(config.RUTA_ETIQUETAS.read_text(encoding="utf-8"))
    assert guardadas["ECM-1005"]["numero_etiqueta"] == "RMA-1005"


def test_no_genera_etiqueta_si_no_es_elegible_aunque_el_modelo_la_pida():
    r = herramientas.crear_etiqueta("ECM-1003", "otro", None)
    assert r["ok"] is False
    assert r["codigo"] == "perecedero"
    assert not config.RUTA_ETIQUETAS.exists()


def test_pedir_la_etiqueta_dos_veces_no_crea_una_segunda():
    herramientas.crear_etiqueta("ECM-1005", "otro", None)
    r = herramientas.crear_etiqueta("ECM-1005", "otro", None)
    assert r["ok"] is True
    assert r["ya_existia"] is True
    guardadas = json.loads(config.RUTA_ETIQUETAS.read_text(encoding="utf-8"))
    assert len(guardadas) == 1


def test_falla_de_la_transportadora_devuelve_error_y_no_guarda(monkeypatch):
    monkeypatch.setattr(config, "SIMULAR_FALLA_TRANSPORTADORA", True)
    r = herramientas.crear_etiqueta("ECM-1005", "otro", None)
    assert r["ok"] is False
    assert r["codigo"] == "servicio_no_disponible"
    assert not config.RUTA_ETIQUETAS.exists()


# --- consultar pedido y registro ---


def test_consultar_pedido_no_entrega_notas_ni_datos_de_mas_cuando_no_existe():
    assert herramientas.buscar_datos_pedido("ECM-9999")["codigo"] == "pedido_no_encontrado"


def test_consultar_pedido_devuelve_estado():
    r = herramientas.buscar_datos_pedido("ECM-1004")
    assert r["ok"] is True
    assert r["estado"] == "retrasado"


def test_cada_llamada_a_una_herramienta_queda_registrada():
    herramientas.generar_etiqueta_devolucion.invoke({"tracking_number": "ECM-1005", "motivo": "otro"})
    lineas = config.RUTA_REGISTRO.read_text(encoding="utf-8").strip().splitlines()
    evento = json.loads(lineas[-1])
    assert evento["herramienta"] == "generar_etiqueta_devolucion"
    assert evento["resultado"]["numero_etiqueta"] == "RMA-1005"
