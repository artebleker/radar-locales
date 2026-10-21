"""Extracción por reglas (sin IA) de señales de apertura a partir de títulos de notas.

Pasos: verbo de apertura en el título → exclusiones fuertes → ubicación (localidades de la zona,
descartando calles, homónimos y lugares fuera de zona) → contexto comercial → nombre → fecha → rubro.
Lo dudoso no se descarta: se anota en `extra["penalizaciones"]` para que el puntaje lo baje.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, timedelta

from .geo import cargar_fuera_de_zona, nombres_localidades
from .modelos import Senal
from .rubros import OTROS, rubro_por_palabras
from .texto import normalizar, sin_tildes

MESES = {m: i for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                     "septiembre", "octubre", "noviembre", "diciembre"], 1)}
MESES["setiembre"] = 9
DIAS = {d: i for i, d in enumerate(["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"])}
ARTICULOS = {"el", "la", "los", "las", "un", "una", "unos", "unas"}
CONECTORES = {"de", "del", "la", "las", "los", "y", "&", "e", "en"}
MAX_PALABRAS_LUGAR = 6


def _frase(p: str) -> str:
    """Regex de frase normalizada con límites de palabra."""
    return r"(?<![a-z0-9])" + re.escape(normalizar(p)) + r"(?![a-z0-9])"


def _alternativa(palabras) -> re.Pattern:
    return re.compile("|".join(_frase(p) for p in sorted(set(palabras), key=len, reverse=True)))


class Extractor:
    def __init__(self, config, localidades: dict[str, list[str]]):
        ex = config["extraccion"]
        self.config = config
        self.localidades = localidades
        self.nombres = nombres_localidades(config)
        self.fuera = cargar_fuera_de_zona(config)
        self.re_pasado = _alternativa(ex["verbos_pasado"])
        self.re_futuro = _alternativa(ex["verbos_futuro"])
        self.re_excl = _alternativa(ex["exclusiones"])
        self.re_excl_debil = _alternativa(ex["exclusiones_debiles"])
        palabras_rubro = [p for r, reg in config["rubros"].items() for p in reg.get("palabras") or []]
        self.re_comercial = _alternativa(ex["contexto_comercial"] + palabras_rubro)
        self.re_homonimos = _alternativa(ex["homonimos"])
        self.re_neutros = _alternativa(ex["nombres_neutros"])
        self.calle = {normalizar(p) for p in ex["palabras_calle"]}

    # --- verbo -------------------------------------------------------------
    def verbo(self, texto_n: str) -> tuple[str, str] | None:
        """Primer verbo de apertura del texto normalizado → (verbo, 'pasado'|'futuro')."""
        hallados = [(m.start(), m.group(), t) for t, r in (("pasado", self.re_pasado), ("futuro", self.re_futuro))
                    for m in r.finditer(texto_n)]
        if not hallados:
            return None
        _, v, t = min(hallados)
        return v, t

    # --- ubicación ---------------------------------------------------------
    def _lugares(self, texto_n: str, dicc) -> list[tuple[int, str]]:
        """Nombres de `dicc` presentes en el texto, sin contar calles ni homónimos (más largo primero)."""
        texto_n = self.re_neutros.sub(" § ", texto_n)
        tokens = texto_n.split()
        hallados, i = [], 0
        while i < len(tokens):
            for largo in range(min(MAX_PALABRAS_LUGAR, len(tokens) - i), 0, -1):
                cand = " ".join(tokens[i:i + largo])
                if cand in dicc:
                    if not (i > 0 and tokens[i - 1] in self.calle):
                        hallados.append((i, cand))
                    i += largo - 1
                    break
            i += 1
        return hallados

    def ubicar(self, titulo_n: str, resumen_n: str) -> tuple[str | None, str | None, str]:
        """(partido, localidad, motivo). motivo: titulo | resumen | fuera | ninguno."""
        if self.re_homonimos.search(titulo_n):  # «Pilar, Córdoba», «San Martín de los Andes»…
            return None, None, "fuera"
        for texto in (titulo_n, resumen_n):
            zona = self._lugares(texto, self.localidades)
            if zona:
                _, clave = zona[0]
                return self.localidades[clave][0], clave, "titulo" if texto is titulo_n else "resumen"
            if texto is titulo_n and self._lugares(texto, self.fuera):
                return None, None, "fuera"
        return None, None, "ninguno"

    # --- nombre ------------------------------------------------------------
    def _parece_nombre(self, s: str) -> bool:
        palabras = [p for p in re.split(r"\s+", s.strip()) if p]
        if not 1 <= len(palabras) <= 6:
            return False
        while palabras and palabras[0].lower() in ARTICULOS:
            palabras = palabras[1:]
        if not palabras or not (palabras[0][0].isupper() or palabras[0][0].isdigit()):
            return False
        llenas = [p for p in palabras if p.lower() not in CONECTORES]
        mayus = sum(1 for p in llenas if p[0].isupper() or p[0].isdigit())
        n = normalizar(s)
        if n in self.localidades or n in self.fuera or self.re_excl_debil.search(n):
            return False
        return mayus * 2 >= len(llenas)

    def nombre(self, titulo: str, verbo_n: str) -> str | None:
        t = unicodedata.normalize("NFC", titulo)
        bajo = sin_tildes(t).lower()  # misma longitud que t: permite ubicar el verbo en el original
        # «Nordelta: Skinko inauguró…» → se saca el prefijo de lugar
        m = re.match(r"^([^:]{2,40}):\s+", t)
        if m and (normalizar(m.group(1)) in self.localidades or len(m.group(1).split()) <= 3):
            t, bajo = t[m.end():], bajo[m.end():]
        mv = re.search(r"(?<![a-z0-9])" + re.escape(verbo_n).replace(r"\ ", r"\s+") + r"(?![a-z0-9])", bajo)

        candidatos = []
        q = re.search(r"[«“\"']([^»”\"']{2,40})[»”\"']", t)
        if q and self._parece_nombre(q.group(1)):
            return q.group(1).strip()  # entre comillas, el artículo es parte del nombre
        if mv:
            antes = t[:mv.start()].strip(" :,;-–—")
            if antes:
                candidatos.append(antes)
            despues = t[mv.end():]
            m2 = re.match(r"\s+((?:[A-ZÁÉÍÓÚÑ0-9][\w'’&.\-]*|de|del|y|&)(?:\s+(?:[A-ZÁÉÍÓÚÑ0-9][\w'’&.\-]*|de|del|&))*)",
                          despues)
            if m2:
                candidatos.append(re.sub(r"\s+(de|del|y|&)$", "", m2.group(1)))
        m3 = re.search(r"(?:nuevo local|nueva sucursal|nueva tienda|apertura|desembarco)\s+de\s+([A-ZÁÉÍÓÚÑ0-9][^,.:;]{1,40})", t,
                       flags=re.IGNORECASE)
        if m3:
            candidatos.append(m3.group(1).split(" en ")[0])
        for c in candidatos:
            c = c.strip(" :,;-–—«»“”\"'")
            if self._parece_nombre(c):
                palabras = c.split()
                while palabras and palabras[0].lower() in ARTICULOS:
                    palabras = palabras[1:]
                return " ".join(palabras)
        return None

    # --- fecha -------------------------------------------------------------
    @staticmethod
    def _anio(mes: int, dia: int, ref: date) -> date | None:
        try:
            f = date(ref.year, mes, dia)
        except ValueError:
            return None
        return date(ref.year + 1, mes, dia) if f < ref - timedelta(days=60) else f

    def fecha(self, texto_n: str, ref: date) -> tuple[str | None, str]:
        """Fecha anunciada en el texto, con la fecha de la nota como referencia."""
        m = re.search(r"(\d{1,2}) de (" + "|".join(MESES) + r")(?: de (\d{4}))?", texto_n)
        if m:
            dia, mes = int(m.group(1)), MESES[m.group(2)]
            f = date(int(m.group(3)), mes, dia) if m.group(3) else self._anio(mes, dia, ref)
            if f:
                return f.isoformat(), "exacta"
        m = re.search(r"(?:este|el proximo|proximo|el) (" + "|".join(DIAS) + r")\b", texto_n)
        if m:
            delta = (DIAS[m.group(1)] - ref.weekday()) % 7
            return (ref + timedelta(days=delta)).isoformat(), "inferida"
        if re.search(r"\bfin de semana\b", texto_n):
            return (ref + timedelta(days=(5 - ref.weekday()) % 7)).isoformat(), "inferida"
        if re.search(r"\b(desde |a partir de )?manana\b", texto_n) and "por la manana" not in texto_n:
            return (ref + timedelta(days=1)).isoformat(), "inferida"
        m = re.search(r"\b(?:en|a partir de|desde|para) (" + "|".join(MESES) + r")\b", texto_n)
        if m:
            f = self._anio(MESES[m.group(1)], 1, ref)
            return f.isoformat(), "inferida"
        return None, "sin_fecha"

    # --- señal -------------------------------------------------------------
    def senal_de_nota(self, nota: dict, hoy: date, fuente: str) -> Senal | None:
        titulo = nota["titulo"]
        t_n, r_n = normalizar(titulo), normalizar(nota.get("resumen") or "")
        v = self.verbo(t_n)
        categorias_n = normalizar(" ".join(nota.get("categorias") or []))
        if not v or self.re_excl.search(t_n) or self.re_excl.search(categorias_n):
            return None
        partido, localidad, motivo = self.ubicar(t_n, r_n)
        if motivo == "fuera":
            return None
        pen = []
        if motivo == "ninguno":
            partido = nota.get("partido_defecto")
            pen.append("partido_del_medio" if partido else "partido_dudoso")
        elif motivo == "resumen":
            pen.append("lugar_solo_en_resumen")
        if localidad and len(self.localidades.get(localidad, [])) > 1:
            pen.append("partido_dudoso")

        nombre = self.nombre(titulo, v[0])
        comercial = self.re_comercial.search(t_n) or self.re_comercial.search(r_n)
        if not comercial:
            if not (nombre and motivo == "titulo"):
                return None
            pen.append("sin_contexto_comercial")
        if not nombre:
            pen.append("sin_nombre")
        debil = self.re_excl_debil.search(t_n)
        if debil:
            pen.append(f"exclusion_debil:{debil.group()}")
        ref = nota.get("fecha_publicacion") or hoy
        if any(int(a) < ref.year for a in re.findall(r"\b(20\d\d)\b", t_n)):
            pen.append("menciona_anio_viejo")

        fecha, precision = self.fecha(t_n, ref)
        if fecha:
            estado = "abrio" if fecha <= hoy.isoformat() else "por_abrir"
        else:
            estado = "abrio" if v[1] == "pasado" else "por_abrir"
        rubro = (rubro_por_palabras(f"{titulo} {' '.join(nota.get('categorias') or [])}", self.config)
                 or rubro_por_palabras(r_n, self.config) or OTROS)

        link = re.sub(r"[?&]utm_[^&]+", "", nota["link"])
        return Senal(
            fuente=fuente, tipo_senal="nota_prensa", nombre=nombre, rubro=rubro, partido=partido,
            localidad=self.nombres.get(localidad, localidad) if localidad else None, detectado_el=hoy.isoformat(),
            url=link, fecha_evento=fecha, precision_fecha=precision, titulo_fuente=titulo,
            fecha_publicacion=nota["fecha_publicacion"].isoformat() if nota.get("fecha_publicacion") else None,
            id_externo="nota:" + hashlib.sha1(link.encode()).hexdigest()[:12],
            detalle=f"Nota en {nota['medio']}: «{v[0]}»" + (f", fecha anunciada {fecha}" if fecha else ""),
            extra={"medio": nota["medio"], "estado_sugerido": estado, "verbo": v[0], "penalizaciones": pen},
        )
