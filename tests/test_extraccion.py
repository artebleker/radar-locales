"""Extracción por reglas: titulares reales grabados (2026-10-20) y casos de ruido conocidos."""

import json
from datetime import date
from pathlib import Path

import pytest

from radar import config as cfg
from radar import extraccion, geo

CONFIG = cfg.cargar()
HOY = date(2026, 10, 20)
NOTAS = Path(__file__).parent / "fixtures" / "medios_rss" / "notas.json"


@pytest.fixture(scope="module")
def ext():
    return extraccion.Extractor(CONFIG, geo.cargar_localidades(CONFIG))


def nota(titulo, fecha="2026-10-15", partido_defecto=None, categorias=()):
    return {"medio": "Test", "titulo": titulo, "link": "https://ejemplo.com/n?utm_source=x",
            "fecha_publicacion": date.fromisoformat(fecha), "categorias": list(categorias),
            "partido_defecto": partido_defecto, "resumen": ""}


def senal(ext, titulo, **kw):
    return ext.senal_de_nota(nota(titulo, **kw), HOY, "medios_rss")


# --- titulares reales ----------------------------------------------------------
@pytest.fixture(scope="module")
def senales_reales(ext):
    notas = json.loads(NOTAS.read_text(encoding="utf-8"))
    for n in notas:
        n["fecha_publicacion"] = date.fromisoformat(n["fecha_publicacion"]) if n["fecha_publicacion"] else None
    return [s for n in notas if (s := ext.senal_de_nota(n, HOY, "medios_rss"))]


def test_fixture_no_guarda_cuerpo_de_notas():
    assert all("resumen" not in n for n in json.loads(NOTAS.read_text(encoding="utf-8")))


@pytest.mark.parametrize("nombre,partido,estado", [
    ("Skinko", "Tigre", "abrio"),
    ("SportClub", "Tigre", "abrio"),
    ("Mr. Tasty", "Escobar", "por_abrir"),
    ("PedidosYa Market", "Escobar", "abrio"),
])
def test_aperturas_reales_detectadas(senales_reales, nombre, partido, estado):
    s = next(s for s in senales_reales if s.nombre == nombre)
    assert (s.partido, s.extra["estado_sugerido"]) == (partido, estado)


def test_sportclub_con_fecha_anunciada(senales_reales):
    s = next(s for s in senales_reales if s.nombre == "SportClub")
    assert (s.fecha_evento, s.precision_fecha) == ("2026-10-17", "exacta")


@pytest.mark.parametrize("fragmento", [
    "Kicillof inauguró", "San Isidro Jazz", "La línea 333", "Plaza Ciudad del Delta", "Lisandro Aristimuño",
    "Fiesta Nacional de la Flor", "convocatoria laboral en Ezeiza", "estación Tribunales", "Las Lomas se suma",
])
def test_ruido_real_descartado(senales_reales, fragmento):
    assert not [s for s in senales_reales if fragmento.lower() in s.titulo_fuente.lower()]


def test_link_sin_parametros_de_seguimiento(ext):
    assert "utm_" not in senal(ext, "Abrió una nueva cafetería en Olivos").url


# --- ruido conocido --------------------------------------------------------------
@pytest.mark.parametrize("titulo", [
    "Inauguraron un nuevo local partidario en Pilar",
    "La agrupación abrió una unidad básica en Garín",
    "Tigre inauguró un nuevo centro de monitoreo en Benavídez",
    "Abre una nueva escuela secundaria en Del Viso",
    "San Fernando inauguró la plaza renovada de Victoria",
    "Inauguran el hospital de Malvinas Argentinas",
    "Abrió la nueva comisaría de Martínez",
    "El teatro de Olivos abre su temporada",
    "Inauguró la obra de pavimentación en Escobar",
    "Abrió una heladería en Pilar, Córdoba",
    "San Martín de los Andes: abre un nuevo local de Grido",
    "Abre una nueva farmacia en San Isidro de Lules",
    "Abrió una cafetería en Rosario",
])
def test_ruido_descartado(ext, titulo):
    assert senal(ext, titulo) is None


