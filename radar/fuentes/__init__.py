"""Registro de fuentes. Cada módulo expone NOMBRE, TIPO, URL, LICENCIA, CONFIANZA_BASE
y recolectar(config, cache) -> list[Senal]."""

from . import directorios, medios_rss, osm

FUENTES = {m.NOMBRE: m for m in (osm, medios_rss, directorios)}
