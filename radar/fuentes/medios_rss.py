"""Notas de medios locales de zona norte (RSS de WordPress, feeds por sección y API pública de WordPress).

De cada nota se guarda solo título, medio, fecha y link. El resumen del feed se usa en memoria para
ubicar la nota, pero nunca se persiste.
"""

from __future__ import annotations

import calendar
import html
import logging
from datetime import date, datetime, timedelta, timezone

import feedparser
from bs4 import BeautifulSoup

from .. import extraccion
from ..geo import cargar_localidades

NOMBRE = "medios_rss"
TIPO = "prensa"
URL = "config.yaml → medios_rss.feeds"
LICENCIA = "Solo título, medio, fecha y link de cada nota; el contenido es de cada medio"
CONFIANZA_BASE = "media"

log = logging.getLogger(__name__)


def _texto(s: str | None) -> str:
    return " ".join(BeautifulSoup(html.unescape(s or ""), "html.parser").get_text(" ").split())


def _notas_rss(contenido: bytes, feed: dict, tz) -> list[dict]:
    notas = []
    for e in feedparser.parse(contenido).entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        fecha = (datetime.fromtimestamp(calendar.timegm(t), timezone.utc).astimezone(tz).date() if t else None)
        notas.append({"medio": feed["nombre"], "titulo": _texto(e.get("title")), "link": e.get("link"),
                      "resumen": _texto(e.get("summary")), "fecha_publicacion": fecha,
                      "categorias": [x.get("term", "") for x in e.get("tags", [])],
                      "partido_defecto": feed.get("partido_defecto")})
    return notas


def _notas_wp_json(datos: list, feed: dict) -> list[dict]:
    return [{"medio": feed["nombre"], "titulo": _texto(p["title"]["rendered"]), "link": p["link"],
             "resumen": _texto((p.get("excerpt") or {}).get("rendered")),
             "fecha_publicacion": date.fromisoformat(p["date"][:10]),  # hora local del sitio
             "categorias": [], "partido_defecto": feed.get("partido_defecto")} for p in datos]


def descargar_feed(config, cliente, feed: dict, desde: date) -> list[dict]:
    """Todas las notas del feed desde la fecha dada, paginando lo necesario."""
    conf = config["medios_rss"]
    notas = []
    for pagina in range(1, conf["paginas_max"] + 1):
        if feed["tipo"] == "wp_json":
            url = f"{feed['url']}?per_page=50&page={pagina}&after={desde.isoformat()}T00:00:00&_fields=date,link,title,excerpt"
            try:
                lote = _notas_wp_json(cliente.pedir(url).json(), feed)
            except Exception as e:  # WordPress responde 400 al pasarse de la última página
                if pagina > 1 and "400" in str(e):
                    break
                raise
        else:
            if pagina > 1 and not feed.get("paginable"):
                break
            url = feed["url"] if pagina == 1 else f"{feed['url']}?paged={pagina}"
            try:
                lote = _notas_rss(cliente.pedir(url).content, feed, config.tz)
            except Exception:
                if pagina > 1:  # páginas extra: si fallan, alcanza con lo que ya se tiene
                    break
                raise
        nuevas = [n for n in lote if n["link"] not in {x["link"] for x in notas}]
        if not nuevas:  # algunos sitios ignoran ?paged= y repiten la primera página
            break
        notas.extend(nuevas)
        fechas = [n["fecha_publicacion"] for n in nuevas if n["fecha_publicacion"]]
        if fechas and min(fechas) < desde:
            break
    return [n for n in notas if n["link"] and (n["fecha_publicacion"] is None or n["fecha_publicacion"] >= desde)]


def descargar(config, cliente) -> tuple[list[dict], list[str]]:
    desde = config.ahora().date() - timedelta(days=config["medios_rss"]["ventana_dias"])
    notas, errores, vistos = [], [], set()
    for feed in config["medios_rss"]["feeds"]:
        try:
            for n in descargar_feed(config, cliente, feed, desde):
                if n["link"] not in vistos:  # el mismo medio repite notas entre secciones
                    vistos.add(n["link"])
                    notas.append(n)
        except Exception as e:  # noqa: BLE001 — un feed caído no frena a los demás
            log.warning("Feed %s (%s) falló: %s", feed["nombre"], feed["url"], e)
            errores.append(f"{feed['nombre']}: {type(e).__name__}: {e}")
    return notas, errores


def recolectar(config, cache) -> list:
    notas, errores = descargar(config, cache)
    if errores and not notas:
        raise RuntimeError("todos los feeds fallaron: " + " | ".join(errores))
    config.setdefault("_avisos", {})[NOMBRE] = errores
    hoy = config.ahora().date()
    ext = extraccion.Extractor(config, cargar_localidades(config))
    senales = [s for n in notas if (s := ext.senal_de_nota(n, hoy, NOMBRE))]
    log.info("Medios: %d notas, %d señales, %d feeds con error", len(notas), len(senales), len(errores))
    return senales
