"""Fuente principal de volumen: comercios de OpenStreetMap vía Overpass.

Una sola consulta diaria para todos los partidos activos (`out meta center`). Se compara con el
snapshot anterior (texto plano, una línea por elemento, para que git guarde solo las diferencias).

Señales: creacion_osm, alta_osm, por_abrir_osm, cambio_osm y, opcional, baja_osm.
Nuevo en OSM no prueba nuevo en la realidad (alguien pudo mapear un local viejo): confianza baja.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta

from .. import overpass
from ..geo import OFFSET_AREA, Limites
from ..modelos import Senal
from ..rubros import clasificar_osm
from ..texto import normalizar

NOMBRE = "osm"
TIPO = "listado"
URL = "https://www.openstreetmap.org"
LICENCIA = "ODbL — © colaboradores de OpenStreetMap"
CONFIANZA_BASE = "baja"

ARCHIVO_SNAPSHOT = "osm.tsv"
CLAVES_PRINCIPALES = ("shop", "amenity", "leisure")
MINIMO_RELATIVO = 0.9  # si la consulta trae menos del 90 % del snapshot anterior, se asume falla

log = logging.getLogger(__name__)


# --- consulta ----------------------------------------------------------------
def _valores(config, clave: str) -> list[str]:
    vals = set()
    for reglas in config["rubros"].values():
        vals.update((reglas.get("osm") or {}).get(clave, []))
    return sorted(vals)


def construir_query(config, limites: Limites) -> str:
    areas = "".join(f"area(id:{OFFSET_AREA + r});" for p, r in limites.relaciones.items() if p in limites.geoms)
    amen = "|".join(_valores(config, "amenity"))
    leis = "|".join(_valores(config, "leisure"))
    partes = ['nwr(area.z)["shop"];',
              f'nwr(area.z)["amenity"~"^({amen})$"];',
              f'nwr(area.z)["leisure"~"^({leis})$"];']
    for pre in config["osm"]["prefijos_por_abrir"]:
        partes.append(f'nwr(area.z)["{pre}:shop"];')
        partes.append(f'nwr(area.z)["{pre}:amenity"~"^({amen})$"];')
    t = config["overpass"]["timeout_query_s"]
    return f"[out:json][timeout:{t}];({areas})->.z;({''.join(partes)});out meta center qt;"


# --- parseo ------------------------------------------------------------------
def principal(tags: dict, config) -> str | None:
    """Etiqueta que define el rubro, ej. 'shop=clothes' o 'construction:shop=clothes'."""
    for k in CLAVES_PRINCIPALES:
        if k in tags:
            return f"{k}={tags[k]}"
    for pre in config["osm"]["prefijos_por_abrir"]:
        for k in ("shop", "amenity"):
            if f"{pre}:{k}" in tags:
                return f"{pre}:{k}={tags[f'{pre}:{k}']}"
    return None


def _hash_tags(tags: dict) -> str:
    return hashlib.sha1(json.dumps(tags, sort_keys=True).encode()).hexdigest()[:10]


def parsear(datos: dict, config) -> dict[str, dict]:
    """Elementos de Overpass → {"node/123": {...}}. No se guardan usuario ni uid de OSM."""
    elementos = {}
    for e in datos["elements"]:
        tags = e.get("tags") or {}
        p = principal(tags, config)
        if not p:
            continue
        lat = e.get("lat", (e.get("center") or {}).get("lat"))
        lon = e.get("lon", (e.get("center") or {}).get("lon"))
        if lat is None:
            continue
        elementos[f"{e['type']}/{e['id']}"] = {
            "tags": tags, "principal": p, "nombre": tags.get("name") or tags.get("brand"),
            "lat": round(lat, 6), "lon": round(lon, 6), "version": e.get("version"),
            "timestamp": e.get("timestamp"), "hash": _hash_tags(tags),
        }
    return elementos


# --- snapshot ----------------------------------------------------------------
def leer_snapshot(config) -> tuple[dict, dict] | tuple[None, None]:
    ruta = config.ruta("snapshots") / ARCHIVO_SNAPSHOT
    if not ruta.exists():
        return None, None
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    meta = json.loads(lineas[0].lstrip("# "))
    previo = {}
    for linea in lineas[1:]:
        oid, h, p, lat, lon, nombre = linea.split("\t")
        previo[oid] = {"hash": h, "principal": p, "lat": float(lat), "lon": float(lon), "nombre": nombre or None}
    return meta, previo


def escribir_snapshot(config, elementos: dict, partidos: list[str], fecha: str):
    ruta = config.ruta("snapshots") / ARCHIVO_SNAPSHOT
    limpiar = lambda s: re.sub(r"[\t\r\n]+", " ", s or "")  # noqa: E731
    lineas = ["# " + json.dumps({"fecha": fecha, "partidos": partidos, "elementos": len(elementos)},
                                ensure_ascii=False)]
    for oid in sorted(elementos, key=lambda k: (k.split("/")[0], int(k.split("/")[1]))):
        e = elementos[oid]
        lineas.append("\t".join([oid, e["hash"], e["principal"], f"{e['lat']:.6f}", f"{e['lon']:.6f}",
                                 limpiar(e["nombre"])]))
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")


# --- señales -----------------------------------------------------------------
def _fecha_local(ts: str | None, tz) -> str | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(tz).date().isoformat()


def _apertura(tags: dict, hoy: date) -> tuple[str, str] | None:
    """opening_date futura → (fecha, precisión). Acepta YYYY-MM-DD (exacta) y YYYY-MM (inferida)."""
    v = (tags.get("opening_date") or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return (v, "exacta") if v >= hoy.isoformat() else None
    if re.fullmatch(r"\d{4}-\d{2}", v):
        return (f"{v}-01", "inferida") if v >= hoy.isoformat()[:7] else None
    return None


def _es_comercio(e: dict, config) -> bool:
    k, _, v = e["principal"].partition("=")
    return not (k == "shop" and v in config["osm"]["shop_no_comercio"])


def generar_senales(actual: dict, previo: dict | None, partidos_previos: list[str] | None,
                    config, limites: Limites, hoy: date) -> list[Senal]:
    tz = config.tz
    desde = (hoy - timedelta(days=config["osm"]["ventana_creacion_dias"])).isoformat()
    prefijos = tuple(f"{p}:" for p in config["osm"]["prefijos_por_abrir"])
    senales = []

    for oid, e in actual.items():
        partido = limites.partido_de(e["lat"], e["lon"])
        if not partido:
            continue
        tags = e["tags"]
        fecha_reg = _fecha_local(e["timestamp"], tz)
        base = dict(
            fuente=NOMBRE, nombre=e["nombre"], partido=partido, detectado_el=hoy.isoformat(),
            url=f"https://www.openstreetmap.org/{oid}", lat=e["lat"], lon=e["lon"],
            localidad=tags.get("addr:suburb") or tags.get("addr:city"),
            direccion=" ".join(x for x in (tags.get("addr:street"), tags.get("addr:housenumber")) if x) or None,
            titulo_fuente=f"OSM {e['principal']}", fecha_registro=fecha_reg, id_externo=f"osm:{oid}",
            extra={"etiqueta": e["principal"], "version": e["version"], "marca": tags.get("brand")},
        )
        rubro_tags = dict(tags)
        if e["principal"].startswith(prefijos):  # construction:shop=clothes → rubro de shop=clothes
            k, _, v = e["principal"].partition("=")
            rubro_tags[k.split(":", 1)[1]] = v
        base["rubro"] = clasificar_osm(rubro_tags, config)

        apertura = _apertura(tags, hoy)
        if e["principal"].startswith(prefijos) or apertura:
            fecha, prec = apertura or (None, "sin_fecha")
            senales.append(Senal(tipo_senal="por_abrir_osm", fecha_evento=fecha, precision_fecha=prec,
                                 detalle=f"OSM lo marca como por abrir ({e['principal']}"
                                         + (f", opening_date={tags['opening_date']})" if apertura else ")"),
                                 **base))
            continue
        if not _es_comercio(e, config):
            continue

        prev = previo.get(oid) if previo is not None else None
        if e["version"] == 1 and fecha_reg and fecha_reg >= desde:
            senales.append(Senal(tipo_senal="creacion_osm", precision_fecha="deteccion",
                                 detalle=f"Cargado por primera vez en OSM el {fecha_reg}", **base))
        elif previo is not None and prev is None and partido in (partidos_previos or []):
            senales.append(Senal(tipo_senal="alta_osm", precision_fecha="deteccion",
                                 detalle=f"Apareció en OSM desde el snapshot anterior (última edición {fecha_reg})",
                                 **base))
        elif prev is not None:
            cambios = []
            if prev["principal"] != e["principal"]:
                cambios.append(f"rubro {prev['principal']} → {e['principal']}")
            if prev["nombre"] and e["nombre"] and normalizar(prev["nombre"]) != normalizar(e["nombre"]):
                cambios.append(f"nombre «{prev['nombre']}» → «{e['nombre']}»")
            if cambios:
                senales.append(Senal(tipo_senal="cambio_osm", precision_fecha="deteccion",
                                     detalle="Mismo lugar, " + "; ".join(cambios) + " (posible local nuevo)",
                                     **{**base, "extra": {**base["extra"], "antes": prev["principal"],
                                                          "nombre_antes": prev["nombre"]}}))

    if config["osm"].get("detectar_desaparicion") and previo:
        for oid, prev in previo.items():
            if oid in actual:
                continue
            partido = limites.partido_de(prev["lat"], prev["lon"])
            if partido:
                senales.append(Senal(
                    fuente=NOMBRE, tipo_senal="baja_osm", nombre=prev["nombre"], partido=partido,
                    rubro=clasificar_osm(dict([prev["principal"].split("=", 1)]), config),
                    detectado_el=hoy.isoformat(), url=f"https://www.openstreetmap.org/{oid}/history",
                    lat=prev["lat"], lon=prev["lon"], id_externo=f"osm:{oid}",
                    detalle="Desapareció de OSM (posible cierre)"))
    return senales


# --- interfaz común ----------------------------------------------------------
def descargar(config, cliente, limites: Limites) -> dict:
    return overpass.consultar(cliente, config, construir_query(config, limites),
                              ttl=config["osm"]["ttl_cache_h"] * 3600)


def recolectar(config, cache) -> list[Senal]:
    """cache: radar.http.Cliente. Escribe el snapshot salvo en dry-run."""
    ejec = config.get("_ejecucion", {})
    limites = Limites(config)
    hoy = config.ahora().date()
    actual = parsear(descargar(config, cache, limites), config)
    meta, previo = leer_snapshot(config)

    mismos_partidos = meta and meta["partidos"] == sorted(limites.geoms)
    if previo and mismos_partidos and len(actual) < MINIMO_RELATIVO * meta["elementos"]:
        raise RuntimeError(f"Overpass trajo {len(actual)} elementos contra {meta['elementos']} del snapshot; "
                           "se asume respuesta incompleta y no se compara ni se pisa el snapshot")
    senales = generar_senales(actual, previo, meta["partidos"] if meta else None, config, limites, hoy)
    if not ejec.get("dry_run"):
        escribir_snapshot(config, actual, sorted(limites.geoms), hoy.isoformat())
    log.info("OSM: %d elementos, %d señales", len(actual), len(senales))
    return senales
