"""Buscadores de sucursales de cadenas: una sucursal nueva en un partido de la zona es una apertura.

Un adaptador por tipo de buscador (config.yaml → sucursales.cadenas). Todos devuelven
{id: {"nombre", "direccion", "localidad", "lat", "lon"}}; después se filtra por partido
(punto-en-polígono) y se compara con el snapshot de la cadena.
"""

from __future__ import annotations

import json
import logging
import re

from .. import listados
from ..geo import Limites
from ..modelos import Senal

NOMBRE = "sucursales"
TIPO = "cadena"
URL = "config.yaml → sucursales.cadenas"
LICENCIA = "Datos públicos de sucursales publicados por cada cadena"
CONFIANZA_BASE = "alta"

log = logging.getLogger(__name__)


def _campo(obj, ruta: str):
    for k in ruta.split("."):
        obj = obj.get(k) if isinstance(obj, dict) else None
    return obj


def _float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# --- adaptadores -------------------------------------------------------------
def vtex_pickup(config, cliente, cadena: dict, limites: Limites) -> dict:
    """Puntos de retiro por cercanía desde el centro de cada partido, hasta cubrir su radio."""
    puntos = {}
    for lat, lon, radio in limites.centros().values():
        for pagina in range(1, config["sucursales"]["max_paginas_vtex"] + 1):
            url = (f"https://{cadena['host']}/api/checkout/pub/pickup-points?"
                   f"geoCoordinates={lon:.4f};{lat:.4f}&page={pagina}&pageSize=50")
            items = cliente.pedir(url).json().get("items") or []
            for it in items:
                pp = it["pickupPoint"]
                a = pp.get("address") or {}
                geo = a.get("geoCoordinates") or [None, None]
                calle = " ".join(str(x) for x in (a.get("street"), a.get("number")) if x)
                puntos[pp["id"]] = {"nombre": cadena["nombre"], "direccion": calle or None,
                                    "localidad": a.get("neighborhood") or a.get("city"),
                                    "lat": _float(geo[1]), "lon": _float(geo[0]),
                                    "referencia": pp.get("friendlyName")}
            if not items or min(it["distance"] for it in items) > radio:
                break
    return puntos


def next_data(config, cliente, cadena: dict, limites: Limites) -> dict:
    html = cliente.pedir(cadena["url"]).text
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError("la página ya no trae __NEXT_DATA__")
    lista = json.loads(m.group(1))
    for k in cadena["ruta"]:
        lista = lista[k]
    c = cadena["campos"]
    return {str(_campo(x, c["id"])): {"nombre": f"{cadena['nombre']} {_campo(x, c['nombre']) or ''}".strip(),
                                      "direccion": _campo(x, c.get("direccion", "")),
                                      "localidad": _campo(x, c.get("localidad", "")),
                                      "lat": _float(_campo(x, c["lat"])), "lon": _float(_campo(x, c["lon"]))}
            for x in lista}


def wpsl(config, cliente, cadena: dict, limites: Limites) -> dict:
    tiendas = {}
    for lat, lon, radio in limites.centros().values():
        url = (f"{cadena['url']}?action=store_search&lat={lat:.4f}&lng={lon:.4f}"
               f"&max_results=100&search_radius={int(radio) + 1}")
        for x in cliente.pedir(url).json() or []:
            tiendas[str(x["id"])] = {"nombre": f"{cadena['nombre']} {x.get('store', '')}".strip(),
                                     "direccion": x.get("address"), "localidad": x.get("city"),
                                     "lat": _float(x.get("lat")), "lon": _float(x.get("lng"))}
    return tiendas


def havanna(config, cliente, cadena: dict, limites: Limites) -> dict:
    tiendas = {}
    for tipo in cadena["tipos"]:
        r = json.loads(cliente.pedir(cadena["url"], metodo="POST", datos={"tipo": tipo}).text)
        if r.get("error"):
            raise RuntimeError(f"Havanna devolvió error para tipo={tipo}")
        for x in r.get("data") or []:
            m = re.match(r"\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)", x.get("latitud_longitud") or "")
            tiendas[x["id_locales"]] = {"nombre": cadena["nombre"], "direccion": (x.get("direccion") or "").strip() or None,
                                        "localidad": None, "lat": _float(m.group(1)) if m else None,
                                        "lon": _float(m.group(2)) if m else None}
    return tiendas


ADAPTADORES = {"vtex_pickup": vtex_pickup, "next_data": next_data, "wpsl": wpsl, "havanna": havanna}


# --- señales -----------------------------------------------------------------
def en_zona(tiendas: dict, limites: Limites) -> dict:
    out = {}
    for tid, t in tiendas.items():
        partido = limites.partido_de(t["lat"], t["lon"])
        if partido:
            out[tid] = {**t, "partido": partido}
    return out


def generar_senales(cadena: dict, tiendas: dict, meta: dict | None, previo: dict | None, hoy: str) -> list[Senal]:
    if previo is None:  # primer relevamiento: es la base, no hay altas
        return []
    return [Senal(
        fuente=NOMBRE, tipo_senal="alta_sucursal", nombre=t["nombre"], rubro=cadena["rubro"], partido=t["partido"],
        localidad=t.get("localidad"), direccion=t.get("direccion"), lat=t["lat"], lon=t["lon"], detectado_el=hoy,
        url=cadena.get("url") or f"https://{cadena['host']}/", precision_fecha="deteccion",
        titulo_fuente=f"Buscador de sucursales de {cadena['nombre']}", id_externo=f"suc:{cadena['id']}:{tid}",
        detalle=f"Sucursal nueva en el buscador de {cadena['nombre']} (no figuraba el {meta['fecha']})",
        extra={"cadena": cadena["nombre"], "estado_sugerido": "abrio"},
    ) for tid, t in tiendas.items() if tid not in previo]


def recolectar(config, cache) -> list[Senal]:
    conf = config["sucursales"]
    ejec = config.get("_ejecucion", {})
    limites = Limites(config)
    hoy = config.ahora().date().isoformat()
    senales, errores, resumen = [], [], {}
    for cadena in conf["cadenas"]:
        try:
            tiendas = en_zona(ADAPTADORES[cadena["tipo"]](config, cache, cadena, limites), limites)
            meta, previo = listados.leer(config, "sucursales", cadena["id"])
            listados.verificar_completo(len(tiendas), previo, conf["minimo_relativo"])
            senales += generar_senales(cadena, tiendas, meta, previo, hoy)
            if not ejec.get("dry_run"):
                listados.escribir(config, "sucursales", cadena["id"],
                                  {k: (t["nombre"], t["partido"]) for k, t in tiendas.items()}, hoy)
            resumen[cadena["nombre"]] = len(tiendas)
        except Exception as e:  # noqa: BLE001 — una cadena rota no frena a las demás
            log.warning("Cadena %s falló: %s", cadena["nombre"], e)
            errores.append(f"{cadena['nombre']}: {type(e).__name__}: {e}")
    if errores and not resumen:
        raise RuntimeError("todas las cadenas fallaron: " + " | ".join(errores))
    config.setdefault("_avisos", {})[NOMBRE] = errores
    config.setdefault("_resumen", {})[NOMBRE] = resumen
    return senales
