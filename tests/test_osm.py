"""Fuente OSM con una muestra real grabada por `radar record --fuente osm` (2026-10-20)."""

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from radar import config as cfg
from radar.fuentes import osm
from radar.geo import Limites

FIXTURE = Path(__file__).parent / "fixtures" / "osm" / "overpass_muestra.json"
HOY = date(2026, 10, 20)  # fecha de grabación del fixture


@pytest.fixture(scope="module")
def config():
    return cfg.cargar()


@pytest.fixture(scope="module")
def limites(config):
    return Limites(config)


@pytest.fixture(scope="module")
def crudo():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture()
def actual(crudo, config):
    return osm.parsear(copy.deepcopy(crudo), config)


def previo_de(actual: dict) -> dict:
    """Snapshot anterior idéntico al actual, en el formato que devuelve leer_snapshot."""
    return {k: {"hash": e["hash"], "principal": e["principal"], "lat": e["lat"], "lon": e["lon"],
                "nombre": e["nombre"]} for k, e in actual.items()}


def tipos(senales):
    return {s.id_externo: s.tipo_senal for s in senales}


def test_fixture_sin_datos_de_usuarios(crudo):
    assert all("user" not in e and "uid" not in e for e in crudo["elements"])


def test_parsear(actual):
    assert len(actual) > 400
    e = next(iter(actual.values()))
    assert set(e) >= {"tags", "principal", "lat", "lon", "version", "timestamp", "hash"}


def test_arranque_sin_snapshot_solo_creaciones_recientes(actual, config, limites):
    senales = osm.generar_senales(actual, None, None, config, limites, HOY)
    assert senales, "la muestra incluye elementos v1 recientes"
    assert {s.tipo_senal for s in senales} == {"creacion_osm"}
    for s in senales:
        assert s.fecha_registro >= "2026-09-20"
        assert s.partido in limites.geoms
        assert s.url.startswith("https://www.openstreetmap.org/")
        assert s.precision_fecha == "deteccion" and s.fecha_evento is None


def test_sin_cambios_no_hay_altas_ni_cambios(actual, config, limites):
    previo = previo_de(actual)
    senales = osm.generar_senales(actual, previo, sorted(limites.geoms), config, limites, HOY)
    assert {s.tipo_senal for s in senales} <= {"creacion_osm"}


def _viejo_con_rubro(actual, limites, clave="shop="):
    """Un elemento editado hace más de 30 días, dentro de la zona."""
    return next(k for k, e in actual.items() if e["version"] > 1 and e["principal"].startswith(clave)
                and e["timestamp"] < "2026-09-01" and e["nombre"] and limites.partido_de(e["lat"], e["lon"]))


def test_alta_desde_snapshot(actual, config, limites):
    oid = _viejo_con_rubro(actual, limites)
    previo = previo_de(actual)
    del previo[oid]
    senales = osm.generar_senales(actual, previo, sorted(limites.geoms), config, limites, HOY)
    assert tipos(senales)[f"osm:{oid}"] == "alta_osm"


def test_alta_en_partido_recien_activado_no_cuenta(actual, config, limites):
    oid = _viejo_con_rubro(actual, limites)
    previo = previo_de(actual)
    del previo[oid]
    partido = limites.partido_de(actual[oid]["lat"], actual[oid]["lon"])
    otros = [p for p in limites.geoms if p != partido]
    senales = osm.generar_senales(actual, previo, otros, config, limites, HOY)
    assert f"osm:{oid}" not in tipos(senales)


def test_local_vacio_que_pasa_a_tener_rubro(actual, config, limites):
    oid = _viejo_con_rubro(actual, limites)
    previo = previo_de(actual)
    previo[oid]["principal"] = "shop=vacant"
    senales = osm.generar_senales(actual, previo, sorted(limites.geoms), config, limites, HOY)
    s = next(s for s in senales if s.id_externo == f"osm:{oid}")
    assert s.tipo_senal == "cambio_osm" and "shop=vacant" in s.detalle


