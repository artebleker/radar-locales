"""Padrón de ARCA: parseo, clasificación, descarga con estado y altas. Datos sintéticos, sin red."""

import copy
import gzip
import io
import zipfile
from datetime import date

import pytest

from radar import cli
from radar import config as cfg
from radar import enriquecer_cuit
from radar.padron import descargar, parsear


def linea(cuit, nombre, iva="AC", empleador="S"):
    """Línea de ancho fijo con el diseño oficial (51 caracteres)."""
    return f"{cuit}{nombre:<30.30}NI{iva}NIN{empleador}00"


def zip_padron(lineas):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SELE-SAL-CONSTA.tmp", ("\r\n".join(lineas) + "\r\n").encode("latin-1"))
    return buf.getvalue()


LINEAS = [
    linea("30711111111", "CAFETERIA LUNA DEL NORTE SRL"),
    linea("33722222222", "FERRETERIA EL TORNILLO SA"),
    linea("20123456789", "PEREZ JUAN"),          # persona física: se descarta
    linea("27987654321", "GOMEZ MARIA"),         # persona física: se descarta
]


@pytest.fixture()
def conf(tmp_path):
    c = cfg.Config(copy.deepcopy(dict(cfg.cargar())))
    c["rutas"]["padron_local"] = str(tmp_path / "padron_local")
    c["rutas"]["altas_cuit"] = str(tmp_path / "altas_cuit")
    return c


class Resp:
    def __init__(self, contenido):
        self.content = contenido
        self.headers = {"Last-Modified": "Sat, 17 Oct 2026 15:56:05 GMT"}


class ClienteFalso:
    def __init__(self, contenido=None, error=None):
        self.contenido, self.error, self.pedidos = contenido, error, 0

    def pedir(self, url, **kw):
        self.pedidos += 1
        assert kw.get("cachear") is False, "el zip trae nombres de personas: no debe ir a la caché HTTP"
        if self.error:
            raise self.error
        return Resp(self.contenido)


# --- clasificación y parseo ----------------------------------------------------------
@pytest.mark.parametrize("cuit,tipo", [
    ("30711111111", "juridica"), ("33722222222", "juridica"), ("34000000001", "juridica"),
    ("20123456789", "fisica"), ("23123456789", "fisica"), ("24123456789", "fisica"), ("27987654321", "fisica"),
    ("50000000000", "otro"),
])
def test_tipo_persona(conf, cuit, tipo):
    assert parsear.tipo_persona(cuit, conf["padron"]) == tipo


def test_linea_sintetica_respeta_el_diseno():
    assert len(linea("30711111111", "X")) == 51


def test_solo_personas_juridicas(conf):
    filas, total = parsear.juridicas(zip_padron(LINEAS), conf["padron"])
    assert total == 4
    assert [f["cuit"] for f in filas] == ["30711111111", "33722222222"]
    assert filas[0]["razon_social"] == "CAFETERIA LUNA DEL NORTE SRL" and filas[0]["iva"] == "AC"


def test_formato_que_no_coincide(conf):
    with pytest.raises(parsear.FormatoInvalido):
        parsear.juridicas(zip_padron(["esto no es el padrón"]), conf["padron"])


def test_csv_con_columnas_por_encabezado(conf):
    p = conf["padron"]
    p.update(formato="csv", codificacion="utf-8")
    p["columnas"] = {"cuit": "CUIT", "razon_social": "RAZON", "domicilio_calle": "CALLE", "domicilio_altura": "ALTURA",
                     **{k: None for k in ("ganancias", "iva", "monotributo", "integrante_sociedad", "empleador",
                                          "actividad_monotributo", "codigo_postal", "localidad",
                                          "fecha_inicio_actividades", "actividad_principal")}}
    contenido = "CUIT,RAZON,CALLE,ALTURA\n30711111111,Luna SRL,Av. Italia,1299\n20123456789,Perez,Belgrano,10\n".encode()
    filas, total = parsear.juridicas(contenido, p)
    assert total == 2 and filas == [{"cuit": "30711111111", "razon_social": "Luna SRL",
                                     "domicilio_calle": "Av. Italia", "domicilio_altura": "1299"}]


