"""Línea de comandos: radar bootstrap | run | record | serve | report."""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
import time
from collections import Counter

from . import config as cfg
from . import ejecutar, enriquecer_cuit, geo, historial, publicar
from .padron import descargar as padron_descargar
from .padron.parsear import Indice
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

    fuera = geo.descargar_fuera_de_zona(config, cliente)
    ruta = geo.guardar_fuera_de_zona(config, fuera)
    print(f"  {len(fuera)} lugares fuera de zona (otros partidos y barrios de CABA) → {ruta.relative_to(cfg.RAIZ)}\n")

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

    from .fuentes import osm
    if osm.leer_snapshot(config)[1] is None:
        print("\nArmando el primer snapshot de OSM (creaciones de los últimos "
              f"{config['osm']['ventana_creacion_dias']} días)…")
        senales, salud = ejecutar.recolectar(config, ["osm"])
        ejecutar.guardar_corrida(config, senales, salud)
        resumen_senales(senales, salud, ejemplos=0)
    return 0


def resumen_senales(senales: list, salud: list[dict], ejemplos: int = 10):
    print("\nSalud de fuentes:")
    for e in salud:
        estado = f"{e['senales']} señales" if e["ok"] else f"FALLÓ — {e['error']}"
        print(f"  {e['fuente']:<18}{estado}  ({e['segundos']} s)")
    if not senales:
        return
    print("\nPor tipo:", ", ".join(f"{k} {v}" for k, v in Counter(s.tipo_senal for s in senales).most_common()))
    rubros = sorted({s.rubro for s in senales})
    tabla = Counter((s.partido, s.rubro) for s in senales)
    ancho = 12
    print(f"\n{'Partido':<22}" + "".join(f"{r[:ancho - 1]:>{ancho}}" for r in rubros) + f"{'Total':>8}")
    for p in sorted({s.partido for s in senales}, key=lambda x: x or ""):
        fila = [tabla[(p, r)] for r in rubros]
        print(f"{p or '(sin partido)':<22}" + "".join(f"{n:>{ancho}}" for n in fila) + f"{sum(fila):>8}")
    print(f"{'Total':<22}" + "".join(f"{sum(tabla[(p, r)] for p in {s.partido for s in senales}):>{ancho}}"
                                      for r in rubros) + f"{len(senales):>8}")
    print(f"\n{ejemplos} ejemplos al azar:")
    for s in random.Random(0).sample(senales, min(ejemplos, len(senales))):
        print(f"  [{s.tipo_senal}] {s.nombre or '(sin nombre)'} — {s.rubro} — {s.partido}"
              f"{' — ' + s.direccion if s.direccion else ''}\n      {s.detalle}\n      {s.url}")


def cmd_run(config, args) -> int:
    pedidas = args.fuentes.split(",") if args.fuentes else None
    ahora = config.ahora()
    hoy = ahora.date().isoformat()
    senales, salud = ejecutar.recolectar(config, pedidas, args.limite, args.dry_run)
    resumen_senales(senales, salud)

    indice, cuits_nuevos = paso_padron(config, salud, ahora.date(), args.dry_run)

    entradas = historial.actualizar(config, historial.cargar(config), senales, hoy)
    activas = historial.senales_activas(entradas, hoy, config["publicacion"]["historial_dias"])
    candidatos = publicar.unificar(activas, config, hoy)
    if indice is not None:
        asignados = enriquecer_cuit.enriquecer(candidatos, indice, config, cuits_nuevos, geo.cargar_localidades(config))
        salud[-1]["senales"] = asignados
        print(f"Padrón ARCA: {asignados} candidatos con CUIT de persona jurídica "
              f"({sum(c.get('coincidencia') == 'ambigua' for c in candidatos)} ambiguos sin asignar)")
    vigentes = [c for c in candidatos if c["vigente"]]
    print(f"\nUnificación: {len(activas)} señales en historial → {len(candidatos)} candidatos "
          f"({len(vigentes)} vigentes; {Counter(c['confianza'] for c in vigentes)})")
    if args.dry_run:
        print("--dry-run: no se escribió historial, snapshots ni site/data.")
    else:
        ejecutar.guardar_corrida(config, senales, salud)
        historial.guardar(config, entradas, hoy)
        rutas = publicar.publicar(config, candidatos, salud, ahora)
        print("Publicado: " + ", ".join(str(r.relative_to(cfg.RAIZ)) for r in rutas))
    return 0 if any(e["ok"] for e in salud) else 1