def test_cambio_de_nombre(actual, config, limites):
    oid = _viejo_con_rubro(actual, limites)
    previo = previo_de(actual)
    previo[oid]["nombre"] = "Comercio Anterior"
    senales = osm.generar_senales(actual, previo, sorted(limites.geoms), config, limites, HOY)
    assert tipos(senales)[f"osm:{oid}"] == "cambio_osm"


def test_nombre_igual_con_otras_tildes_no_es_cambio(actual, config, limites):
    oid = _viejo_con_rubro(actual, limites)
    previo = previo_de(actual)
    previo[oid]["nombre"] = actual[oid]["nombre"].upper()
    senales = osm.generar_senales(actual, previo, sorted(limites.geoms), config, limites, HOY)
    assert f"osm:{oid}" not in tipos(senales)


@pytest.mark.parametrize("tags,esperado", [
    ({"construction:shop": "clothes", "name": "Nueva Tienda"}, ("Indumentaria y calzado", None, "sin_fecha")),
    ({"shop": "bakery", "opening_date": "2026-11-15"}, ("Gastronomía", "2026-11-15", "exacta")),
    ({"planned:amenity": "cafe", "opening_date": "2026-12"}, ("Gastronomía", "2026-12-01", "inferida")),
])
def test_por_abrir(config, limites, tags, esperado):
    crudo = {"elements": [{"type": "node", "id": 1, "lat": -34.5106, "lon": -58.4920, "version": 3,
                           "timestamp": "2025-01-01T00:00:00Z", "tags": tags}]}
    actual = osm.parsear(crudo, config)
    [s] = osm.generar_senales(actual, None, None, config, limites, HOY)
    assert s.tipo_senal == "por_abrir_osm"
    assert (s.rubro, s.fecha_evento, s.precision_fecha) == esperado


def test_opening_date_pasada_no_es_por_abrir(config, limites):
    crudo = {"elements": [{"type": "node", "id": 1, "lat": -34.5106, "lon": -58.4920, "version": 3,
                           "timestamp": "2025-01-01T00:00:00Z", "tags": {"shop": "bakery", "opening_date": "2024-05-01"}}]}
    assert osm.generar_senales(osm.parsear(crudo, config), None, None, config, limites, HOY) == []


def test_fuera_de_zona_se_ignora(config, limites):
    crudo = {"elements": [{"type": "node", "id": 1, "lat": -31.6667, "lon": -63.8833, "version": 1,
                           "timestamp": "2026-10-19T00:00:00Z", "tags": {"shop": "clothes"}}]}  # Pilar, Córdoba
    assert osm.generar_senales(osm.parsear(crudo, config), None, None, config, limites, HOY) == []


def test_snapshot_ida_y_vuelta(actual, config, tmp_path):
    conf = cfg.Config(copy.deepcopy(dict(config)))
    conf["rutas"]["snapshots"] = str(tmp_path)
    oid = next(iter(actual))
    actual[oid]["nombre"] = "Con\ttab y\nsalto"
    osm.escribir_snapshot(conf, actual, ["Tigre"], "2026-10-20")
    meta, previo = osm.leer_snapshot(conf)
    assert meta == {"fecha": "2026-10-20", "partidos": ["Tigre"], "elementos": len(actual)}
    assert previo[oid]["nombre"] == "Con tab y salto"
    assert set(previo) == set(actual)


def test_respuesta_incompleta_no_pisa_snapshot(actual, config, tmp_path, monkeypatch, crudo):
    conf = cfg.Config(copy.deepcopy(dict(config)))
    conf["rutas"]["snapshots"] = str(tmp_path)
    osm.escribir_snapshot(conf, actual, sorted(Limites(conf).geoms), "2026-10-19")
    antes = (tmp_path / osm.ARCHIVO_SNAPSHOT).read_text()
    recortado = {"elements": crudo["elements"][: len(crudo["elements"]) // 2]}
    monkeypatch.setattr(osm, "descargar", lambda *a: copy.deepcopy(recortado))
    with pytest.raises(RuntimeError, match="incompleta"):
        osm.recolectar(conf, None)
    assert (tmp_path / osm.ARCHIVO_SNAPSHOT).read_text() == antes
