"""Descarga periódica del padrón de ARCA con estado en data/padron_local/estado.json.

- Si no pasaron `frecuencia_dias` desde la última descarga, no se descarga: se usa el derivado local.
- Si el sha256 no cambió, no se reprocesa.
- Si la descarga o el formato fallan, se conserva el derivado anterior y se lanza la excepción
  (la corrida la registra como «Falló» en la salud de fuentes y sigue).
- Se conservan solo los dos derivados más recientes (el mes actual y el anterior, necesario para las altas).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from . import parsear

ARCHIVO_ESTADO = "estado.json"


def directorio(config):
    return config.ruta("padron_local")


def leer_estado(config) -> dict | None:
    ruta = directorio(config) / ARCHIVO_ESTADO
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None


def _guardar_estado(config, estado: dict):
    (directorio(config) / ARCHIVO_ESTADO).write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")


def derivados(config) -> list:
    """Derivados existentes, del más viejo al más nuevo (AAAA-MM.tsv.gz)."""
    return sorted(directorio(config).glob("????-??.tsv.gz"))


def toca_descargar(estado: dict | None, hoy: date, frecuencia_dias: int) -> bool:
    if not estado or not estado.get("ultima_descarga"):
        return True
    return (hoy - date.fromisoformat(estado["ultima_descarga"])).days >= frecuencia_dias


def actualizar(config, cliente, hoy: date, forzar: bool = False) -> dict:
    """Devuelve {"accion": omitida | sin_cambios | actualizada, ...}. Lanza excepción si falla."""
    conf = config["padron"]
    estado = leer_estado(config)
    if not forzar and not toca_descargar(estado, hoy, conf["frecuencia_dias"]):
        return {"accion": "omitida", "estado": estado}

    r = cliente.pedir(conf["url"], timeout=conf["timeout_s"], cachear=False)  # trae nombres de personas: sin caché
    contenido = r.content
    sha = hashlib.sha256(contenido).hexdigest()
    if estado and estado.get("sha256") == sha and derivados(config):
        estado["ultima_descarga"] = hoy.isoformat()
        _guardar_estado(config, estado)
        return {"accion": "sin_cambios", "estado": estado}

    filas_j, total = parsear.juridicas(contenido, conf)  # FormatoInvalido si no coincide con `columnas`
    periodo = hoy.isoformat()[:7]
    columnas = parsear.columnas_disponibles(conf)
    destino = directorio(config) / f"{periodo}.tsv.gz"
    temporal = destino.with_suffix(".tmp")
    parsear.escribir_derivado(temporal, filas_j, columnas)
    temporal.replace(destino)  # recién ahora se reemplaza: si algo falló antes, queda el anterior
    for viejo in derivados(config)[:-2]:
        viejo.unlink()

    estado = {"ultima_descarga": hoy.isoformat(), "sha256": sha, "filas_total": total,
              "filas_juridicas": len(filas_j), "periodo": periodo, "url": conf["url"],
              "fuente_modificada": getattr(r, "headers", {}).get("Last-Modified")}
    _guardar_estado(config, estado)
    return {"accion": "actualizada", "estado": estado}


def cargar_actual_y_anterior(config) -> tuple[list[dict] | None, list[dict] | None]:
    d = derivados(config)
    actual = parsear.leer_derivado(d[-1]) if d else None
    anterior = parsear.leer_derivado(d[-2]) if len(d) > 1 else None
    return actual, anterior
