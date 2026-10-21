"""Línea de comandos: radar bootstrap | run | record | serve | report."""

from __future__ import annotations

import argparse
import logging
import sys

from . import config as cfg
from . import geo
from .http import Cliente


def cmd_bootstrap(config, args) -> int:
    cliente = Cliente(config)
    print("Descargando y verificando límites de partidos…")
    features = geo.descargar_limites(config, cliente)
    ruta = geo.guardar_limites(config, features)
    print(f"  {len(features)} partidos → {ruta.relative_to(cfg.RAIZ)}")

    print("Armando diccionario localidad → partido…")
    limites = geo.Limites(config, solo_activos=False)
    dicc = geo.descargar_localidades(config, cliente, limites)
    ruta = geo.guardar_localidades(config, dicc)
    print(f"  {len(dicc)} nombres → {ruta.relative_to(cfg.RAIZ)}\n")

    conteo = {p: 0 for p in limites.geoms}
    for ent in dicc.values():
        for p in ent["partidos"]:
            conteo[p] += 1
    ambiguos = [e["nombre"] for e in dicc.values() if len(e["partidos"]) > 1]
    print(f"{'Partido':<22}{'Relación OSM':>14}{'Localidades':>13}  Activo")
    for p in config.partidos(solo_activos=False):
        print(f"{p['nombre']:<22}{p['relacion']:>14}{conteo.get(p['nombre'], 0):>13}  {'sí' if p['activo'] else 'no'}")
    if ambiguos:
        print(f"\nNombres en más de un partido ({len(ambiguos)}): {', '.join(sorted(ambiguos))}")
    return 0


def pendiente(fase: str):
    def _cmd(config, args) -> int:
        print(f"Comando pendiente: se implementa en la fase {fase}.")
        return 1
    return _cmd


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="radar", description="Radar de aperturas comerciales — Zona Norte GBA")
    ap.add_argument("--config", help="ruta a config.yaml (por defecto, la del repo)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="comando", required=True)

    sub.add_parser("bootstrap", help="descarga límites y localidades").set_defaults(func=cmd_bootstrap)
    p = sub.add_parser("run", help="recolecta, deduplica, puntúa y genera site/data")
    p.add_argument("--fuentes", help="lista separada por comas (por defecto, todas las activas)")
    p.add_argument("--limite", type=int, help="máximo de señales por fuente (smoke test)")
    p.add_argument("--dry-run", action="store_true", help="no escribe snapshots ni site/data")
    p.set_defaults(func=pendiente("3-6"))
    p = sub.add_parser("record", help="graba respuestas reales en tests/fixtures/")
    p.add_argument("--fuente", required=True)
    p.set_defaults(func=pendiente("3"))
    p = sub.add_parser("serve", help="sirve site/ en http://localhost:8000")
    p.add_argument("--puerto", type=int, default=8000)
    p.set_defaults(func=pendiente("7"))
    sub.add_parser("report", help="totales y muestra aleatoria").set_defaults(func=pendiente("6"))

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    return args.func(cfg.cargar(args.config), args)


if __name__ == "__main__":
    sys.exit(main())
