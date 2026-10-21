"""Lectura del archivo masivo de ARCA y armado del índice en memoria.

Las personas físicas se descartan al leer: nunca se guardan ni se indexan. En disco queda un derivado
(data/padron_local/AAAA-MM.tsv.gz) solo con personas jurídicas y las columnas que el archivo trae.
"""

from __future__ import annotations

import csv
import gzip
import io
import re
import zipfile
from pathlib import Path

from rapidfuzz import fuzz, process

from ..dedupe import nombre_normalizado
from ..texto import normalizar

MUESTRA_VALIDACION = 2000


class FormatoInvalido(ValueError):
    pass


def tipo_persona(cuit: str, conf: dict) -> str:
    """juridica | fisica | otro, según el prefijo del CUIT."""
    if cuit[:2] in conf["prefijos_juridica"]:
        return "juridica"
    if cuit[:2] in conf["prefijos_fisica"]:
        return "fisica"
    return "otro"


def columnas_disponibles(conf: dict) -> list[str]:
    return [k for k, v in conf["columnas"].items() if v is not None]


def _texto(contenido: bytes, conf: dict) -> io.TextIOBase:
    if conf["formato"] in ("zip_txt", "zip_csv"):
        z = zipfile.ZipFile(io.BytesIO(contenido))
        nombres = [n for n in z.namelist() if not n.endswith("/")]
        if len(nombres) != 1:
            raise FormatoInvalido(f"se esperaba un único archivo en el zip y hay {len(nombres)}")
        return io.TextIOWrapper(z.open(nombres[0]), encoding=conf["codificacion"], newline="")
    return io.TextIOWrapper(io.BytesIO(contenido), encoding=conf["codificacion"], newline="")


def filas(contenido: bytes, conf: dict):
    """Itera filas {columna: valor} validando el formato con las primeras líneas."""
    cols = conf["columnas"]
    disponibles = columnas_disponibles(conf)
    f = _texto(contenido, conf)
    if conf["formato"] in ("csv", "zip_csv"):
        lector = csv.DictReader(f)
        faltan = [v for v in (cols[k] for k in disponibles) if v not in (lector.fieldnames or [])]
        if faltan:
            raise FormatoInvalido(f"faltan columnas en el encabezado: {faltan}")
        for i, r in enumerate(lector):
            fila = {k: (r[cols[k]] or "").strip() for k in disponibles}
            if i < MUESTRA_VALIDACION and not re.fullmatch(r"\d{11}", fila["cuit"]):
                raise FormatoInvalido(f"fila {i + 1}: CUIT inválido")
            yield fila
        return
    largo = conf["largo_linea"]
    for i, linea in enumerate(f):
        linea = linea.rstrip("\r\n")
        if not linea:
            continue
        if i < MUESTRA_VALIDACION and (len(linea) != largo or not linea[:11].isdigit()):
            raise FormatoInvalido(f"línea {i + 1}: largo {len(linea)} (se esperaba {largo}) o CUIT inválido")
        yield {k: linea[cols[k][0]:cols[k][1]].strip() for k in disponibles}


def juridicas(contenido: bytes, conf: dict) -> tuple[list[dict], int]:
    """(filas de personas jurídicas, total de filas leídas)."""
    total, out = 0, []
    for fila in filas(contenido, conf):
        total += 1
        if tipo_persona(fila["cuit"], conf) == "juridica":
            out.append(fila)
    if not total:
        raise FormatoInvalido("el archivo no tiene filas")
    return out, total


# --- derivado en disco -------------------------------------------------------------
def escribir_derivado(ruta: Path, filas_j: list[dict], columnas: list[str]):
    with gzip.open(ruta, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(columnas)
        for r in filas_j:
            w.writerow([r.get(c, "") for c in columnas])


def leer_derivado(ruta: Path) -> list[dict]:
    with gzip.open(ruta, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


# --- índice ------------------------------------------------------------------------
def separar_direccion(direccion: str | None) -> tuple[str, str] | None:
    """«Avenida Italia 1299» → ("avenida italia", "1299")."""
    m = re.match(r"^(.*?)[\s,]+(\d{1,5})\b", normalizar(direccion or ""))
    return (m.group(1).strip(), m.group(2)) if m and m.group(1).strip() else None


class Indice:
    """Personas jurídicas indexadas por nombre normalizado y, si el archivo lo trae, por calle y altura."""

    def __init__(self, filas_j: list[dict], config):
        self.config = config
        self.por_nombre: dict[str, list[dict]] = {}
        self.por_direccion: dict[tuple[str, str], list[dict]] = {}
        for r in filas_j:
            n = nombre_normalizado(r.get("razon_social"), config)
            if n:
                self.por_nombre.setdefault(n, []).append(r)
            if r.get("domicilio_calle") and r.get("domicilio_altura"):
                clave = (normalizar(r["domicilio_calle"]), normalizar(r["domicilio_altura"]))
                self.por_direccion.setdefault(clave, []).append(r)
        self.claves = list(self.por_nombre)

    def __len__(self):
        return sum(len(v) for v in self.por_nombre.values())

    def buscar_nombre(self, nombre: str | None) -> tuple[list[dict], str | None]:
        """(filas posibles, método) por nombre exacto normalizado o, si no hay, similar por encima del umbral."""
        conf = self.config["padron"]
        n = nombre_normalizado(nombre, self.config)
        palabras = n.split()
        if len(n.replace(" ", "")) < conf["min_largo_nombre"] or (
                len(palabras) == 1 and len(n) < conf["min_largo_una_palabra"]):
            return [], None
        if n in self.por_nombre:
            return self.por_nombre[n], "exacto"
        similares = process.extract(n, self.claves, scorer=fuzz.token_set_ratio,
                                    score_cutoff=conf["umbral_nombre"], limit=10)
        # token_set_ratio da 100 si un nombre contiene al otro en cualquier sentido. Se acepta solo si todas las
        # palabras del candidato están en la razón social («Luna del Norte» ⊂ «Cafetería Luna del Norte SRL»),
        # o si el orden de palabras también coincide; no al revés («Castiello SA» ⊄ «Cucuza Castiello»).
        validas = [clave for clave, _, _ in similares
                   if set(palabras) <= set(clave.split()) or fuzz.token_sort_ratio(n, clave) >= conf["umbral_orden"]]
        return [r for clave in validas for r in self.por_nombre[clave]], "similar"

    def buscar_direccion(self, direccion: str | None) -> list[dict]:
        partes = separar_direccion(direccion)
        return self.por_direccion.get(partes, []) if partes and self.por_direccion else []
