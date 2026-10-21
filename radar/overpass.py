"""Consultas a Overpass con endpoints alternativos.

Política de overpass-api.de (wiki.openstreetmap.org/wiki/Overpass_API, revisada 2026-10-20):
para uso regular, menos de 100 consultas y menos de 10 MB por día, User-Agent identificable,
nada en paralelo y 30 s de pausa ante 429/406. El cliente HTTP ya serializa y espera; acá solo
se rota de servidor si uno sigue fallando.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def consultar(cliente, config, query: str, ttl: float | None = None) -> dict:
    ov = config["overpass"]
    errores = []
    for ep in ov["endpoints"]:
        try:
            r = cliente.pedir(ep, metodo="POST", datos={"data": query}, ttl=ttl,
                              timeout=ov["timeout_query_s"] + 30)
            datos = r.json()
            if "elements" not in datos:
                raise ValueError(f"respuesta sin 'elements' de {ep}")
            if datos.get("remark"):  # Overpass informa timeouts parciales en 'remark'
                raise ValueError(f"{ep}: {datos['remark']}")
            return datos
        except Exception as e:  # noqa: BLE001 — se prueba el siguiente endpoint
            log.warning("Overpass %s falló: %s", ep, e)
            errores.append(f"{ep}: {e}")
    raise RuntimeError("Todos los endpoints de Overpass fallaron: " + " | ".join(errores))
