"""Unificación (dedupe + puntaje + estado) y generación de site/data/candidatos.json y estado.json."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date, timedelta

from . import dedupe, scoring
from .enriquecer_cuit import sin_personas_fisicas
from .historial import clave
from .rubros import OTROS

# Prioridad para elegir nombre, rubro y ubicación del candidato: la fuente más específica primero.
PRIORIDAD = ["alta_sucursal", "alta_directorio", "nota_prensa", "por_abrir_osm", "cambio_osm",
             "creacion_osm", "alta_osm", "baja_osm", "corroboracion_arca"]


def _orden(s):
    return PRIORIDAD.index(s.tipo_senal) if s.tipo_senal in PRIORIDAD else len(PRIORIDAD)


def fecha_de_senal(s) -> str:
    """Fecha que ubica la señal en el tiempo para la ventana del sitio (no reemplaza a las demás fechas)."""
    if s.fecha_evento:
        return s.fecha_evento
    if s.fecha_publicacion:
        return s.fecha_publicacion
    if s.tipo_senal == "creacion_osm" and s.fecha_registro:
        return s.fecha_registro
    return s.detectado_el


def armar_candidato(grupo: list[tuple], config, hoy: str) -> dict:
    """grupo: lista de (señal, primera, ultima)."""
    senales = sorted((g[0] for g in grupo), key=_orden)
    primeras = {id(g[0]): g[1] for g in grupo}
    mas_vieja = min(grupo, key=lambda g: (g[1], clave(g[0])))[0]
    cid = "c" + hashlib.sha1(clave(mas_vieja).encode()).hexdigest()[:10]

    con_nombre = [s for s in senales if s.nombre]
    con_coords = [s for s in senales if s.lat is not None]
    rubros = [s.rubro for s in senales if s.rubro and s.rubro != OTROS]
    puntaje, confianza, motivos = scoring.puntuar(senales, config)
    exactas = [s for s in senales if s.fecha_evento and s.precision_fecha == "exacta"]
    inferidas = [s for s in senales if s.fecha_evento and s.precision_fecha == "inferida"]
    con_fecha = (exactas or inferidas)
    notas = sorted(s.fecha_publicacion for s in senales if s.tipo_senal == "nota_prensa" and s.fecha_publicacion)
    if con_fecha:
        fecha_est, precision, origen = con_fecha[0].fecha_evento, con_fecha[0].precision_fecha, "anunciada"
    elif notas:  # sin fecha anunciada: la nota más vieja da una estimación (marcada como inferida)
        fecha_est, precision, origen = notas[0], "inferida", "publicacion"
    else:
        fecha_est, precision, origen = None, "deteccion", "deteccion"
    primera = min(g[1] for g in grupo)
    ubic = (con_coords or senales)[0]

    fecha_ventana = max(fecha_de_senal(s) for s in senales)
    max_ventana = max(config["publicacion"]["ventanas_dias"])
    return {
        "id": cid,
        "alias": sorted({"c" + hashlib.sha1(clave(s).encode()).hexdigest()[:10] for s in senales} - {cid}),
        "nombre": con_nombre[0].nombre if con_nombre else None,
        "rubro": rubros[0] if rubros else OTROS,
        "partido": ubic.partido or next((s.partido for s in senales if s.partido), None),
        "localidad": next((s.localidad for s in senales if s.localidad), None),
        "direccion": next((s.direccion for s in senales if s.direccion), None),
        "lat": ubic.lat, "lon": ubic.lon,
        "estado": scoring.estado(senales, hoy),
        "fecha_estimada": fecha_est or primera,
        "precision_fecha": precision,
        "origen_fecha": origen,
        "fecha_ventana": fecha_ventana,
        "confianza": confianza, "puntaje": puntaje, "motivos_puntaje": motivos,
        "fuentes": sorted({s.fuente for s in senales}),
        "senales": [{
            "fuente": s.fuente, "tipo": s.tipo_senal, "url": s.url, "titulo": s.titulo_fuente, "detalle": s.detalle,
            "medio": (s.extra or {}).get("medio") or (s.extra or {}).get("shopping") or (s.extra or {}).get("cadena"),
            "fecha_evento": s.fecha_evento, "precision_fecha": s.precision_fecha,
            "fecha_publicacion": s.fecha_publicacion, "fecha_registro": s.fecha_registro,
            "detectado_el": primeras[id(s)], "penalizaciones": (s.extra or {}).get("penalizaciones") or [],
        } for s in senales],
        "primera_deteccion": primera,
        "ultima_deteccion": max(g[2] for g in grupo),
        "vigente": fecha_ventana >= (date.fromisoformat(hoy) - timedelta(days=max_ventana)).isoformat(),
    }


def unificar(activas: list[tuple], config, hoy: str) -> list[dict]:
    indice = {id(t[0]): t for t in activas}
    grupos = dedupe.agrupar([t[0] for t in activas], config)
    candidatos = [armar_candidato([indice[id(s)] for s in g], config, hoy) for g in grupos]
    candidatos.sort(key=lambda c: c["fecha_ventana"], reverse=True)
    candidatos.sort(key=lambda c: c["puntaje"], reverse=True)  # orden estable: puntaje y, a igualdad, más reciente
    return candidatos


def publicar(config, candidatos: list[dict], salud: list[dict], ahora) -> tuple:
    destino = config.ruta("site_data")
    hoy = ahora.date().isoformat()
    vigentes = [sin_personas_fisicas(c, config) for c in candidatos if c["vigente"]]
    (destino / "candidatos.json").write_text(
        json.dumps({"generado": ahora.isoformat(timespec="seconds"), "candidatos": vigentes},
                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    def_ventana = config["publicacion"]["ventana_defecto"]
    desde = (ahora.date() - timedelta(days=def_ventana)).isoformat()
    en_ventana = [c for c in vigentes if c["fecha_ventana"] >= desde]
    estado = {
        "actualizado": ahora.isoformat(timespec="seconds"),
        "zona_horaria": config["proyecto"]["zona_horaria"],
        "ventanas_dias": config["publicacion"]["ventanas_dias"], "ventana_defecto": def_ventana,
        "totales_ventana": {
            "candidatos": len(en_ventana),
            "por_estado": dict(Counter(c["estado"] for c in en_ventana)),
            "por_confianza": dict(Counter(c["confianza"] for c in en_ventana)),
        },
        "partidos": [p["nombre"] for p in config.partidos()],
        "rubros": list(config["rubros"]),
        "salud": salud,
        "arca": {k: config["arca"][k] for k in ("estado", "comprobado_el", "url_constancia", "nota")},
        "repo": config["proyecto"]["repo_url"],
        "hoy": hoy,
    }
    (destino / "estado.json").write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
    return destino / "candidatos.json", destino / "estado.json"
