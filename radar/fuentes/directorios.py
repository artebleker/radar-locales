"""Directorios de shoppings: una tienda que aparece y no estaba en el relevamiento anterior, o que figura
como «Próximamente», es una apertura (o una próxima apertura).

Un solo adaptador genérico configurado por sitio en config.yaml (páginas, patrón de link, origen del nombre).
Snapshot por sitio en texto plano: data/snapshots/directorios/<id>.tsv.
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..geo import Limites
from ..modelos import Senal
from ..rubros import clasificar_texto
from ..texto import normalizar

NOMBRE = "directorios"
TIPO = "directorio"
URL = "config.yaml → directorios.sitios"
LICENCIA = "Nombre de la tienda y link al directorio público de cada shopping"
CONFIANZA_BASE = "alta"

log = logging.getLogger(__name__)
NIVELES_TARJETA = 5
TEXTOS_GENERICOS = {"ver mas", "ir a perfil", "mas info", "mas informacion", "ver local", "ver tienda", "leer mas"}


def _humanizar(slug: str) -> str:
    return " ".join(p.capitalize() for p in slug.replace("_", "-").split("-") if p)


def _tarjeta(a, niveles: int = NIVELES_TARJETA):
    """Ancestros del link, del más cercano al más lejano (la «tarjeta» de la tienda)."""
    return [p for _, p in zip(range(niveles), a.parents)]


def parsear_pagina(html: str, url: str, sitio: dict, pagina: dict, patron_por_abrir: re.Pattern) -> dict:
    """{id: {"nombre", "url", "rubro", "por_abrir"}} de una página del directorio."""
    s = BeautifulSoup(html, "html.parser")
    tiendas: dict[str, dict] = {}
    excluir = set(sitio.get("excluir_ids") or [])
    modo = sitio["nombre_desde"]

    if modo == "img_alt":
        excluir_alt = {normalizar(x) for x in sitio.get("excluir_alt") or []}
        for img in s.find_all("img", alt=True):
            alt = img["alt"].strip()
            clave = normalizar(alt).replace(" ", "-")
            if alt and normalizar(alt) not in excluir_alt:
                tiendas.setdefault(clave, {"nombre": alt, "url": url, "rubro": pagina.get("rubro"), "por_abrir": False})
        return tiendas

    patron = re.compile(sitio["enlace"])
    for a in s.find_all("a", href=True):
        href = a["href"].strip()
        m = patron.search(href)
        if not m or m.group(1) in excluir:
            continue
        tid = m.group(1)
        if modo == "selector":
            nodo = next((n for p in _tarjeta(a) if (n := p.select_one(sitio["selector"]))), None)
            nombre = nodo.get_text(" ", strip=True) if nodo else ""
        elif modo == "enlace":
            img = a.find("img", alt=True)
            texto = a.get_text(" ", strip=True)
            if normalizar(texto) in TEXTOS_GENERICOS:
                texto = ""
            nombre = (img["alt"].strip() if img else "") or texto or a.get("title", "")
        else:
            nombre = ""
        tarjeta = _tarjeta(a, 3)[-1] if _tarjeta(a, 3) else a
        ent = tiendas.setdefault(tid, {"nombre": "", "url": urljoin(url, href), "rubro": pagina.get("rubro"),
                                       "por_abrir": False})
        ent["nombre"] = ent["nombre"] or nombre
        ent["por_abrir"] = ent["por_abrir"] or bool(patron_por_abrir.search(tarjeta.get_text(" ", strip=True)))
    for tid, ent in tiendas.items():
        ent["nombre"] = ent["nombre"] or _humanizar(tid)
    return tiendas


def descargar_sitio(config, cliente, sitio: dict) -> dict:
    conf = config["directorios"]
    patron_pa = re.compile(conf["patron_por_abrir"], re.IGNORECASE)
    tiendas: dict[str, dict] = {}
    for pagina in sitio["paginas"]:
        numeros = range(conf["max_paginas"]) if "{n}" in pagina["url"] else [None]
        for n in numeros:
            url = pagina["url"].format(n=n) if n is not None else pagina["url"]
            lote = parsear_pagina(cliente.pedir(url).text, url, sitio, pagina, patron_pa)
            nuevas = {k: v for k, v in lote.items() if k not in tiendas}
            for k, v in lote.items():
                if k in tiendas:  # la misma tienda en dos categorías: se conserva el primer rubro
                    tiendas[k]["por_abrir"] |= v["por_abrir"]
            tiendas.update(nuevas)
            if n is not None and not nuevas:
                break
    return tiendas


# --- snapshot ----------------------------------------------------------------
def _ruta_snapshot(config, sitio_id: str):
    d = config.ruta("snapshots") / "directorios"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{sitio_id}.tsv"


def leer_snapshot(config, sitio_id: str):
    ruta = _ruta_snapshot(config, sitio_id)
    if not ruta.exists():
        return None, None
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    previo = {}
    for linea in lineas[1:]:
        tid, nombre, rubro = linea.split("\t")
        previo[tid] = {"nombre": nombre, "rubro": rubro or None}
    return json.loads(lineas[0].lstrip("# ")), previo


def escribir_snapshot(config, sitio_id: str, tiendas: dict, fecha: str):
    limpiar = lambda s: re.sub(r"[\t\r\n]+", " ", s or "")  # noqa: E731
    lineas = ["# " + json.dumps({"fecha": fecha, "tiendas": len(tiendas)})]
    lineas += [f"{tid}\t{limpiar(t['nombre'])}\t{t['rubro'] or ''}" for tid, t in sorted(tiendas.items())]
    _ruta_snapshot(config, sitio_id).write_text("\n".join(lineas) + "\n", encoding="utf-8")


# --- señales -----------------------------------------------------------------
def generar_senales(sitio: dict, tiendas: dict, meta: dict | None, previo: dict | None, partido: str,
                    hoy: str, config) -> list[Senal]:
    senales = []
    for tid, t in tiendas.items():
        nueva = previo is not None and tid not in previo
        if not (nueva or t["por_abrir"]):
            continue
        motivos = []
        if nueva:
            motivos.append(f"apareció en el directorio de {sitio['nombre']} (no estaba el {meta['fecha']})")
        if t["por_abrir"]:
            motivos.append(f"figura como «Próximamente» en {sitio['nombre']}")
        senales.append(Senal(
            fuente=NOMBRE, tipo_senal="alta_directorio", nombre=t["nombre"],
            rubro=t["rubro"] or clasificar_texto(t["nombre"], config), partido=partido,
            direccion=sitio["nombre"], lat=sitio["lat"], lon=sitio["lon"], detectado_el=hoy, url=t["url"],
            precision_fecha="deteccion", titulo_fuente=f"Directorio de {sitio['nombre']}",
            id_externo=f"dir:{sitio['id']}:{tid}", detalle="; ".join(motivos).capitalize(),
            extra={"shopping": sitio["nombre"], "estado_sugerido": "por_abrir" if t["por_abrir"] else "abrio"},
        ))
    return senales


def recolectar(config, cache) -> list[Senal]:
    conf = config["directorios"]
    ejec = config.get("_ejecucion", {})
    limites = Limites(config)
    hoy = config.ahora().date().isoformat()
    senales, errores, resumen = [], [], {}
    for sitio in conf["sitios"]:
        partido = limites.partido_de(sitio["lat"], sitio["lon"])
        if not partido:
            log.info("%s queda fuera de los partidos activos; se omite", sitio["nombre"])
            continue
        try:
            tiendas = descargar_sitio(config, cache, sitio)
            meta, previo = leer_snapshot(config, sitio["id"])
            if previo and len(tiendas) < conf["minimo_relativo"] * len(previo):
                raise RuntimeError(f"{len(tiendas)} tiendas contra {len(previo)} del snapshot; respuesta incompleta")
            if not tiendas:
                raise RuntimeError("el directorio no devolvió tiendas (¿cambió el HTML?)")
            senales += generar_senales(sitio, tiendas, meta, previo, partido, hoy, config)
            if not ejec.get("dry_run"):
                escribir_snapshot(config, sitio["id"], tiendas, hoy)
            resumen[sitio["nombre"]] = len(tiendas)
        except Exception as e:  # noqa: BLE001 — un sitio roto no frena a los demás
            log.warning("Directorio %s falló: %s", sitio["nombre"], e)
            errores.append(f"{sitio['nombre']}: {type(e).__name__}: {e}")
    if errores and not resumen:
        raise RuntimeError("todos los directorios fallaron: " + " | ".join(errores))
    config.setdefault("_avisos", {})[NOMBRE] = errores
    config.setdefault("_resumen", {})[NOMBRE] = resumen
    return senales