# --- descarga con estado -------------------------------------------------------------------
def test_primera_descarga_guarda_solo_juridicas(conf):
    res = descargar.actualizar(conf, ClienteFalso(zip_padron(LINEAS)), date(2026, 10, 21))
    assert res["accion"] == "actualizada"
    est = descargar.leer_estado(conf)
    assert (est["filas_total"], est["filas_juridicas"], est["periodo"]) == (4, 2, "2026-10")
    [archivo] = descargar.derivados(conf)
    assert archivo.name == "2026-10.tsv.gz"
    texto = gzip.open(archivo, "rt", encoding="utf-8").read()
    assert "PEREZ" not in texto and "20123456789" not in texto


def test_descarga_omitida_dentro_del_plazo(conf):
    descargar.actualizar(conf, ClienteFalso(zip_padron(LINEAS)), date(2026, 10, 1))
    cliente = ClienteFalso(zip_padron(LINEAS))
    res = descargar.actualizar(conf, cliente, date(2026, 10, 20))
    assert res["accion"] == "omitida" and cliente.pedidos == 0


def test_forzar_ignora_el_plazo(conf):
    descargar.actualizar(conf, ClienteFalso(zip_padron(LINEAS)), date(2026, 10, 1))
    cliente = ClienteFalso(zip_padron(LINEAS))
    assert descargar.actualizar(conf, cliente, date(2026, 10, 2), forzar=True)["accion"] == "sin_cambios"
    assert cliente.pedidos == 1


def test_mismo_sha_no_reprocesa(conf):
    descargar.actualizar(conf, ClienteFalso(zip_padron(LINEAS)), date(2026, 9, 1))
    res = descargar.actualizar(conf, ClienteFalso(zip_padron(LINEAS)), date(2026, 10, 5))
    assert res["accion"] == "sin_cambios"
    assert [a.name for a in descargar.derivados(conf)] == ["2026-09.tsv.gz"]
    assert descargar.leer_estado(conf)["ultima_descarga"] == "2026-10-05"


@pytest.mark.parametrize("error", [ConnectionError("sin red"), None])
def test_descarga_fallida_conserva_el_anterior(conf, error):
    descargar.actualizar(conf, ClienteFalso(zip_padron(LINEAS)), date(2026, 9, 1))
    antes = descargar.leer_estado(conf)
    roto = ClienteFalso(zip_padron(["basura"]), error=error)  # sin red, o formato que no coincide
    with pytest.raises(Exception):
        descargar.actualizar(conf, roto, date(2026, 10, 5))
    assert descargar.leer_estado(conf) == antes
    assert [a.name for a in descargar.derivados(conf)] == ["2026-09.tsv.gz"]


def test_conserva_solo_mes_actual_y_anterior(conf):
    for i, mes in enumerate((8, 9, 10)):
        extra = [linea(f"3070000000{i}", f"SOCIEDAD NUEVA {i} SA")]
        descargar.actualizar(conf, ClienteFalso(zip_padron(LINEAS + extra)), date(2026, mes, 1))
    assert [a.name for a in descargar.derivados(conf)] == ["2026-09.tsv.gz", "2026-10.tsv.gz"]


# --- altas mensuales -------------------------------------------------------------------------
def test_altas_con_cambios(conf):
    descargar.actualizar(conf, ClienteFalso(zip_padron(LINEAS)), date(2026, 9, 1))
    nueva = linea("30799999999", "HELADERIA POLO SUR SA")
    descargar.actualizar(conf, ClienteFalso(zip_padron(LINEAS + [nueva])), date(2026, 10, 2))
    assert cli.cmd_altas_cuit(conf, None) == 0
    csv = (conf.ruta("altas_cuit") / "2026-10.csv").read_text(encoding="utf-8").splitlines()
    assert len(csv) == 2 and csv[1].startswith("30799999999,juridica,HELADERIA POLO SUR SA")


def test_altas_sin_cambios(conf):
    actual, _ = parsear.juridicas(zip_padron(LINEAS), conf["padron"])
    assert enriquecer_cuit.altas(actual, actual) == []


def test_altas_sin_mes_anterior(conf):
    descargar.actualizar(conf, ClienteFalso(zip_padron(LINEAS)), date(2026, 10, 1))
    assert cli.cmd_altas_cuit(conf, None) == 1
