"""Deduplicación, puntaje, estado, historial e ids estables."""

import copy

import pytest

from radar import config as cfg
from radar import dedupe, historial, publicar, scoring
from radar.modelos import Senal

CONFIG = cfg.cargar()
HOY = "2026-10-20"


def senal(**kw):
    base = dict(fuente="osm", tipo_senal="creacion_osm", nombre="Café Uno", rubro="Gastronomía",
                partido="San Isidro", detectado_el=HOY, url="https://x", lat=-34.4700, lon=-58.5100,
                precision_fecha="deteccion", id_externo="osm:node/1")
    base.update(kw)
    return Senal(**base)


def grupos(*senales):
    return dedupe.agrupar(list(senales), CONFIG)


# --- dedupe ------------------------------------------------------------------
def test_nombre_normalizado_quita_genericos():
    assert dedupe.nombre_normalizado("Supermercados Día S.R.L.", CONFIG) == "dia"
    assert dedupe.nombre_normalizado("Local", CONFIG) == "local"  # si queda vacío, se conserva


def test_fusiona_mismo_nombre_cerca():
    a = senal()
    b = senal(fuente="sucursales", tipo_senal="alta_sucursal", nombre="CAFE UNO Sucursal",
              lat=-34.4705, lon=-58.5102, id_externo="suc:x:1")
    assert len(grupos(a, b)) == 1


def test_no_fusiona_mismo_nombre_lejos():
    a = senal()
    b = senal(fuente="sucursales", tipo_senal="alta_sucursal", lat=-34.4800, lon=-58.5100, id_externo="suc:x:1")
    assert len(grupos(a, b)) == 2  # ~1,1 km: dos sucursales distintas


def test_no_fusiona_nombres_distintos_en_el_mismo_lugar():
    assert len(grupos(senal(), senal(nombre="Ferretería Dos", id_externo="osm:node/2"))) == 2


def test_nota_sin_coordenadas_se_fusiona_con_lugar_unico():
    nota = senal(fuente="medios_rss", tipo_senal="nota_prensa", lat=None, lon=None, id_externo="nota:1")
    assert len(grupos(senal(), nota)) == 1


def test_nota_sin_coordenadas_ambigua_no_se_fusiona():
    nota = senal(fuente="medios_rss", tipo_senal="nota_prensa", nombre="Día", lat=None, lon=None, id_externo="nota:1")
    s1 = senal(fuente="sucursales", tipo_senal="alta_sucursal", nombre="Supermercados Día", id_externo="suc:dia:1")
    s2 = senal(fuente="sucursales", tipo_senal="alta_sucursal", nombre="Supermercados Día",
               lat=-34.4900, lon=-58.5300, id_externo="suc:dia:2")
    assert len(grupos(nota, s1, s2)) == 3


def test_sin_nombre_no_se_fusiona():
    assert len(grupos(senal(nombre=None), senal(nombre=None, id_externo="osm:node/2"))) == 2


def test_mismo_id_externo_siempre_se_fusiona():
    assert len(grupos(senal(), senal(tipo_senal="cambio_osm", nombre="Otro"))) == 1


# --- puntaje y estado --------------------------------------------------------------
def test_puntaje_osm_solo_es_bajo():
    assert scoring.puntuar([senal()], CONFIG)[1] == "baja"


def test_sucursal_nueva_es_alta():
    assert scoring.puntuar([senal(tipo_senal="alta_sucursal", fuente="sucursales")], CONFIG)[1] == "alta"


def test_dos_fuentes_suben_la_confianza():
    solo = scoring.puntuar([senal()], CONFIG)[0]
    nota = senal(fuente="medios_rss", tipo_senal="nota_prensa", id_externo="nota:1")
    juntas = scoring.puntuar([senal(), nota], CONFIG)[0]
    assert juntas >= solo + CONFIG["puntaje"]["bonos"]["fuente_adicional"]


