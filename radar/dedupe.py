"""Agrupa señales en candidatos. Ante la duda no se fusiona: mejor un duplicado visible que perder uno.

Dos señales van al mismo candidato si:
  - tienen el mismo id externo (la misma nota, el mismo nodo OSM, la misma sucursal), o
  - sus nombres normalizados se parecen (umbral en config) y además están a menos de N metros,
    o están en el mismo partido y al menos una no tiene coordenadas.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from .geo import distancia_km
from .texto import normalizar


def nombre_normalizado(nombre: str | None, config) -> str:
    n = normalizar(nombre or "")
    genericas = [normalizar(p) for p in config["deduplicacion"]["palabras_genericas"]]
    limpio = n
    for p in sorted(genericas, key=len, reverse=True):
        limpio = re.sub(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", " ", limpio)
    limpio = " ".join(limpio.split())
    return limpio or n


def _mismo_lugar(a, b, config) -> bool:
    if a.lat is not None and b.lat is not None:
        return distancia_km(a.lat, a.lon, b.lat, b.lon) * 1000 <= config["deduplicacion"]["distancia_m"]
    return bool(a.partido) and a.partido == b.partido


def similares(a, b, config) -> bool:
    na, nb = nombre_normalizado(a.nombre, config), nombre_normalizado(b.nombre, config)
    if not na or not nb:
        return False
    return fuzz.token_set_ratio(na, nb) >= config["deduplicacion"]["umbral_nombre"] and _mismo_lugar(a, b, config)


def agrupar(senales: list, config) -> list[list]:
    """Union-find sobre las señales. Devuelve grupos (listas de señales)."""
    padre = list(range(len(senales)))

    def raiz(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    def unir(i, j):
        ri, rj = raiz(i), raiz(j)
        if ri != rj:
            padre[max(ri, rj)] = min(ri, rj)

    por_id: dict[str, int] = {}
    for i, s in enumerate(senales):
        if s.id_externo in por_id:
            unir(i, por_id[s.id_externo])
        else:
            por_id[s.id_externo] = i
    # Señales sin coordenadas: se fusionan solo si coinciden con un único lugar. Si «Día» (nota sin
    # coordenadas) coincide con tres sucursales de Día del partido, es ambiguo y no se fusiona con ninguna.
    sin_coords: dict[int, list[int]] = {}
    for i in range(len(senales)):
        for j in range(i + 1, len(senales)):
            a, b = senales[i], senales[j]
            if raiz(i) == raiz(j) or not similares(a, b, config):
                continue
            if a.lat is None or b.lat is None:
                k, otro = (i, j) if a.lat is None else (j, i)
                sin_coords.setdefault(k, []).append(otro)
            else:
                unir(i, j)
    for k, otros in sin_coords.items():
        lugares = {raiz(o) for o in otros if senales[o].lat is not None}
        if len(lugares) <= 1:
            for o in otros:
                unir(k, o)

    grupos: dict[int, list] = {}
    for i, s in enumerate(senales):
        grupos.setdefault(raiz(i), []).append(s)
    return list(grupos.values())
