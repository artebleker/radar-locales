"""Snapshots de listados (directorios de shoppings, sucursales de cadenas) en texto plano.

Una línea por elemento: id, nombre y un campo extra. Texto y ordenado para que git guarde solo diferencias.
"""

from __future__ import annotations

import json
import re

_LIMPIAR = re.compile(r"[\t\r\n]+")


def ruta(config, carpeta: str, lista_id: str):
    d = config.ruta("snapshots") / carpeta
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{lista_id}.tsv"


def leer(config, carpeta: str, lista_id: str) -> tuple[dict | None, dict | None]:
    r = ruta(config, carpeta, lista_id)
    if not r.exists():
        return None, None
    lineas = r.read_text(encoding="utf-8").splitlines()
    previo = {}
    for linea in lineas[1:]:
        eid, nombre, extra = linea.split("\t")
        previo[eid] = {"nombre": nombre, "extra": extra or None}
    return json.loads(lineas[0].lstrip("# ")), previo


def escribir(config, carpeta: str, lista_id: str, elementos: dict[str, tuple[str, str | None]], fecha: str):
    """elementos: {id: (nombre, extra)}."""
    limpiar = lambda s: _LIMPIAR.sub(" ", s or "")  # noqa: E731
    lineas = ["# " + json.dumps({"fecha": fecha, "elementos": len(elementos)})]
    lineas += [f"{eid}\t{limpiar(n)}\t{limpiar(x)}" for eid, (n, x) in sorted(elementos.items())]
    ruta(config, carpeta, lista_id).write_text("\n".join(lineas) + "\n", encoding="utf-8")


def verificar_completo(actual: int, previo: dict | None, minimo_relativo: float):
    if previo and actual < minimo_relativo * len(previo):
        raise RuntimeError(f"{actual} elementos contra {len(previo)} del snapshot; respuesta incompleta")
    if not actual:
        raise RuntimeError("el listado vino vacío (¿cambió el sitio?)")