def paso_padron(config, salud: list[dict], hoy, dry_run: bool):
    """Actualiza (si toca) y carga el padrón. Si falla, lo registra en la salud y la corrida sigue."""
    estado = {"fuente": "padron", "tipo": "enriquecimiento", "url": config["padron"]["url"],
              "licencia": "Datos públicos de ARCA; solo personas jurídicas", "ok": True, "error": None,
              "senales": 0, "avisos": [], "detalle": {}, "segundos": 0}
    if not config["padron"].get("activa", True):
        return None, None
    salud.append(estado)
    t0 = time.monotonic()
    error = None
    if not dry_run:
        try:
            res = padron_descargar.actualizar(config, Cliente(config), hoy)
            estado["detalle"] = {"descarga": res["accion"], "periodo": (res.get("estado") or {}).get("periodo")}
        except Exception as e:  # noqa: BLE001 — se conserva el padrón anterior y la corrida sigue
            error = f"{type(e).__name__}: {e}"
    actual, anterior = padron_descargar.cargar_actual_y_anterior(config)
    estado["segundos"] = round(time.monotonic() - t0, 1)
    if error:
        estado.update(ok=False, error=error + (" (se usa el padrón anterior)" if actual else ""))
    if actual is None:
        if not error:
            estado.update(ok=False, error="no hay padrón local (correr `radar padron`)")
        return None, None
    estado["detalle"]["personas_juridicas"] = len(actual)
    nuevos = {f["cuit"] for f in enriquecer_cuit.altas(actual, anterior)} if anterior else set()
    return Indice(actual, config), nuevos


def cmd_padron(config, args) -> int:
    """Fuerza la descarga del padrón de ARCA (ignora frecuencia_dias)."""
    res = padron_descargar.actualizar(config, Cliente(config), config.ahora().date(), forzar=True)
    e = res["estado"]
    miles = lambda n: f"{n:,}".replace(",", ".")  # noqa: E731
    print(f"Padrón: {res['accion']} · período {e['periodo']} · {miles(e['filas_total'])} filas leídas, "
          f"{miles(e['filas_juridicas'])} personas jurídicas guardadas (las físicas se descartan)")
    return 0


def cmd_altas_cuit(config, args) -> int:
    """CSV privado con los CUIT de personas jurídicas nuevos entre los dos últimos padrones."""
    import csv
    actual, anterior = padron_descargar.cargar_actual_y_anterior(config)
    if actual is None or anterior is None:
        print("Hacen falta dos padrones (mes actual y anterior) en data/padron_local/. Hay "
              f"{len(padron_descargar.derivados(config))}.")
        return 1
    nuevas = enriquecer_cuit.altas(actual, anterior)
    periodo = padron_descargar.derivados(config)[-1].name[:7]
    ruta = config.ruta("altas_cuit") / f"{periodo}.csv"
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cuit", "tipo_persona", "razon_social", "rubro", "domicilio", "fecha_inicio_actividades",
                    "condicion_iva", "empleador"])
        for r in nuevas:
            rubro = r.get("actividad_principal") or r.get("actividad_monotributo") or ""
            domicilio = " ".join(x for x in (r.get("domicilio_calle"), r.get("domicilio_altura")) if x)
            w.writerow([r["cuit"], "juridica", r.get("razon_social", ""), rubro, domicilio,
                        r.get("fecha_inicio_actividades", ""), r.get("iva", ""), r.get("empleador", "")])
    print(f"{len(nuevas)} altas de personas jurídicas → {ruta} (privado, no se commitea)")
    return 0


