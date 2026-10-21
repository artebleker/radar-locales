"""Carga de config.yaml y utilidades de tiempo y rutas."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

RAIZ = Path(__file__).resolve().parent.parent


class Config(dict):
    """La config es un dict con algunos atajos."""

    def ruta(self, clave: str) -> Path:
        p = RAIZ / self["rutas"][clave]
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self["proyecto"]["zona_horaria"])

    def ahora(self) -> datetime:
        return datetime.now(self.tz)

    def partidos(self, solo_activos: bool = True) -> list[dict]:
        return [p for p in self["partidos"] if p.get("activo") or not solo_activos]


def cargar(ruta: str | Path | None = None) -> Config:
    ruta = Path(ruta) if ruta else RAIZ / "config.yaml"
    with open(ruta, encoding="utf-8") as f:
        return Config(yaml.safe_load(f))
