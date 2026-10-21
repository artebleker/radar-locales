"""Límites, punto-en-polígono y diccionario de localidades.

Usa data/ref/partidos.geojson y localidades.json reales (generados por `radar bootstrap`).
"""

import pytest

from radar import config as cfg
from radar import geo
from radar.texto import normalizar

CONFIG = cfg.cargar()


@pytest.fixture(scope="module")
def limites():
    return geo.Limites(CONFIG)


@pytest.mark.parametrize("lat,lon,esperado", [
    (-34.5106, -58.4920, "Vicente López"),     # Olivos, estación
    (-34.4708, -58.5131, "San Isidro"),        # San Isidro, catedral
    (-34.4176, -58.6750, "Tigre"),             # Nordelta
    (-34.4587, -58.9142, "Pilar"),             # Pilar centro
    (-34.3497, -58.7956, "Escobar"),           # Belén de Escobar
    (-34.5753, -58.5376, "San Martín"),        # San Martín centro
    (-34.6037, -58.3816, None),                # Obelisco, CABA: fuera de zona
    (-31.6667, -63.8833, None),                # Pilar, Córdoba: homónimo fuera de zona
])
def test_punto_en_poligono(limites, lat, lon, esperado):
    assert limites.partido_de(lat, lon) == esperado


def test_sin_coordenadas(limites):
    assert limites.partido_de(None, None) is None


def test_solo_partidos_activos(limites):
    activos = {p["nombre"] for p in CONFIG.partidos()}
    assert set(limites.geoms) == activos


def test_poligono_de_relacion_une_ways_sueltos():
    # Un cuadrado partido en dos ways abiertos, como vienen en las relaciones de OSM.
    p = lambda lon, lat: {"lon": lon, "lat": lat}  # noqa: E731
    rel = {"id": 1, "members": [
        {"type": "way", "role": "outer", "geometry": [p(0, 0), p(1, 0), p(1, 1)]},
        {"type": "way", "role": "outer", "geometry": [p(1, 1), p(0, 1), p(0, 0)]},
        {"type": "node", "role": "admin_centre", "lat": 0.5, "lon": 0.5},
    ]}
    assert geo.poligono_de_relacion(rel).area == pytest.approx(1.0)


def test_localidades_conocidas():
    loc = geo.cargar_localidades(CONFIG)
    for nombre, partido in [("Olivos", "Vicente López"), ("Martínez", "San Isidro"),
                            ("Nordelta", "Tigre"), ("Pilar", "Pilar")]:
        assert partido in loc[normalizar(nombre)], nombre


def test_normalizar():
    assert normalizar("  Martínez — SRL. ") == "martinez srl"
    assert normalizar("JOSÉ C. PAZ") == "jose c paz"


@pytest.mark.parametrize("nombre,partido", [
    ("Villa Ballester", "San Martín"), ("José León Suárez", "San Martín"), ("Villa Adelina", "San Isidro"),
])
def test_alias_de_prensa(nombre, partido):
    assert partido in geo.cargar_localidades(CONFIG)[normalizar(nombre)]


def test_alias_conservador():
    assert geo._alias("villa lynch") == []                      # «Lynch» solo es demasiado ambiguo
    assert geo._alias("villa ballester noreste") == ["villa ballester", "ballester noreste"]