def cmd_report(config, args) -> int:
    datos = json.loads((config.ruta("site_data") / "candidatos.json").read_text(encoding="utf-8"))
    estado = json.loads((config.ruta("site_data") / "estado.json").read_text(encoding="utf-8"))
    cands = datos["candidatos"]
    print(f"Actualizado: {estado['actualizado']} · {len(cands)} candidatos vigentes (ventana {max(estado['ventanas_dias'])} días)\n")
    print("Salud de la última corrida:")
    for e in estado["salud"]:
        print(f"  {e['fuente']:<14}{'OK ' if e['ok'] else 'FALLÓ'} {e['senales']:>4} señales"
              + (f"  avisos: {len(e['avisos'])}" if e.get("avisos") else "") + (f"  {e['error']}" if e["error"] else ""))
    for titulo, clave_fn in [("fuente", lambda c: c["fuentes"]), ("partido", lambda c: [c["partido"] or "(sin partido)"]),
                             ("rubro", lambda c: [c["rubro"]]), ("confianza", lambda c: [c["confianza"]]),
                             ("estado", lambda c: [c["estado"]])]:
        cnt = Counter(v for c in cands for v in clave_fn(c))
        print(f"\nPor {titulo}: " + ", ".join(f"{k} {v}" for k, v in cnt.most_common()))
    print("\nMuestra aleatoria de 15 para revisión manual:")
    for c in random.Random().sample(cands, min(15, len(cands))):
        s = c["senales"][0]
        print(f"  [{c['confianza']} {c['puntaje']:>3}] {c['nombre'] or '(sin nombre)'} — {c['rubro']} — "
              f"{c['localidad'] or c['partido']} — {c['estado']} {c['fecha_estimada']} ({c['precision_fecha']})\n"
              f"      {', '.join(c['fuentes'])}: {s['detalle']}\n      {s['url']}")
    return 0


def _sin_contactos(obj):
    """Quita teléfonos y emails antes de grabar fixtures (pueden ser de franquiciados particulares)."""
    if isinstance(obj, dict):
        return {k: _sin_contactos(v) for k, v in obj.items()
                if not re.search(r"phone|tel[eé]fono|^tel$|e?mail|contact", k, re.IGNORECASE)}
    if isinstance(obj, list):
        return [_sin_contactos(x) for x in obj]
    return obj


