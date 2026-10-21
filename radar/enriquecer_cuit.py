"""Cruce de candidatos con el padrón de ARCA (solo personas jurídicas). No modifica el puntaje.

Coincidencias:
  direccion_y_nombre → confianza_cuit alta   (requiere un archivo con domicilio; el actual de ARCA no lo trae)
  direccion_exacta   → confianza_cuit media
  nombre_similar     → confianza_cuit baja   (nombre exacto normalizado o similar sobre el umbral)
  ambigua            → no se asigna CUIT (más de una sociedad posible)
Ante la duda no se asigna. Un CUIT por nombre puede ser el de la empresa dueña de la marca y no el del local.
"""

from __future__ import annotations

from .padron.parsear import Indice, tipo_persona
from .texto import normalizar

CAMPOS = ("cuit", "fuente_cuit", "coincidencia", "confianza_cuit", "razon_social_cuit", "condicion_iva",
          "empleador", "cuit_alta_reciente", "cuits_posibles")


def _unicos(filas: list[dict]) -> dict[str, dict]:
    return {f["cuit"]: f for f in filas}


def _desambiguar(filas: dict[str, dict], candidato: dict, localidades: dict[str, list[str]] | None) -> dict[str, dict]:
    """Si el archivo trae localidad, se quedan las filas de la localidad o del partido del candidato."""
    if not candidato.get("partido") or not any(f.get("localidad") for f in filas.values()):
        return filas
    propias = {normalizar(candidato.get("localidad") or "")} | {
        k for k, partidos in (localidades or {}).items() if candidato["partido"] in partidos}
    filtradas = {c: f for c, f in filas.items() if normalizar(f.get("localidad") or "") in propias}
    return filtradas or filas


def cruzar(candidato: dict, indice: Indice, config, cuits_nuevos: set[str] | None = None,
           localidades: dict | None = None) -> dict:
    """Campos de CUIT para el candidato (todos en None si no hay asignación)."""
    vacio = dict.fromkeys(CAMPOS)
    por_dir = _desambiguar(_unicos(indice.buscar_direccion(candidato.get("direccion"))), candidato, localidades)
    filas_nombre, _metodo = indice.buscar_nombre(candidato.get("nombre"))
    por_nombre = _desambiguar(_unicos(filas_nombre), candidato, localidades)

    ambas = {c: f for c, f in por_dir.items() if c in por_nombre}
    if len(ambas) == 1:
        elegido, coincidencia, confianza = next(iter(ambas.values())), "direccion_y_nombre", "alta"
    elif len(por_dir) == 1 and not por_nombre:
        elegido, coincidencia, confianza = next(iter(por_dir.values())), "direccion_exacta", "media"
    elif len(por_nombre) == 1 and not por_dir:
        elegido, coincidencia, confianza = next(iter(por_nombre.values())), "nombre_similar", "baja"
    else:
        posibles = len(ambas) or len(set(por_dir) | set(por_nombre))
        if posibles > 1:
            return {**vacio, "fuente_cuit": "padron_arca", "coincidencia": "ambigua", "cuits_posibles": posibles}
        return vacio

    if tipo_persona(elegido["cuit"], config["padron"]) != "juridica":  # el índice solo tiene jurídicas; doble control
        return vacio
    return {
        "cuit": elegido["cuit"], "fuente_cuit": "padron_arca", "coincidencia": coincidencia,
        "confianza_cuit": confianza, "razon_social_cuit": elegido.get("razon_social"),
        "condicion_iva": elegido.get("iva") or None, "empleador": elegido.get("empleador") or None,
        "cuit_alta_reciente": bool(cuits_nuevos and elegido["cuit"] in cuits_nuevos), "cuits_posibles": 1,
    }


def enriquecer(candidatos: list[dict], indice: Indice, config, cuits_nuevos: set[str] | None = None,
               localidades: dict | None = None) -> int:
    """Agrega los campos de CUIT a cada candidato. Devuelve cuántos quedaron con CUIT."""
    asignados = 0
    for c in candidatos:
        c.update(cruzar(c, indice, config, cuits_nuevos, localidades))
        asignados += bool(c["cuit"])
    return asignados


def sin_personas_fisicas(candidato: dict, config) -> dict:
    """Garantía para lo publicado: si un CUIT no es de persona jurídica, se borran CUIT y razón social."""
    cuit = candidato.get("cuit")
    if cuit and tipo_persona(cuit, config["padron"]) != "juridica":
        return {**candidato, "cuit": None, "razon_social_cuit": None, "condicion_iva": None, "empleador": None}
    return candidato


def altas(actual: list[dict], anterior: list[dict]) -> list[dict]:
    """CUITs presentes en el derivado actual y no en el anterior."""
    previos = {f["cuit"] for f in anterior}
    return [f for f in actual if f["cuit"] not in previos]
