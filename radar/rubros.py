"""Clasificación de rubros según config.yaml (etiquetas OSM o palabras clave)."""

from __future__ import annotations

import re

from .texto import normalizar

OTROS = "Otros"


def clasificar_osm(tags: dict, config) -> str:
    for rubro, reglas in config["rubros"].items():
        for clave, valores in (reglas.get("osm") or {}).items():
            if tags.get(clave) in valores:
                return rubro
    return OTROS


def clasificar_texto(texto: str, config) -> str:
    """Primer rubro cuya palabra clave aparece como palabra completa en el texto."""
    palabras = set(normalizar(texto).split())
    for rubro, reglas in config["rubros"].items():
        for p in reglas.get("palabras") or []:
            p = normalizar(p)
            if (" " in p and re.search(rf"\b{re.escape(p)}\b", normalizar(texto))) or p in palabras:
                return rubro
    return OTROS