def test_calle_san_martin_no_ubica_en_el_partido(ext):
    s = senal(ext, "Abrió una nueva cafetería en Av. San Martín 500")
    assert s.partido is None and "partido_dudoso" in s.extra["penalizaciones"]


def test_partido_del_medio_si_la_nota_no_nombra_lugar(ext):
    s = senal(ext, "Abrió una nueva ferretería en el centro", partido_defecto="Pilar")
    assert s.partido == "Pilar" and "partido_del_medio" in s.extra["penalizaciones"]


def test_nota_vieja_reflotada(ext):
    s = senal(ext, "En 2019 abrió su local Café Tortoni en Martínez")
    assert "menciona_anio_viejo" in s.extra["penalizaciones"]


def test_exclusion_debil_penaliza_sin_descartar(ext):
    s = senal(ext, "El intendente recorrió el nuevo local de Carrefour en Beccar")
    assert s and any(p.startswith("exclusion_debil") for p in s.extra["penalizaciones"])


def test_categoria_de_agenda_descarta(ext):
    assert senal(ext, "Llega Ritual a Tigre con un nuevo local", categorias=["Agenda Cultural"]) is None


# --- nombre, lugar, rubro, fecha ----------------------------------------------------
@pytest.mark.parametrize("titulo,nombre,partido,localidad", [
    ("Llega Grido a Del Viso con su nuevo local", "Grido", "Pilar", "Del Viso"),
    ("Abrió «La Esquina de Pepe» en Olivos", "La Esquina de Pepe", "Vicente López", "Olivos"),
    ("Nueva sucursal de Farmacity en Martínez", "Farmacity", "San Isidro", "Martínez"),
    ("Nordelta: Skinko inauguró su local", "Skinko", "Tigre", "Nordelta"),
    ("Abrió una nueva verdulería en Villa Ballester", None, "San Martín", None),
])
def test_nombre_y_lugar(ext, titulo, nombre, partido, localidad):
    s = senal(ext, titulo)
    assert (s.nombre, s.partido) == (nombre, partido)
    if localidad:
        assert s.localidad == localidad


@pytest.mark.parametrize("titulo,rubro", [
    ("Abrió una nueva heladería en Olivos", "Gastronomía"),
    ("Abre una ferretería en Garín", "Hogar y construcción"),
    ("Nueva sucursal de zapatillas en Tortuguitas", "Indumentaria y calzado"),
    ("Inauguró un gimnasio en Munro", "Otros"),
])
def test_rubro(ext, titulo, rubro):
    assert senal(ext, titulo).rubro == rubro


@pytest.mark.parametrize("texto,ref,esperado", [
    ("inaugura el 23 de octubre", "2026-10-10", ("2026-10-23", "exacta")),
    ("abre el 15 de enero", "2026-12-01", ("2027-01-15", "exacta")),
    ("abre el 3 de marzo de 2027", "2026-12-01", ("2027-03-03", "exacta")),
    ("abre este jueves", "2026-10-19", ("2026-10-22", "inferida")),
    ("abre manana", "2026-10-19", ("2026-10-20", "inferida")),
    ("abre en noviembre", "2026-10-19", ("2026-11-01", "inferida")),
    ("abre pronto", "2026-10-19", (None, "sin_fecha")),
])
def test_fecha(ext, texto, ref, esperado):
    assert ext.fecha(texto, date.fromisoformat(ref)) == esperado


@pytest.mark.parametrize("titulo,estado", [
    ("Café Martínez abrirá un local en Pilar", "por_abrir"),
    ("Café Martínez inauguró un local en Pilar", "abrio"),
    ("Café Martínez inaugura su local el 30 de octubre en Pilar", "por_abrir"),
    ("Café Martínez inaugura su local el 18 de octubre en Pilar", "abrio"),
])
def test_estado_sugerido(ext, titulo, estado):
    assert senal(ext, titulo).extra["estado_sugerido"] == estado


def test_nombre_neutro_no_ubica_ni_descarta(ext):
    s = senal(ext, "Abrió una pizzería frente al Club Atlético Tigre, en Victoria")
    assert s is not None and s.partido == "San Fernando"


def test_nombre_oficial_del_partido(ext):
    assert senal(ext, "Abrió una nueva librería en General San Martín").partido == "San Martín"
