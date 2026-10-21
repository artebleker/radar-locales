"""Límites de partidos (desde relaciones OSM), punto-en-polígono y diccionario de localidades."""

from __future__ import annotations

import json
import re
import logging
from pathlib import Path

import yaml
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import polygonize, unary_union
from shapely.prepared import prep

from . import overpass
from .texto import normalizar

log = logging.getLogger(__name__)

ARCHIVO_LIMITES = "partidos.geojson"
ARCHIVO_LOCALIDADES = "localidades.json"
ARCHIVO_CORRECCIONES = "localidades_correcciones.yaml"
OFFSET_AREA = 3_600_000_000  # id de área Overpass = id de relación + 3 600 000 000


# --- límites -----------------------------------------------------------------
def poligono_de_relacion(rel: dict):
    """Arma el (multi)polígono de una relación con 'out geom' uniendo sus ways outer/inner."""
    lineas = {"outer": [], "inner": []}
    for m in rel.get("members", []):
        if m.get("type") != "way" or "geometry" not in m:
            continue
        rol = "inner" if m.get("role") == "inner" else "outer"
        coords = [(p["lon"], p["lat"]) for p in m["geometry"] if p]
        if len(coords) >= 2:
            lineas[rol].append(LineString(coords))
    exterior = unary_union(list(polygonize(unary_union(lineas["outer"]))))
    if lineas["inner"]:
        exterior = exterior.difference(unary_union(list(polygonize(unary_union(lineas["inner"])))))
    if exterior.is_empty:
        raise ValueError(f"relación {rel.get('id')}: no se pudo cerrar el polígono")
    return exterior


def descargar_limites(config, cliente) -> list[dict]:
    """Descarga y verifica los límites de todos los partidos configurados (activos o no)."""
    partidos = config.partidos(solo_activos=False)
    ids = ",".join(str(p["relacion"]) for p in partidos)
    q = f"[out:json][timeout:{config['overpass']['timeout_query_s']}];rel(id:{ids});out geom;"
    datos = overpass.consultar(cliente, config, q, ttl=7 * 86400)
    por_id = {e["id"]: e for e in datos["elements"] if e["type"] == "relation"}

    nivel = str(config["geo"]["admin_level_partido"])
    tol = config["geo"]["simplificar_grados"]
    features = []
    for p in partidos:
        rel = por_id.get(p["relacion"])
        if rel is None:
            raise RuntimeError(f"{p['nombre']}: la relación {p['relacion']} no existe en OSM")
        tags = rel.get("tags", {})
        # Verificación de identidad: si OSM cambió nombre o nivel, se frena en vez de usar un límite equivocado.
        if tags.get("name") != p["osm_nombre"] or tags.get("admin_level") != nivel:
            raise RuntimeError(
                f"{p['nombre']}: relación {p['relacion']} tiene name={tags.get('name')!r} "
                f"admin_level={tags.get('admin_level')!r}; se esperaba {p['osm_nombre']!r} nivel {nivel}")
        geom = poligono_de_relacion(rel).simplify(tol, preserve_topology=True)
        features.append({
            "type": "Feature",
            "properties": {"partido": p["nombre"], "relacion": p["relacion"],
                           "osm_nombre": tags["name"], "wikidata": tags.get("wikidata")},
            "geometry": mapping(geom),
        })
    return features


def guardar_limites(config, features: list[dict]) -> Path:
    ruta = config.ruta("ref") / ARCHIVO_LIMITES
    fc = {"type": "FeatureCollection",
          "attribution": "© colaboradores de OpenStreetMap, ODbL", "features": features}
    ruta.write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return ruta


class Limites:
    """Punto-en-polígono sobre los partidos activos."""

    def __init__(self, config, solo_activos: bool = True):
        activos = {p["nombre"] for p in config.partidos(solo_activos)}
        fc = json.loads((config.ruta("ref") / ARCHIVO_LIMITES).read_text(encoding="utf-8"))
        self.geoms = {f["properties"]["partido"]: shape(f["geometry"])
                      for f in fc["features"] if f["properties"]["partido"] in activos}
        self._prep = {n: prep(g) for n, g in self.geoms.items()}
        self.relaciones = {f["properties"]["partido"]: f["properties"]["relacion"] for f in fc["features"]}

    def partido_de(self, lat: float | None, lon: float | None) -> str | None:
        if lat is None or lon is None:
            return None
        pt = Point(lon, lat)
        for nombre, g in self._prep.items():
            if g.contains(pt):
                return nombre
        return None

    def bbox(self) -> tuple[float, float, float, float]:
        """(sur, oeste, norte, este) de todos los partidos activos, en el orden de Overpass."""
        o, s, e, n = unary_union(list(self.geoms.values())).bounds
        return s, o, n, e


