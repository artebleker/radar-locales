/* Radar de aperturas — interfaz. JS vanilla; lee data/candidatos.json y data/estado.json.
   Todo texto que viene de las fuentes se inserta con textContent (nunca innerHTML). */
"use strict";

const ETIQUETAS = {
  estado: { por_abrir: "Por abrir", abrio: "Abrió", detectado: "Detectado" },
  confianza: { alta: "Alta", media: "Media", baja: "Baja" },
  fuente: { osm: "OpenStreetMap", medios_rss: "Medios locales", directorios: "Shoppings", sucursales: "Cadenas" },
  tipo: {
    creacion_osm: "Nuevo en OSM", alta_osm: "Apareció en OSM", por_abrir_osm: "Por abrir (OSM)",
    cambio_osm: "Cambio en OSM", baja_osm: "Desapareció de OSM", nota_prensa: "Nota de prensa",
    alta_directorio: "Nuevo en shopping", alta_sucursal: "Sucursal nueva", corroboracion_arca: "ARCA",
  },
  precision: { exacta: "fecha exacta", inferida: "fecha inferida", deteccion: "detección", sin_fecha: "sin fecha" },
  origen: { anunciada: "anunciada", publicacion: "según la nota", deteccion: "detectado por el radar" },
};
const NIVEL = { baja: 0, media: 1, alta: 2 };
const ORDEN_ESTADO = { por_abrir: 0, abrio: 1, detectado: 2 };

const estado = { datos: [], meta: null, filtrados: [], orden: { campo: "puntaje", asc: false }, mapa: null, capa: null, marcadores: new Map() };

/* ---------- utilidades ---------- */
function el(tag, attrs = {}, ...hijos) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const h of hijos.flat()) if (h !== null && h !== undefined && h !== false) n.append(h instanceof Node ? h : String(h));
  return n;
}
function fechaCorta(iso) {
  if (!iso) return "";
  const [a, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
}
function restarDias(iso, dias) {
  const f = new Date(iso + "T12:00:00");
  f.setDate(f.getDate() - dias);
  return f.toISOString().slice(0, 10);
}
function sinTildes(s) { return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
function guardar(clave, valor) { try { localStorage.setItem(clave, valor); } catch (_) { /* almacenamiento no disponible */ } }
function leer(clave) { try { return localStorage.getItem(clave); } catch (_) { return null; } }
function enlaceSeguro(url) {
  try { const u = new URL(url); return u.protocol === "https:" || u.protocol === "http:" ? u.href : null; } catch (_) { return null; }
}

/* ---------- tema ---------- */
function aplicarTema(tema) {
  if (tema === "light" || tema === "dark") document.documentElement.dataset.theme = tema;
  else delete document.documentElement.dataset.theme;
  document.getElementById("tema").textContent = "Tema: " + ({ light: "claro", dark: "oscuro" }[tema] || "auto");
}
function iniciarTema() {
  let tema = leer("radar-tema") || "auto";
  aplicarTema(tema);
  document.getElementById("tema").addEventListener("click", () => {
    tema = { auto: "light", light: "dark", dark: "auto" }[tema] || "auto";
    guardar("radar-tema", tema);
    aplicarTema(tema);
  });
}

/* ---------- filtros ---------- */
function leerFiltros() {
  const f = new FormData(document.getElementById("form-filtros"));
  return Object.fromEntries(f.entries());
}
function filtrar() {
  const f = leerFiltros();
  const hoy = estado.meta.hoy;
  const desde = restarDias(hoy, Number(f.ventana || estado.meta.ventana_defecto));
  const q = sinTildes(f.q).trim();
  estado.filtrados = estado.datos.filter((c) => {
    const futuro = c.estado === "por_abrir" && c.fecha_estimada > hoy;
    if (!(c.fecha_ventana >= desde || futuro)) return false;
    if (f.partido && c.partido !== f.partido) return false;
    if (f.rubro && c.rubro !== f.rubro) return false;
    if (f.estado && c.estado !== f.estado) return false;
    if (NIVEL[c.confianza] < NIVEL[f.confianza || "baja"]) return false;
    if (f.fuente && !c.fuentes.includes(f.fuente)) return false;
    if (q) {
      const texto = sinTildes([c.nombre, c.rubro, c.partido, c.localidad, c.direccion, ...c.senales.map((s) => s.titulo)].join(" "));
      if (!q.split(/\s+/).every((p) => texto.includes(p))) return false;
    }
    return true;
  });
  ordenar();
  const params = new URLSearchParams(Object.entries(f).filter(([k, v]) => v && !(k === "confianza" && v === "baja")));
  history.replaceState(null, "", params.toString() ? "#" + params : location.pathname);
  pintar();
}
function ordenar() {
  const { campo, asc } = estado.orden;
  const clave = {
    nombre: (c) => sinTildes(c.nombre || "~"),
    rubro: (c) => c.rubro,
    lugar: (c) => sinTildes(c.localidad || c.partido || "~"),
    estado: (c) => ORDEN_ESTADO[c.estado],
    fecha: (c) => c.fecha_estimada || "",
    puntaje: (c) => c.puntaje,
  }[campo];
  estado.filtrados.sort((a, b) => {
    const x = clave(a), y = clave(b);
    return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1) || (b.puntaje - a.puntaje);
  });
}

/* ---------- render ---------- */
function celdaSenales(c) {
  const lista = el("ul", { class: "senales" }, c.senales.map((s) => {
    const url = enlaceSeguro(s.url);
    const titulo = ETIQUETAS.tipo[s.tipo] || s.tipo;
    const medio = s.medio ? ` · ${s.medio}` : "";
    const fecha = s.fecha_publicacion ? ` · nota del ${fechaCorta(s.fecha_publicacion)}`
      : s.fecha_registro ? ` · OSM ${fechaCorta(s.fecha_registro)}` : "";
    return el("li", {},
      url ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, titulo) : titulo,
      el("span", { class: "mini" }, medio + fecha),
      s.titulo && s.tipo === "nota_prensa" ? el("span", { class: "secundario" }, "«" + s.titulo + "»") : null);
  }));
  const detalle = el("details", {},
    el("summary", {}, "Por qué y cómo verificar"),
    el("ul", { class: "senales mini" },
      c.senales.map((s) => el("li", {}, s.detalle || "")),
      el("li", {}, "Puntaje " + c.puntaje + ": " + c.motivos_puntaje.join(", ")),
      el("li", {}, "Visto por primera vez el " + fechaCorta(c.primera_deteccion) + ", última vez el " + fechaCorta(c.ultima_deteccion)),
      estado.meta.arca ? el("li", {}, el("a", { href: estado.meta.arca.url_constancia, target: "_blank", rel: "noopener noreferrer" },
        "Consultar constancia en ARCA"), " — " + estado.meta.arca.nota) : null));
  return el("td", { "data-titulo": "Señales" }, lista, detalle);
}

