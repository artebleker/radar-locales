"""Directorios de shoppings: un test por sitio con su primera página real (grabada 2026-10-20)."""

import copy
import re
from pathlib import Path

import pytest

from radar import config as cfg
from radar.fuentes import directorios as d

CONFIG = cfg.cargar()
FIX = Path(__file__).parent / "fixtures" / "directorios"
SITIOS = {s["id"]: s for s in CONFIG["directorios"]["sitios"]}
PATRON_PA = re.compile(CONFIG["directorios"]["patron_por_abrir"], re.IGNORECASE)


def parsear(sitio_id, html=None):
    sitio = SITIOS[sitio_id]
    pagina = sitio["paginas"][0]
    html = html if html is not None else (FIX / f"{sitio_id}.html").read_text(encoding="utf-8")
    return d.parsear_pagina(html, pagina["url"].format(n=0), sitio, pagina, PATRON_PA)


@pytest.mark.parametrize("sitio_id,minimo,conocida", [
    ("unicenter", 10, "5 A Sec"),
    ("palmasdelpilar", 10, "47 Street"),
    ("portalescobar", 10, "Al Mundo"),
    ("factorysanmartin", 10, "Al Mundo"),
    ("champagnat", 40, "Burger King"),
    ("remeros", 40, "Aroma"),
    ("soleil", 5, "47 Street"),
    ("tortugas", 5, "Adidas"),
])
def test_parser_por_sitio(sitio_id, minimo, conocida):
    tiendas = parsear(sitio_id)
    assert len(tiendas) >= minimo
    nombres = {t["nombre"] for t in tiendas.values()}
    assert conocida in nombres
    assert not {n for n in nombres if n.lower() in {"ver más", "ir a perfil", ""}}
    assert all(t["url"].startswith("http") for t in tiendas.values())


def test_tortugas_excluye_slugs_de_categoria():
    assert not set(parsear("tortugas")) & set(SITIOS["tortugas"]["excluir_ids"])


def test_rubro_de_la_pagina_de_categoria():
    assert {t["rubro"] for t in parsear("tortugas").values()} == {"Indumentaria y calzado"}


def test_proximamente_en_la_tarjeta():
    html = ('<div><div><div class="card"><span class="views-field-title">Nueva Marca</span>'
            '<span>Próximamente</span><a href="https://shoppingscencosud.com.ar/unicenter/tiendas/nueva-marca">'
            'Ir a perfil</a></div></div></div>')
    t = parsear("unicenter", html)["nueva-marca"]
    assert t["nombre"] == "Nueva Marca" and t["por_abrir"]


def _senales(tiendas, previo):
    meta = {"fecha": "2026-10-19"} if previo is not None else None
    return d.generar_senales(SITIOS["unicenter"], tiendas, meta, previo, "San Isidro", "2026-10-20", CONFIG)


def test_tienda_nueva_respecto_del_snapshot():
    tiendas = parsear("unicenter")
    previo = {k: {"nombre": v["nombre"], "rubro": v["rubro"]} for k, v in tiendas.items()}
    nueva = next(iter(previo))
    del previo[nueva]
    [s] = _senales(tiendas, previo)
    assert s.tipo_senal == "alta_directorio" and s.id_externo == f"dir:unicenter:{nueva}"
    assert s.partido == "San Isidro" and "2026-10-19" in s.detalle


def test_primer_relevamiento_no_genera_altas():
    assert _senales(parsear("unicenter"), None) == []


def test_snapshot_y_respuesta_incompleta(tmp_path, monkeypatch):
    conf = cfg.Config(copy.deepcopy(dict(CONFIG)))
    conf["rutas"]["snapshots"] = str(tmp_path)
    conf["directorios"]["sitios"] = [SITIOS["remeros"]]
    tiendas = parsear("remeros")
    d.escribir_snapshot(conf, "remeros", tiendas, "2026-10-19")
    meta, previo = d.leer_snapshot(conf, "remeros")
    assert meta["tiendas"] == len(tiendas) and set(previo) == set(tiendas)

    mitad = dict(list(tiendas.items())[: len(tiendas) // 3])
    monkeypatch.setattr(d, "descargar_sitio", lambda *a: mitad)
    with pytest.raises(RuntimeError, match="todos los directorios fallaron"):
        d.recolectar(conf, None)
    assert d.leer_snapshot(conf, "remeros")[1] == previo  # no se pisó
