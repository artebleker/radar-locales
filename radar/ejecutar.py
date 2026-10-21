"""Corrida: recolecta de cada fuente, aislando errores, y registra la salud de cada una."""

from __future__ import annotations

import json
import logging
import time
import traceback

from .fuentes import FUENTES
from .http import Cliente

log = logging.getLogger(__name__)


def fuentes_activas(config, pedidas: list[str] | None) -> list:
    if pedidas:
        desconocidas = set(pedidas) - set(FUENTES)
        if desconocidas:
            raise SystemExit(f"Fuentes desconocidas: {', '.join(sorted(desconocidas))}. Disponibles: {', '.join(FUENTES)}")
        return [FUENTES[n] for n in pedidas]
    return [m for n, m in FUENTES.items() if (config.get(n) or {}).get("activa", True)]


def recolectar(config, pedidas: list[str] | None = None, limite: int | None = None,
               dry_run: bool = False) -> tuple[list, list[dict]]:
    """Devuelve (señales, salud). Una fuente que falla no frena a las demás."""
    config["_ejecucion"] = {"dry_run": dry_run, "limite": limite}
    cliente = Cliente(config)
    senales, salud = [], []
    for fuente in fuentes_activas(config, pedidas):
        t0 = time.monotonic()
        estado = {"fuente": fuente.NOMBRE, "tipo": fuente.TIPO, "url": fuente.URL,
                  "licencia": fuente.LICENCIA, "ok": True, "error": None, "senales": 0}
        try:
            propias = fuente.recolectar(config, cliente)
            if limite:
                propias = propias[:limite]
            senales.extend(propias)
            estado["senales"] = len(propias)
        except Exception as e:  # noqa: BLE001 — se registra y se sigue con la próxima fuente
            log.error("Fuente %s falló: %s", fuente.NOMBRE, e)
            log.debug(traceback.format_exc())
            estado.update(ok=False, error=f"{type(e).__name__}: {e}")
        estado["segundos"] = round(time.monotonic() - t0, 1)
        salud.append(estado)
    return senales, salud


def guardar_corrida(config, senales: list, salud: list[dict]):
    """Última corrida cruda (señales + salud), insumo de la unificación de la fase 6."""
    ruta = config.ruta("snapshots").parent / "ultima_corrida.json"
    ruta.write_text(json.dumps({"fecha": config.ahora().isoformat(timespec="seconds"), "salud": salud,
                                "senales": [s.a_dict() for s in senales]}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return ruta