function fila(c) {
  const nombre = c.nombre ? el("span", { class: "nombre" }, c.nombre) : el("span", { class: "nombre nombre--vacio" }, "Sin nombre");
  const lugar = [c.localidad, c.partido].filter((x, i, a) => x && a.indexOf(x) === i).join(", ");
  const fecha = c.fecha_estimada ? fechaCorta(c.fecha_estimada) : "—";
  const precision = ETIQUETAS.precision[c.precision_fecha] + (c.origen_fecha && c.origen_fecha !== "deteccion" ? ", " + ETIQUETAS.origen[c.origen_fecha] : "");
  return el("tr", { id: "c-" + c.id },
    el("td", { "data-titulo": "Nombre" }, nombre,
      c.direccion ? el("span", { class: "secundario" }, c.direccion) : null,
      c.lat != null
        ? el("button", { type: "button", class: "ver-mapa", onclick: () => enfocar(c.id) }, "Ver en el mapa")
        : el("span", { class: "sin-mapa", title: "La fuente no informa coordenadas" }, "Sin ubicación en el mapa")),
    el("td", { "data-titulo": "Rubro" }, c.rubro),
    el("td", { "data-titulo": "Lugar" }, lugar || "—"),
    el("td", { "data-titulo": "Estado" }, el("span", { class: "etiqueta etiqueta--" + c.estado }, ETIQUETAS.estado[c.estado])),
    el("td", { "data-titulo": "Fecha" }, fecha, el("span", { class: "secundario" }, precision)),
    el("td", { "data-titulo": "Confianza" }, el("span", { class: "etiqueta etiqueta--" + c.confianza }, ETIQUETAS.confianza[c.confianza]),
      el("span", { class: "secundario" }, c.puntaje + "/100 · " + c.fuentes.map((f) => ETIQUETAS.fuente[f] || f).join(" + "))),
    celdaSenales(c));
}