# --- localidades -------------------------------------------------------------
def descargar_localidades(config, cliente, limites: Limites) -> dict:
    """Lugares place=* dentro de los partidos, asignados a su partido por punto-en-polígono."""
    tipos = "|".join(config["geo"]["tipos_place"])
    areas = "".join(f"area(id:{OFFSET_AREA + r});" for r in limites.relaciones.values())
    q = (f"[out:json][timeout:{config['overpass']['timeout_query_s']}];({areas})->.z;"
         f'nwr(area.z)["place"~"^({tipos})$"]["name"];out tags center;')
    datos = overpass.consultar(cliente, config, q, ttl=7 * 86400)

    dicc: dict[str, dict] = {}
    for e in datos["elements"]:
        lat = e.get("lat", e.get("center", {}).get("lat"))
        lon = e.get("lon", e.get("center", {}).get("lon"))
        partido = limites.partido_de(lat, lon)
        if not partido:
            continue
        nombre = e["tags"]["name"]
        ent = dicc.setdefault(normalizar(nombre), {"nombre": nombre, "partidos": [], "fuentes": []})
        if partido not in ent["partidos"]:
            ent["partidos"].append(partido)
        ent["fuentes"].append(f"osm:{e['type']}/{e['id']}:{e['tags']['place']}")
    # Alias de cómo escribe la prensa: «Villa Ballester Noreste» → «Villa Ballester»,
    # «Villa José León Suárez» → «José León Suárez». No pisan nombres existentes.
    for clave, ent in list(dicc.items()):
        for alias in _alias(clave):
            if alias not in dicc:
                dicc[alias] = {"nombre": ent["nombre"], "partidos": list(ent["partidos"]),
                               "fuentes": [f"alias:{clave}"]}
            elif dicc[alias]["fuentes"][0].startswith("alias:"):
                for p in ent["partidos"]:
                    if p not in dicc[alias]["partidos"]:
                        dicc[alias]["partidos"].append(p)
    # El nombre corto de cada partido también ubica (ej. «Pilar», «Escobar»).
    for p in config.partidos(solo_activos=False):
        if p["nombre"] in limites.geoms:
            ent = dicc.setdefault(normalizar(p["nombre"]), {"nombre": p["nombre"], "partidos": [], "fuentes": []})
            if p["nombre"] not in ent["partidos"]:
                ent["partidos"].append(p["nombre"])
            ent["fuentes"].append("config:partido")
    return dict(sorted(dicc.items()))


_ORIENTACION = re.compile(r" (norte|sur|este|oeste|noreste|noroeste|sudeste|sudoeste|sureste|suroeste|centro)$")


def _alias(clave: str) -> list[str]:
    """Variantes normalizadas de un nombre de localidad, solo si quedan al menos dos palabras."""
    alias = []
    base = _ORIENTACION.sub("", clave)
    if base != clave and len(base.split()) >= 2:
        alias.append(base)
    for c in {clave, base}:
        if c.startswith("villa ") and len(c.split()) >= 3:
            alias.append(c[len("villa "):])
    return alias


def guardar_localidades(config, dicc: dict) -> Path:
    ruta = config.ruta("ref") / ARCHIVO_LOCALIDADES
    ruta.write_text(json.dumps(dicc, ensure_ascii=False, indent=1), encoding="utf-8")
    corr = config.ruta("ref") / ARCHIVO_CORRECCIONES
    if not corr.exists():
        corr.write_text(
            "# Correcciones manuales al diccionario localidad → partido (se aplican sobre localidades.json).\n"
            "# agregar: {\"Nombre\": \"Partido\"}   quitar: [\"Nombre\"]\n"
            "agregar: {}\nquitar: []\n", encoding="utf-8")
    return ruta


def cargar_localidades(config) -> dict[str, list[str]]:
    """Diccionario normalizado nombre → partidos, con correcciones manuales aplicadas."""
    ref = config.ruta("ref")
    base = json.loads((ref / ARCHIVO_LOCALIDADES).read_text(encoding="utf-8"))
    dicc = {k: list(v["partidos"]) for k, v in base.items()}
    corr_ruta = ref / ARCHIVO_CORRECCIONES
    if corr_ruta.exists():
        corr = yaml.safe_load(corr_ruta.read_text(encoding="utf-8")) or {}
        for nombre in corr.get("quitar") or []:
            dicc.pop(normalizar(nombre), None)
        for nombre, partido in (corr.get("agregar") or {}).items():
            dicc[normalizar(nombre)] = [partido] if isinstance(partido, str) else list(partido)
    return dicc
