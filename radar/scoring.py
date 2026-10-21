"""Puntaje de confianza y estado de cada candidato. Los números están en config.yaml → puntaje.

Puntaje = peso de la mejor señal + bono por cada fuente distinta adicional + bonos (fecha exacta,
dirección) + penalizaciones de la mejor señal (sin nombre, partido dudoso, palabras débiles…).
Se recorta a 0-100. Confianza: alta / media / baja según los umbrales.
"""

from __future__ import annotations


def puntuar(senales: list, config) -> tuple[int, str, list[str]]:
    """(puntaje, confianza, motivos legibles)."""
    p = config["puntaje"]
    base = p["base"]
    mejor = max(senales, key=lambda s: base.get(s.tipo_senal, 0))
    puntaje = base.get(mejor.tipo_senal, 0)
    motivos = [f"{mejor.tipo_senal} +{puntaje}"]

    fuentes = {s.fuente for s in senales}
    if len(fuentes) > 1:
        extra = p["bonos"]["fuente_adicional"] * (len(fuentes) - 1)
        puntaje += extra
        motivos.append(f"{len(fuentes)} fuentes distintas +{extra}")
    if any(s.precision_fecha == "exacta" for s in senales):
        puntaje += p["bonos"]["fecha_exacta"]
        motivos.append(f"fecha exacta +{p['bonos']['fecha_exacta']}")
    if any(s.direccion for s in senales):
        puntaje += p["bonos"]["direccion"]
        motivos.append(f"dirección +{p['bonos']['direccion']}")

    penalizaciones = list((mejor.extra or {}).get("penalizaciones") or [])
    if not any(s.nombre for s in senales) and "sin_nombre" not in penalizaciones:
        penalizaciones.append("sin_nombre")
    for pen in penalizaciones:
        clave = pen.split(":")[0]
        valor = p["penalizaciones"].get(clave, 0)
        if valor:
            puntaje += valor
            motivos.append(f"{pen} {valor}")

    puntaje = max(0, min(100, puntaje))
    u = p["umbrales"]
    confianza = "alta" if puntaje >= u["alta"] else "media" if puntaje >= u["media"] else "baja"
    return puntaje, confianza, motivos


def estado(senales: list, hoy: str) -> str:
    """por_abrir | abrio | detectado."""
    fechas = [s.fecha_evento for s in senales if s.fecha_evento]
    if any(f > hoy for f in fechas):
        return "por_abrir"
    sugeridos = {(s.extra or {}).get("estado_sugerido") for s in senales}
    if "abrio" in sugeridos or any(f <= hoy for f in fechas):
        return "abrio"
    if "por_abrir" in sugeridos or any(s.tipo_senal == "por_abrir_osm" for s in senales):
        return "por_abrir"
    return "detectado"