def cmd_record(config, args) -> int:
    """Graba una muestra real y acotada de la respuesta de la fuente para las pruebas offline."""
    destino = config.ruta("fixtures") / args.fuente
    destino.mkdir(parents=True, exist_ok=True)
    cliente = Cliente(config)
    if args.fuente == "osm":
        from .fuentes import osm
        datos = osm.descargar(config, cliente, geo.Limites(config))
        elems = datos["elements"]
        # Muestra estratificada: algunos de cada etiqueta principal, más todos los v1 y los "por abrir".
        por_tag: dict[str, list] = {}
        for e in elems:
            p = osm.principal(e.get("tags") or {}, config)
            if p:
                por_tag.setdefault(p, []).append(e)
        muestra = [e for grupo in por_tag.values() for e in grupo[:3]]
        muestra += [e for e in elems if e.get("version") == 1 and e not in muestra][:50]
        for e in muestra:  # no se graban datos de usuarios de OSM
            e.pop("user", None)
            e.pop("uid", None)
        datos["elements"] = muestra
        ruta = destino / "overpass_muestra.json"
        ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=0), encoding="utf-8")
        print(f"{len(muestra)} de {len(elems)} elementos → {ruta.relative_to(cfg.RAIZ)}")
        return 0
    if args.fuente == "medios_rss":
        from .fuentes import medios_rss
        notas, errores = medios_rss.descargar(config, cliente)
        # Derechos: solo título, medio, fecha, link y categorías; el resumen del medio no se graba.
        guardar = [{"medio": n["medio"], "titulo": n["titulo"], "link": n["link"],
                    "fecha_publicacion": n["fecha_publicacion"].isoformat() if n["fecha_publicacion"] else None,
                    "categorias": n["categorias"], "partido_defecto": n["partido_defecto"]} for n in notas]
        ruta = destino / "notas.json"
        ruta.write_text(json.dumps(guardar, ensure_ascii=False, indent=0), encoding="utf-8")
        print(f"{len(guardar)} notas → {ruta.relative_to(cfg.RAIZ)}; feeds con error: {errores or 'ninguno'}")
        return 0
    if args.fuente == "directorios":
        from bs4 import BeautifulSoup
        for sitio in config["directorios"]["sitios"]:
            url = sitio["paginas"][0]["url"].format(n=0)
            sopa = BeautifulSoup(cliente.pedir(url).text, "html.parser")
            for tag in sopa(["script", "style", "svg", "head", "noscript", "iframe"]):
                tag.decompose()
            ruta = destino / f"{sitio['id']}.html"
            ruta.write_text(f"<!-- {url} -->\n" + str(sopa), encoding="utf-8")
            print(f"{sitio['nombre']}: {ruta.stat().st_size // 1024} KB → {ruta.relative_to(cfg.RAIZ)}")
        return 0
    if args.fuente == "sucursales":
        from .fuentes import sucursales
        limites = geo.Limites(config)
        for cadena in config["sucursales"]["cadenas"]:
            capturas = []
            original = cliente.pedir
            cliente.pedir = lambda *a, **k: capturas.append(original(*a, **k)) or capturas[-1]
            try:
                sucursales.ADAPTADORES[cadena["tipo"]](config, cliente, cadena, limites)
            finally:
                cliente.pedir = original
            texto = capturas[0].text
            if cadena["tipo"] == "next_data":  # solo el JSON embebido, no la página entera
                texto = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', texto, re.S).group(1)
                texto = ('<script id="__NEXT_DATA__" type="application/json">'
                         + json.dumps(_sin_contactos(json.loads(texto)), ensure_ascii=False) + "</script>")
            else:
                texto = json.dumps(_sin_contactos(json.loads(texto)), ensure_ascii=False)
            ruta = destino / f"{cadena['id']}.{'html' if cadena['tipo'] == 'next_data' else 'json'}"
            ruta.write_text(texto, encoding="utf-8")
            print(f"{cadena['nombre']}: {len(texto) // 1024} KB → {ruta.relative_to(cfg.RAIZ)}")
        return 0
    print(f"record no implementado para {args.fuente}")
    return 1


def cmd_serve(config, args) -> int:
    import functools
    import http.server
    sitio = cfg.RAIZ / "site"
    manejador = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(sitio))
    with http.server.ThreadingHTTPServer(("0.0.0.0", args.puerto), manejador) as srv:
        print(f"Sirviendo {sitio.relative_to(cfg.RAIZ)}/ en http://localhost:{args.puerto} (Ctrl+C para cortar).")
        print("Desde el celular, en la misma red Wi-Fi: http://<IP-de-esta-computadora>:" + str(args.puerto))
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


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
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("record", help="graba respuestas reales en tests/fixtures/")
    p.add_argument("--fuente", required=True)
    p.set_defaults(func=cmd_record)
    p = sub.add_parser("serve", help="sirve site/ en http://localhost:8000")
    p.add_argument("--puerto", type=int, default=8000)
    p.set_defaults(func=cmd_serve)
    sub.add_parser("report", help="totales y muestra aleatoria").set_defaults(func=cmd_report)
    sub.add_parser("padron", help="fuerza la descarga del padrón de ARCA").set_defaults(func=cmd_padron)
    sub.add_parser("altas-cuit", help="CSV privado con CUIT nuevos del mes").set_defaults(func=cmd_altas_cuit)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    return args.func(cfg.cargar(args.config), args)


if __name__ == "__main__":
    sys.exit(main())
