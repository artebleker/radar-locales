"""Modelo de datos: Señal (lo que devuelve una fuente)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

TIPOS_SENAL = {"alta_osm", "creacion_osm", "por_abrir_osm", "cambio_osm", "baja_osm", "nota_prensa",
               "alta_directorio", "alta_sucursal", "corroboracion_arca"}
PRECISIONES = {"exacta", "inferida", "deteccion", "sin_fecha"}


@dataclass
class Senal:
    fuente: str
    tipo_senal: str
    nombre: str | None
    rubro: str
    partido: str | None
    detectado_el: str                       # YYYY-MM-DD, cuándo lo vio el radar
    url: str
    localidad: str | None = None
    direccion: str | None = None
    lat: float | None = None
    lon: float | None = None
    fecha_evento: str | None = None         # apertura (pasada o anunciada), si se conoce
    precision_fecha: str = "sin_fecha"
    titulo_fuente: str | None = None
    fecha_publicacion: str | None = None    # fecha de la nota o publicación
    fecha_registro: str | None = None       # alta/modificación del registro en la fuente (ej. timestamp OSM)
    id_externo: str | None = None           # ej. osm:node/123
    detalle: str | None = None              # explicación legible de por qué es señal
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.tipo_senal not in TIPOS_SENAL:
            raise ValueError(f"tipo_senal desconocido: {self.tipo_senal}")
        if self.precision_fecha not in PRECISIONES:
            raise ValueError(f"precision_fecha desconocida: {self.precision_fecha}")

    def a_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def de_dict(cls, d: dict) -> "Senal":
        return cls(**d)