def test_penalizaciones_de_nota():
    nota = senal(fuente="medios_rss", tipo_senal="nota_prensa", nombre=None,
                 extra={"penalizaciones": ["partido_dudoso", "exclusion_debil:municipio"]})
    puntaje, confianza, motivos = scoring.puntuar([nota], CONFIG)
    assert confianza == "baja" and any("exclusion_debil" in m for m in motivos)


@pytest.mark.parametrize("senales,esperado", [
    ([senal()], "detectado"),
    ([senal(tipo_senal="por_abrir_osm")], "por_abrir"),
    ([senal(fecha_evento="2026-11-01", precision_fecha="exacta")], "por_abrir"),
    ([senal(fecha_evento="2026-10-01", precision_fecha="exacta")], "abrio"),
    ([senal(extra={"estado_sugerido": "abrio"})], "abrio"),
    ([senal(extra={"estado_sugerido": "por_abrir"})], "por_abrir"),
])
def test_estado(senales, esperado):
    assert scoring.estado(senales, HOY) == esperado


# --- historial e ids -----------------------------------------------------------------
@pytest.fixture()
def conf(tmp_path):
    c = cfg.Config(copy.deepcopy(dict(CONFIG)))
    c["rutas"]["historial"] = str(tmp_path / "historial")
    c["rutas"]["site_data"] = str(tmp_path / "site")
    return c


def test_historial_conserva_primera_deteccion(conf):
    e = historial.actualizar(conf, {}, [senal()], "2026-10-01")
    historial.guardar(conf, e, "2026-10-01")
    e = historial.actualizar(conf, historial.cargar(conf), [senal(nombre="Café Uno Renombrado")], "2026-10-20")
    [entrada] = e.values()
    assert (entrada["primera"], entrada["ultima"]) == ("2026-10-01", "2026-10-20")
    assert entrada["senal"]["nombre"] == "Café Uno Renombrado"


def test_historial_archiva_meses_viejos(conf):
    e = historial.actualizar(conf, {}, [senal()], "2026-01-10")
    historial.guardar(conf, e, "2026-10-20")
    base = conf.ruta("historial")
    assert not list(base.glob("senales-2026-01.jsonl")) and (base / "archivo" / "senales-2026-01.jsonl.gz").exists()


def test_id_estable_entre_corridas_y_al_sumar_senales():
    a = (senal(), "2026-10-01", "2026-10-20")
    [c1] = publicar.unificar([a], CONFIG, HOY)
    nota = (senal(fuente="medios_rss", tipo_senal="nota_prensa", lat=None, lon=None, id_externo="nota:9"),
            "2026-10-15", "2026-10-20")
    [c2] = publicar.unificar([a, nota], CONFIG, HOY)
    assert c1["id"] == c2["id"] and c2["fuentes"] == ["medios_rss", "osm"]


def test_fecha_estimada_de_nota_sin_fecha_anunciada():
    nota = senal(fuente="medios_rss", tipo_senal="nota_prensa", fecha_publicacion="2026-09-25",
                 extra={"estado_sugerido": "abrio"})
    [c] = publicar.unificar([(nota, HOY, HOY)], CONFIG, HOY)
    assert (c["fecha_estimada"], c["precision_fecha"], c["origen_fecha"]) == ("2026-09-25", "inferida", "publicacion")


def test_publicar_genera_json(conf):
    import json
    cands = publicar.unificar([(senal(), HOY, HOY)], conf, HOY)
    rc, re_ = publicar.publicar(conf, cands, [{"fuente": "osm", "ok": True, "senales": 1}], conf.ahora())
    datos = json.loads(rc.read_text())
    assert len(datos["candidatos"]) == 1 and json.loads(re_.read_text())["arca"]["estado"] == "verificacion_manual_enlazada"


def test_version_publicada_y_en_readme(conf):
    import json
    from pathlib import Path
    from radar import __version__
    _, re_ = publicar.publicar(conf, [], [{"fuente": "osm", "ok": True, "senales": 0}], conf.ahora())
    assert json.loads(re_.read_text())["version"] == __version__
    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    assert f"**Versión:** {__version__}" in readme
