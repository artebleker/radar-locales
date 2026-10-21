"""Cruce de candidatos con el padrón y publicación sin datos de personas físicas. Datos sintéticos."""

import copy
import json

import pytest

from radar import config as cfg
from radar import enriquecer_cuit as ec
from radar import publicar
from radar.padron.parsear import Indice

CONFIG = cfg.cargar()

FILAS = [
    {"cuit": "30711111111", "razon_social": "CAFETERIA LUNA DEL NORTE SRL", "iva": "AC", "empleador": "S",
     "domicilio_calle": "Avenida Italia", "domicilio_altura": "1299", "localidad": "Tigre"},
    {"cuit": "33722222222", "razon_social": "FERRETERIA EL TORNILLO SA", "iva": "AC", "empleador": "N",
     "domicilio_calle": "Belgrano", "domicilio_altura": "450", "localidad": "Martinez"},
    {"cuit": "30733333333", "razon_social": "PANADERIA AURORA SRL", "domicilio_calle": "Belgrano",
     "domicilio_altura": "450", "localidad": "Martinez"},
    {"cuit": "30744444444", "razon_social": "FORTALEZA SA", "localidad": "Rosario"},
    {"cuit": "30755555555", "razon_social": "FORTALEZA SRL", "localidad": "Pilar"},
    {"cuit": "30766666666", "razon_social": "LEO SA"},
    {"cuit": "30777777777", "razon_social": "CASTIELLO SA"},
    {"cuit": "30788888888", "razon_social": "JUNIOR SAS"},
    {"cuit": "30799999999", "razon_social": "ALTIO STUDIO S. R. L."},
]


@pytest.fixture(scope="module")
def indice():
    return Indice(FILAS, CONFIG)


def cand(**kw):
    base = {"id": "c1", "nombre": None, "direccion": None, "partido": None, "localidad": None}
    base.update(kw)
    return base


def test_direccion_y_nombre_es_alta(indice):
    r = ec.cruzar(cand(nombre="Cafetería Luna del Norte", direccion="Avenida Italia 1299", partido="Tigre"), indice, CONFIG)
    assert (r["cuit"], r["coincidencia"], r["confianza_cuit"]) == ("30711111111", "direccion_y_nombre", "alta")


def test_solo_direccion_exacta_es_media(indice):
    r = ec.cruzar(cand(direccion="Av. Italia 1299"), indice, CONFIG)
    assert r["coincidencia"] is None  # «Av.» ≠ «Avenida»: exacta quiere decir exacta
    r = ec.cruzar(cand(direccion="Avenida Italia 1299"), indice, CONFIG)
    assert (r["cuit"], r["coincidencia"], r["confianza_cuit"]) == ("30711111111", "direccion_exacta", "media")


def test_solo_nombre_es_baja(indice):
    r = ec.cruzar(cand(nombre="Ferretería El Tornillo"), indice, CONFIG)
    assert (r["cuit"], r["coincidencia"], r["confianza_cuit"]) == ("33722222222", "nombre_similar", "baja")
    assert r["razon_social_cuit"] == "FERRETERIA EL TORNILLO SA" and r["condicion_iva"] == "AC"


def test_nombre_similar_sobre_el_umbral(indice):
    r = ec.cruzar(cand(nombre="Luna del Norte Cafetería"), indice, CONFIG)
    assert r["cuit"] == "30711111111" and r["coincidencia"] == "nombre_similar"


def test_dos_sociedades_en_la_misma_direccion_es_ambiguo(indice):
    r = ec.cruzar(cand(direccion="Belgrano 450"), indice, CONFIG)
    assert r["cuit"] is None and r["coincidencia"] == "ambigua" and r["cuits_posibles"] == 2


def test_direccion_y_nombre_desempatan(indice):
    r = ec.cruzar(cand(nombre="Panadería Aurora", direccion="Belgrano 450"), indice, CONFIG)
    assert (r["cuit"], r["confianza_cuit"]) == ("30733333333", "alta")


def test_direccion_y_nombre_contradictorios_no_asigna(indice):
    r = ec.cruzar(cand(nombre="Ferretería El Tornillo", direccion="Avenida Italia 1299"), indice, CONFIG)
    assert r["cuit"] is None and r["coincidencia"] == "ambigua"


def test_nombre_ambiguo_sin_asignacion(indice):
    r = ec.cruzar(cand(nombre="Fortaleza"), indice, CONFIG)
    assert r["cuit"] is None and r["coincidencia"] == "ambigua"


def test_localidad_desambigua(indice):
    localidades = {"pilar": ["Pilar"], "del viso": ["Pilar"]}
    r = ec.cruzar(cand(nombre="Fortaleza", partido="Pilar"), indice, CONFIG, localidades=localidades)
    assert r["cuit"] == "30755555555"


def test_nombre_corto_no_se_cruza(indice):
    assert ec.cruzar(cand(nombre="Leo"), indice, CONFIG)["cuit"] is None


def test_sin_coincidencia(indice):
    assert ec.cruzar(cand(nombre="Kiosco Inexistente"), indice, CONFIG) == dict.fromkeys(ec.CAMPOS)


def test_alta_reciente(indice):
    r = ec.cruzar(cand(nombre="Ferretería El Tornillo"), indice, CONFIG, cuits_nuevos={"33722222222"})
    assert r["cuit_alta_reciente"] is True


def test_enriquecer_no_modifica_el_puntaje(indice):
    c = cand(nombre="Ferretería El Tornillo", puntaje=25, confianza="baja")
    assert ec.enriquecer([c], indice, CONFIG) == 1
    assert (c["puntaje"], c["confianza"]) == (25, "baja")


def test_indice_de_personas_fisicas_no_existe():
    # Aunque una persona física llegara al índice, nunca se asigna su CUIT.
    indice = Indice([{"cuit": "20123456789", "razon_social": "PEREZ JUAN HELADOS"}], CONFIG)
    assert ec.cruzar(cand(nombre="Perez Juan Helados"), indice, CONFIG)["cuit"] is None


def test_publicacion_sin_datos_de_personas_fisicas(tmp_path):
    conf = cfg.Config(copy.deepcopy(dict(CONFIG)))
    conf["rutas"]["site_data"] = str(tmp_path)
    comun = {"vigente": True, "fecha_ventana": "2026-10-20", "estado": "detectado", "confianza": "baja"}
    juridica = {**comun, "id": "a", "cuit": "30711111111", "razon_social_cuit": "LUNA SRL"}
    fisica = {**comun, "id": "b", "cuit": "20123456789", "razon_social_cuit": "PEREZ JUAN",
              "condicion_iva": "AC", "empleador": "N"}
    rc, _ = publicar.publicar(conf, [juridica, fisica], [], conf.ahora())
    texto = rc.read_text(encoding="utf-8")
    assert "20123456789" not in texto and "PEREZ" not in texto
    publicados = {c["id"]: c for c in json.loads(texto)["candidatos"]}
    assert publicados["a"]["cuit"] == "30711111111" and publicados["b"]["cuit"] is None


def test_razon_social_contenida_en_el_candidato_no_alcanza(indice):
    assert ec.cruzar(cand(nombre="Cucuza Castiello"), indice, CONFIG)["cuit"] is None


def test_una_palabra_generica_no_se_cruza(indice):
    assert ec.cruzar(cand(nombre="Junior"), indice, CONFIG)["cuit"] is None


def test_parecido_de_letras_no_alcanza(indice):
    assert ec.cruzar(cand(nombre="Ático Studios"), indice, CONFIG)["cuit"] is None
