"""Sucursales de cadenas: cada adaptador con la primera respuesta real grabada (2026-10-20)."""

import re
from pathlib import Path

import pytest

from radar import config as cfg
from radar.fuentes import sucursales as su
from radar.geo import Limites

CONFIG = cfg.cargar()
FIX = Path(__file__).parent / "fixtures" / "sucursales"
CADENAS = {c["id"]: c for c in CONFIG["sucursales"]["cadenas"]}


class Respuesta:
    def __init__(self, texto):
        self.text = texto

    def json(self):
        import json
        return json.loads(self.text)


class ClienteFalso:
    """Devuelve el fixture en el primer pedido de cada consulta; las páginas siguientes de VTEX vienen vacías."""

    def __init__(self, cadena_id):
        ext = "html" if CADENAS[cadena_id]["tipo"] == "next_data" else "json"
        self.texto = (FIX / f"{cadena_id}.{ext}").read_text(encoding="utf-8")
        self.pedidos = []

    def pedir(self, url, **kw):
        self.pedidos.append(url)
        if "pickup-points" in url and "page=1&" not in url:
            return Respuesta('{"items": []}')
        return Respuesta(self.texto)


@pytest.fixture(scope="module")
def limites():
    return Limites(CONFIG)


@pytest.mark.parametrize("cadena_id,minimo_en_zona", [
    ("fravega", 5), ("dia", 5), ("carrefour", 5), ("easy", 2), ("blaisten", 1),
    ("simplicity", 2), ("bonafide", 5), ("havanna", 5),
])
def test_adaptador(cadena_id, minimo_en_zona, limites):
    cadena = CADENAS[cadena_id]
    crudo = su.ADAPTADORES[cadena["tipo"]](CONFIG, ClienteFalso(cadena_id), cadena, limites)
    zona = su.en_zona(crudo, limites)
    assert len(zona) >= minimo_en_zona
    for t in zona.values():
        assert t["partido"] in limites.geoms
        assert -35 < t["lat"] < -34 and -59.2 < t["lon"] < -58.3
        assert t["nombre"].startswith(cadena["nombre"])


def test_vtex_consulta_desde_cada_partido(limites):
    cliente = ClienteFalso("dia")
    su.vtex_pickup(CONFIG, cliente, CADENAS["dia"], limites)
    centros = {u.split("geoCoordinates=")[1].split("&")[0] for u in cliente.pedidos}
    assert len(centros) == len(limites.geoms)


def test_fuera_de_zona_se_descarta(limites):
    crudo = su.next_data(CONFIG, ClienteFalso("fravega"), CADENAS["fravega"], limites)
    assert len(su.en_zona(crudo, limites)) < len(crudo)  # Frávega publica todo el país


def _tiendas(limites):
    return su.en_zona(su.havanna(CONFIG, ClienteFalso("havanna"), CADENAS["havanna"], limites), limites)


def test_sucursal_nueva(limites):
    tiendas = _tiendas(limites)
    previo = {k: {"nombre": v["nombre"], "extra": v["partido"]} for k, v in tiendas.items()}
    nueva = next(iter(previo))
    del previo[nueva]
    [s] = su.generar_senales(CADENAS["havanna"], tiendas, {"fecha": "2026-10-19"}, previo, "2026-10-20")
    assert s.tipo_senal == "alta_sucursal" and s.id_externo == f"suc:havanna:{nueva}"
    assert s.rubro == "Gastronomía" and s.lat is not None


def test_primer_relevamiento_sin_altas(limites):
    assert su.generar_senales(CADENAS["havanna"], _tiendas(limites), None, None, "2026-10-20") == []


def test_fixtures_sin_contactos():
    for f in FIX.iterdir():
        assert not re.search(r'"[a-z_]*(email|telefono|contactphone)"', f.read_text(encoding="utf-8"), re.IGNORECASE)
