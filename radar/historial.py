"""Historial de señales: un archivo JSONL por mes de primera detección (data/historial/senales-AAAA-MM.jsonl).

Cada línea: {"clave", "primera", "ultima", "senal"}. La clave es fuente|tipo|id_externo, así que una señal que
se repite día a día (una nota que sigue en el feed, un nodo OSM) es una sola entrada con primera y última
detección. Los meses que quedan fuera de publicacion.historial_dias se mueven comprimidos a archivo/.
"""

from __future__ import annotations

import gzip
import json
import shutil
from datetime import date, timedelta

from .modelos import Senal

PREFIJO = "senales-"


def clave(s: Senal) -> str:
    return f"{s.fuente}|{s.tipo_senal}|{s.id_externo}"


def _archivos(config):
    return sorted(config.ruta("historial").glob(f"{PREFIJO}*.jsonl"))


def cargar(config) -> dict[str, dict]:
    entradas = {}
    for f in _archivos(config):
        for linea in f.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                e = json.loads(linea)
                entradas[e["clave"]] = e
    return entradas


def actualizar(config, entradas: dict[str, dict], nuevas: list[Senal], hoy: str) -> dict[str, dict]:
    """Suma las señales de la corrida. Se conserva la primera detección y se actualiza la última y el contenido."""
    for s in nuevas:
        k = clave(s)
        previa = entradas.get(k)
        datos = s.a_dict()
        if previa:
            datos["detectado_el"] = previa["primera"]  # detectado_el = primera vez que el radar la vio
            entradas[k] = {"clave": k, "primera": previa["primera"], "ultima": hoy, "senal": datos}
        else:
            entradas[k] = {"clave": k, "primera": hoy, "ultima": hoy, "senal": datos}
    return entradas


def guardar(config, entradas: dict[str, dict], hoy: str):
    """Reescribe los meses activos y archiva los que superan la ventana de historial."""
    directorio = config.ruta("historial")
    limite = (date.fromisoformat(hoy) - timedelta(days=config["publicacion"]["historial_dias"])).isoformat()
    por_mes: dict[str, list] = {}
    for e in entradas.values():
        por_mes.setdefault(e["primera"][:7], []).append(e)
    for mes, lista in por_mes.items():
        lista.sort(key=lambda e: e["clave"])
        (directorio / f"{PREFIJO}{mes}.jsonl").write_text(
            "".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in lista), encoding="utf-8")
    archivo = directorio / "archivo"
    for f in _archivos(config):
        mes = f.stem[len(PREFIJO):]
        if f"{mes}-31" < limite:
            archivo.mkdir(exist_ok=True)
            with open(f, "rb") as src, gzip.open(archivo / f"{f.name}.gz", "wb") as dst:
                shutil.copyfileobj(src, dst)
            f.unlink()


def senales_activas(entradas: dict[str, dict], hoy: str, dias: int) -> list[tuple[Senal, str, str]]:
    """(señal, primera, ultima) de las entradas vistas dentro de la ventana de historial."""
    limite = (date.fromisoformat(hoy) - timedelta(days=dias)).isoformat()
    return [(Senal.de_dict(e["senal"]), e["primera"], e["ultima"]) for e in entradas.values() if e["ultima"] >= limite]
