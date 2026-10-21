"""Normalización de texto compartida por extracción, geo y dedupe."""

import re
import unicodedata


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalizar(s: str) -> str:
    """Minúsculas, sin tildes, sin puntuación y con espacios simples."""
    s = sin_tildes(s or "").lower()
    s = re.sub(r"[^a-z0-9ñ ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()