function pintar() {
  const cuerpo = document.getElementById("filas");
  cuerpo.replaceChildren(...estado.filtrados.map(fila));
  document.getElementById("vacio").hidden = estado.filtrados.length > 0;
  const sinMapa = estado.filtrados.filter((c) => c.lat == null).length;
  document.getElementById("resultado").textContent =
    `${estado.filtrados.length} candidatos con estos filtros` + (sinMapa ? ` (${sinMapa} sin ubicación en el mapa)` : "") + ".";
  pintarMapa();
}

function pintarMapa() {
  if (!estado.mapa) return;
  estado.capa.clearLayers();
  estado.marcadores.clear();
  const css = getComputedStyle(document.documentElement);
  const puntos = [];
  for (const c of estado.filtrados) {
    if (c.lat == null) continue;
    const m = L.circleMarker([c.lat, c.lon], {
      radius: { alta: 10, media: 8, baja: 6 }[c.confianza],
      color: css.getPropertyValue("--superficie").trim() || "#fff", weight: 1.5,
      fillColor: css.getPropertyValue("--" + c.estado).trim(), fillOpacity: { alta: 0.95, media: 0.8, baja: 0.55 }[c.confianza],
    });
    const contenido = el("div", {},
      el("strong", {}, c.nombre || "Sin nombre"), el("br"),
      `${c.rubro} · ${ETIQUETAS.estado[c.estado]} · confianza ${ETIQUETAS.confianza[c.confianza].toLowerCase()}`, el("br"),
      el("a", { href: "#c-" + c.id, onclick: (e) => { e.preventDefault(); irAFila(c.id); } }, "Ver en la lista"));
    m.bindPopup(contenido);
    m.addTo(estado.capa);
    estado.marcadores.set(c.id, m);
    puntos.push([c.lat, c.lon]);
  }
  if (puntos.length) estado.mapa.fitBounds(puntos, { padding: [24, 24], maxZoom: 14 });
}

function enfocar(id) {
  const m = estado.marcadores.get(id);
  if (!m) return;
  document.getElementById("mapa").scrollIntoView({ behavior: "smooth", block: "center" });
  estado.mapa.setView(m.getLatLng(), 16);
  m.openPopup();
}
function irAFila(id) {
  const tr = document.getElementById("c-" + id);
  if (!tr) return;
  document.querySelectorAll("tr.resaltado").forEach((x) => x.classList.remove("resaltado"));
  tr.classList.add("resaltado");
  tr.scrollIntoView({ behavior: "smooth", block: "center" });
  tr.querySelector("a, button")?.focus({ preventScroll: true });
}

function pintarEncabezado() {
  const m = estado.meta;
  const fecha = new Date(m.actualizado);
  const texto = fecha.toLocaleString("es-AR", { timeZone: m.zona_horaria, dateStyle: "long", timeStyle: "short" });
  document.getElementById("actualizado").textContent = `Actualizado el ${texto} (hora de Buenos Aires).`;
  const t = m.totales_ventana;
  const items = [
    [t.candidatos, `en los últimos ${m.ventana_defecto} días`],
    [t.por_estado.por_abrir || 0, "por abrir"],
    [t.por_estado.abrio || 0, "abrieron"],
    [t.por_estado.detectado || 0, "detectados"],
    [t.por_confianza.alta || 0, "con confianza alta"],
  ];
  document.getElementById("totales").replaceChildren(...items.map(([n, txt]) => el("li", {}, el("strong", {}, n), txt)));
}

function pintarSalud() {
  const filas = estado.meta.salud.map((s) => {
    const detalle = [];
    const resumen = Object.entries(s.detalle || {}).map(([k, v]) => `${k}: ${v}`).join(" · ");
    if (resumen) detalle.push(el("span", { class: "secundario" }, resumen));
    for (const a of s.avisos || []) detalle.push(el("span", { class: "secundario fallo" }, "Aviso: " + a));
    if (s.error) detalle.push(el("span", { class: "secundario fallo" }, s.error));
    return el("tr", {},
      el("td", {}, ETIQUETAS.fuente[s.fuente] || s.fuente),
      el("td", {}, s.ok ? el("span", { class: "ok" }, "OK") : el("span", { class: "fallo" }, "Falló")),
      el("td", {}, String(s.senales)),
      el("td", {}, detalle.length ? detalle : "—"));
  });
  document.getElementById("salud").replaceChildren(...filas);
}

/* ---------- exportar ---------- */
function descargar(nombre, tipo, contenido) {
  const url = URL.createObjectURL(new Blob([contenido], { type: tipo }));
  const a = el("a", { href: url, download: nombre });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function exportarCSV() {
  const cols = ["id", "nombre", "rubro", "partido", "localidad", "direccion", "lat", "lon", "estado", "fecha_estimada",
    "precision_fecha", "confianza", "puntaje", "fuentes", "links"];
  const esc = (v) => { const s = v == null ? "" : String(v); return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const lineas = [cols.join(",")].concat(estado.filtrados.map((c) => cols.map((k) =>
    esc(k === "fuentes" ? c.fuentes.join(" + ") : k === "links" ? c.senales.map((s) => s.url).join(" | ") : c[k])).join(",")));
  descargar(`radar-zona-norte-${estado.meta.hoy}.csv`, "text/csv;charset=utf-8", "﻿" + lineas.join("\n"));
}
function exportarJSON() {
  descargar(`radar-zona-norte-${estado.meta.hoy}.json`, "application/json",
    JSON.stringify({ generado: estado.meta.actualizado, filtros: leerFiltros(), candidatos: estado.filtrados }, null, 1));
}

/* ---------- inicio ---------- */
function opciones(select, valores, etiqueta = (v) => v) {
  for (const v of valores) select.append(el("option", { value: v }, etiqueta(v)));
}

function iniciarMapa() {
  if (typeof L === "undefined") {
    document.getElementById("mapa").replaceChildren(el("p", { class: "vacio" }, "No se pudo cargar el mapa. La lista sigue funcionando."));
    return;
  }
  estado.mapa = L.map("mapa", { scrollWheelZoom: false }).setView([-34.45, -58.7], 10);
  // Tiles estándar de OSM: uso liviano, con atribución (operations.osmfoundation.org/policies/tiles/).
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">colaboradores de OpenStreetMap</a>',
  }).addTo(estado.mapa);
  estado.capa = L.layerGroup().addTo(estado.mapa);
}

async function iniciar() {
  iniciarTema();
  try {
    const [rc, re] = await Promise.all([fetch("data/candidatos.json", { cache: "no-cache" }), fetch("data/estado.json", { cache: "no-cache" })]);
    if (!rc.ok || !re.ok) throw new Error("HTTP " + rc.status + "/" + re.status);
    estado.datos = (await rc.json()).candidatos;
    estado.meta = await re.json();
  } catch (e) {
    document.getElementById("actualizado").textContent = "No se pudieron cargar los datos (" + e.message + ").";
    return;
  }
  const m = estado.meta;
  opciones(document.getElementById("f-ventana"), m.ventanas_dias, (d) => `Últimos ${d} días`);
  document.getElementById("f-ventana").value = String(m.ventana_defecto);
  opciones(document.getElementById("f-partido"), m.partidos);
  opciones(document.getElementById("f-rubro"), m.rubros);
  opciones(document.getElementById("f-fuente"), [...new Set(m.salud.map((s) => s.fuente))], (f) => ETIQUETAS.fuente[f] || f);
  if (m.arca) {
    document.getElementById("arca").replaceChildren("Verificación tributaria: la integración automática con ARCA no es viable (",
      el("a", { href: m.repo + "/blob/main/docs/ARCA.md" }, "por qué"), "); cada candidato enlaza la ",
      el("a", { href: m.arca.url_constancia, target: "_blank", rel: "noopener noreferrer" }, "consulta oficial de constancias"), ".");
  }
  document.getElementById("repo").href = m.repo;

  // Filtros desde la URL (#partido=Tigre&estado=abrio…) para poder compartir una vista.
  const params = new URLSearchParams(location.hash.slice(1));
  const form = document.getElementById("form-filtros");
  for (const [k, v] of params) if (form.elements[k]) form.elements[k].value = v;

  pintarEncabezado();
  pintarSalud();
  iniciarMapa();

  form.addEventListener("input", filtrar);
  form.addEventListener("submit", (e) => { e.preventDefault(); filtrar(); });
  form.addEventListener("reset", () => setTimeout(() => { document.getElementById("f-ventana").value = String(m.ventana_defecto); filtrar(); }));
  document.querySelectorAll("th button[data-orden]").forEach((b) => b.addEventListener("click", () => {
    const campo = b.dataset.orden;
    estado.orden = { campo, asc: estado.orden.campo === campo ? !estado.orden.asc : campo !== "puntaje" && campo !== "fecha" };
    document.querySelectorAll("th button[data-orden]").forEach((x) => x.removeAttribute("aria-sort"));
    b.setAttribute("aria-sort", estado.orden.asc ? "ascending" : "descending");
    ordenar();
    pintar();
  }));
  document.getElementById("exportar-csv").addEventListener("click", exportarCSV);
  document.getElementById("exportar-json").addEventListener("click", exportarJSON);
  filtrar();
}

iniciar();
