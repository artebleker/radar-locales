# Radar de aperturas comerciales — Zona Norte GBA

**Sitio:** https://artebleker.github.io/radar-locales/

Sitio estático y público con locales comerciales **recién abiertos o por abrir** en zona norte del Gran Buenos Aires. Se detectan automáticamente, todos los días, a partir de fuentes públicas: OpenStreetMap, medios locales, directorios de shoppings y buscadores de sucursales de cadenas.

El sitio prioriza la **cantidad sobre la precisión**. Nada se descarta por dudoso: se le baja la confianza. Cada candidato muestra su nivel de confianza, por qué lo tiene y el link a cada fuente, para que cualquiera pueda verificarlo.

- **Costo cero:** sin APIs pagas, sin claves y sin servicios de prueba que vencen.
- **Sin IA:** la extracción es por reglas (regex, diccionarios, etiquetas de OSM y comparación de listados).
- **Sin login ni cookies:** quien visita no gasta nada; son HTML, CSS, JS y JSON estáticos.

Partidos activos: Vicente López, San Isidro, San Fernando, Tigre, San Martín, Escobar, Pilar y Malvinas Argentinas. San Miguel, José C. Paz, Tres de Febrero y Campana están verificados en la configuración pero apagados.

---

## Cómo funciona

```
fuentes (radar/fuentes/)            unificación                         publicación
 ├─ osm          ─┐                  historial (180 días)                site/data/candidatos.json
 ├─ medios_rss    ├─► señales ─►     deduplicación (nombre + distancia)  site/data/estado.json
 ├─ directorios   │                  puntaje y estado                    → GitHub Pages
 └─ sucursales   ─┘
```

Cada fuente devuelve **señales**: «este comercio apareció acá, según esta fuente, con este link». Las señales que se refieren al mismo local se agrupan en un **candidato**, que tiene un id estable entre corridas, un puntaje y un estado.

### Fuentes

Medición del 2026-10-20, que fue la primera corrida. Las fuentes que comparan listados no dan señales el primer día, porque ese relevamiento queda como base.

| Fuente | Qué detecta | Cómo | Confianza base | Primera corrida |
|---|---|---|---|---|
| **OpenStreetMap** (`osm`) | Comercio cargado en los últimos 30 días; comercio nuevo respecto del día anterior; «por abrir» (`opening_date` futura o prefijos `construction:`, `planned:` o `proposed:`); cambio de nombre o rubro en el mismo lugar, incluido un local vacío que pasa a tener comercio | Una consulta diaria a Overpass (`out meta center`, unos 5,4 MB, 11 005 comercios) y comparación con el snapshot | Baja | 27 señales |
| **Medios locales** (`medios_rss`) | Notas con verbos de apertura («abrió», «inaugura», «llega», «futura sucursal»…) | 13 feeds de 11 medios (RSS y API pública de WordPress) | Media | 6 señales sobre 779 notas, todas aperturas reales |
| **Shoppings** (`directorios`) | Tienda nueva en el directorio, o marcada como «Próximamente» | 8 directorios, con un adaptador genérico configurable | Alta | Base: 913 tiendas |
| **Cadenas** (`sucursales`) | Sucursal nueva en un partido de la zona | 8 cadenas (Día, Carrefour, Easy, Blaisten, Simplicity, Bonafide, Havanna, Frávega) | Alta | Base: 249 sucursales |

Las fuentes probadas y descartadas, con el motivo de cada una, están anotadas en `config.yaml`, en los comentarios de cada sección.

### Confianza y estado

Las reglas están en `radar/scoring.py` y los números en `config.yaml → puntaje`, así que se pueden ajustar sin tocar código.

- **Puntaje (0 a 100).** Se calcula así:
  - Se parte del peso de la mejor señal: sucursal o tienda nueva 65, nota de prensa 50, «por abrir» en OSM 35, cambio en OSM 30, comercio nuevo en OSM 25.
  - Suma **+20 por cada fuente distinta** adicional, +10 si hay fecha exacta y +5 si hay dirección.
  - Resta penalizaciones: sin nombre −15, partido dudoso −15, palabras «de gobierno» como municipio o intendente −15, nota que menciona un año viejo −20, entre otras.
- **Confianza.** Alta desde 60 puntos, media desde 35 y baja por debajo.
- **Estado:**
  - *Por abrir:* fecha futura, «próximamente» o construcción en OSM.
  - *Abrió:* fecha pasada, o la fuente dice que abrió.
  - *Detectado:* solo se sabe que apareció, que es el caso de la mayoría de OSM.
- **Fechas.** Se guardan por separado la fecha del evento, la de publicación de la nota, la de alta o modificación en la fuente y la de detección. Nunca se reemplaza una por otra. Si una nota no anuncia fecha, el sitio muestra la fecha de la nota como «inferida, según la nota».

### Deduplicación

Dos señales se fusionan si tienen el mismo id externo, o si sus nombres normalizados se parecen y además están a menos de 150 m. Para la comparación, los nombres se pasan a minúsculas, sin tildes y sin palabras como «SRL», «sucursal» o «supermercados». La similitud se mide con `rapidfuzz.token_set_ratio` y un umbral de 88.

Si una señal no tiene coordenadas, solo se fusiona cuando coincide con un único lugar. Ante la duda no se fusiona: es preferible un duplicado visible a perder un candidato.

---

## Uso local

Requiere Python 3.11 o superior. El desarrollo se hizo con 3.14 y GitHub Actions usa 3.14.

```bash
cd radar-locales
make instalar          # crea .venv e instala requirements.txt y el comando `radar`
make bootstrap         # límites, localidades y primer snapshot (una vez)
make run               # corrida completa: recolecta, unifica y genera site/data/
make serve             # http://localhost:8000
make test              # pytest sin red (fixtures grabados)
```

### Comandos

| Comando | Qué hace |
|---|---|
| `radar bootstrap` | Descarga los límites de los partidos desde OSM, verificando nombre y nivel de cada relación. Arma el diccionario localidad → partido y la lista de lugares fuera de zona. Si no hay snapshot de OSM, arma el primero con los comercios cargados en los últimos 30 días. |
| `radar run [--fuentes osm,medios_rss,directorios,sucursales] [--limite N] [--dry-run]` | Recolecta, deduplica, puntúa y genera `site/data/`. Con `--dry-run` no escribe nada. |
| `radar record --fuente X` | Graba respuestas reales en `tests/fixtures/X/` para las pruebas sin red. Nunca graba cuerpos de notas, teléfonos, emails ni usuarios de OSM. |
| `radar serve [--puerto 8000]` | Sirve `site/`. Desde el celular, en la misma red Wi-Fi, se entra con `http://<IP-de-la-computadora>:8000`. |
| `radar report` | Totales por fuente, partido, rubro, confianza y estado, más una muestra aleatoria de 15 candidatos para revisar a mano. |
| `radar padron` | Fuerza la descarga del padrón de ARCA, sin esperar los 30 días. Tarda unos 45 s y usa unos 600 MB de memoria. |
| `radar altas-cuit` | Escribe `data/altas_cuit/AAAA-MM.csv` con las personas jurídicas nuevas entre los dos últimos padrones. Es **privado**: está fuera de git y nunca se publica. |

### Windows

```powershell
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install --no-deps -e .
.venv\Scripts\radar bootstrap
.venv\Scripts\radar run
.venv\Scripts\radar serve
```

---

## Cómo extender

Todo lo configurable está en **`config.yaml`**: zona, rubros, fuentes, pesos, umbrales y ventanas.

- **Sumar un partido.**
  1. Buscá su relación en Overpass: `rel["boundary"="administrative"]["admin_level"="5"]["name"="Partido de X"]`. En la provincia de Buenos Aires los partidos son de nivel 5.
  2. Agregalo a `partidos:` con su `relacion` y su `osm_nombre`, o cambiá `activo: true` si ya figura.
  3. Corré `radar bootstrap`. El código frena si el nombre o el nivel no coinciden.

  Los comercios de un partido recién activado no se cuentan como altas el primer día.
- **Corregir localidades.** Usá `data/ref/localidades_correcciones.yaml`, con `agregar: {Nombre: Partido}` y `quitar: [Nombre]`.
- **Sumar un medio.** Probá su `/feed/`. Si devuelve HTML, el feed está desactivado: usá `tipo: wp_json` con `/wp-json/wp/v2/posts`. Agregalo a `medios_rss.feeds`, con `partido_defecto` si es un medio de un solo partido.
- **Sumar un shopping.** Agregalo a `directorios.sitios` con:
  - las páginas;
  - el patrón de link de cada tienda (el grupo 1 es el id);
  - de dónde sale el nombre (`enlace`, `selector`, `slug` o `img_alt`);
  - lat y lon del shopping según OSM.

  Después corré `radar record --fuente directorios` y sumá su caso a `tests/test_directorios.py`.
- **Sumar una cadena.** Si la tienda usa VTEX, alcanza con `tipo: vtex_pickup` y su `host`. Antes verificá que robots.txt no prohíba `/api/checkout/` y que los puntos de retiro sean locales propios y no lockers de terceros. Para otros buscadores, agregá un adaptador en `radar/fuentes/sucursales.py`.
- **Sumar una fuente nueva.** Creá un módulo en `radar/fuentes/` con `NOMBRE`, `TIPO`, `URL`, `LICENCIA`, `CONFIANZA_BASE` y `recolectar(config, cache) -> list[Senal]`, y registralo en `radar/fuentes/__init__.py`. Usá siempre `cache.pedir(url)`, que ya respeta robots.txt, manda el User-Agent, pausa entre pedidos al mismo host, reintenta y guarda en caché.
- **Ajustar el puntaje o los filtros de prensa.** Están en `puntaje:` y en `extraccion:`: verbos, exclusiones fuertes y débiles, homónimos y nombres neutros. Cada caso de ruido nuevo conviene sumarlo como test en `tests/test_extraccion.py`.

**Cuando una fuente se rompe**, aparece como «Falló» o con avisos en la sección *Salud de las fuentes* del sitio, y las demás siguen funcionando. El arreglo típico es corregir el patrón o la URL en `config.yaml`, volver a grabar el fixture con `radar record` y correr `make test`.

---

## Automatización y publicación

- **`.github/workflows/actualizar.yml`:** se dispara todos los días a las 9:37 UTC (6:37 en Argentina) y también a mano, desde *Actions → Actualizar radar → Run workflow*. Corre `radar run`. Si los datos cambiaron, hace un commit de `data/` y `site/data/` con los totales en el mensaje. Al final despliega `site/` en GitHub Pages con el flujo oficial: `configure-pages@v6`, `upload-pages-artifact@v5` y `deploy-pages@v5`.
- **Padrón de ARCA en Actions:** persiste entre corridas con `actions/cache@v6` (clave `padron-<run_id>`, que restaura la más reciente), sin commitearse. El workflow frena si algo de `data/padron_local/` o `data/altas_cuit/` quedara agregado al commit.
- **`.github/workflows/tests.yml`:** corre pytest sin red en cada push.
- **Pages:** está configurado en *Settings → Pages → Source: GitHub Actions*.

### Límites de GitHub

- **El schedule no es exacto.** Con mucha carga, GitHub puede demorar o saltear una corrida programada. Por eso el cron está fuera del minuto 0.
- **60 días sin actividad.** En repos públicos, GitHub desactiva los workflows programados cuando el repo pasa 60 días sin actividad, pero la documentación oficial no define qué cuenta como actividad. El workflow hace un commit cada vez que cambian los datos, que es casi todos los días, y las herramientas de «keepalive» de terceros usan justamente commits para mantenerlo vivo. Aun así, **no está verificado** que los commits del bot alcancen. Si se desactiva, se reactiva desde *Actions → Actualizar radar → Enable workflow*, o con `gh workflow enable actualizar.yml`.
- **Tamaño del repo.** Los snapshots y el historial son archivos de texto ordenados, así que git guarda solo las diferencias diarias. Hoy `data/snapshots` ocupa unos 0,9 MB. El historial se parte por mes y, pasados los 180 días, se comprime en `data/historial/archivo/`. Si `data/` crece demasiado, se pueden mover los snapshots a una rama aparte.

### Alternativa evaluada: Netlify

Se revisó el 2026-10-20 en netlify.com/pricing y en la documentación de planes por créditos. El plan gratuito tiene **300 créditos por mes con límite estricto**. Cada deploy de producción cuesta 15 créditos y cada GB de tráfico 20. **Una actualización diaria cuesta unos 450 créditos por mes**, más de lo que incluye el plan, así que Netlify gratis no sirve para este proyecto. Para publicar ahí habría que espaciar los deploys a unos 20 por mes.

---

## Límites conocidos

- **Nuevo en OSM no es lo mismo que nuevo en la realidad.** Alguien puede mapear hoy un local que tiene 20 años. Por eso OSM entra con confianza baja y sube si otra fuente lo confirma. Hay tandas visibles, con IDs consecutivos cargados el mismo día, que casi seguro son locales viejos.
- **La prensa local trae poco volumen:** unas 6 aperturas por mes en 11 medios. Google Noticias quedó **excluido**, porque `news.google.com/robots.txt` prohíbe `/rss`.
- **Overpass.** El servidor principal está sobrecargado, según la wiki, y a veces devuelve 502. El radar respeta su política para uso regular: menos de 100 consultas y 10 MB por día, User-Agent identificable, nada en paralelo y 30 s de espera ante un 429 o 406. Si el principal falla, prueba los servidores alternativos de la config. Si la respuesta trae menos del 90 % de los comercios del día anterior, no compara ni pisa el snapshot.
- **Frávega bloquea los servidores de la nube.** Desde GitHub Actions su robots.txt no permite el pedido, aunque desde una conexión hogareña sí. El radar lo respeta y lo muestra como aviso en la sección de salud.
- **Escobar a Diario ignora la paginación** y siempre devuelve sus 10 notas más recientes. Con la corrida diaria alcanza.
- **Cadenas por cercanía.** Las cadenas VTEX devuelven como mucho 300 puntos por consulta, así que se consulta desde el centro de cada partido. San Fernando incluye islas del Delta, y su centro cae en el agua.
- **Términos y condiciones.** Se verificó robots.txt en todas las fuentes, pero no se leyeron en detalle los términos de cada sitio.
- **Tiles del mapa.** Se usan los tiles estándar de OSM, con atribución visible y respetando su [política de uso](https://operations.osmfoundation.org/policies/tiles/), que admite uso liviano sin cupo garantizado. Si el tráfico creciera, habría que pasar a otro proveedor de tiles libre o a uno propio.

## ARCA (corroboración tributaria)

**Estado: integración automática implementada (parcial), más verificación manual enlazada.** Comprobado el 2026-10-21; el detalle y la evidencia están en [`docs/ARCA.md`](docs/ARCA.md).

**Padrón público (automático).** Cada 30 días se descarga el archivo masivo oficial de condición tributaria.

- **Qué guarda:** se queda solo con las personas jurídicas, unas 535 mil. Las físicas se descartan al leer.
- **Cómo cruza:** asocia el **CUIT** al candidato cuando el nombre coincide sin ambigüedad. La coincidencia es solo por nombre y de confianza baja, porque el archivo no trae domicilio: el CUIT puede ser el de la empresa dueña de la marca.
- **Cómo se ve:** el sitio muestra el CUIT, la razón social y el tipo de coincidencia. No cambia el puntaje.
- **Si falla:** se usa el padrón anterior, la falla queda en la salud de fuentes y el resto del radar sigue igual.
- **Cuándo no asigna:** si hay más de una sociedad posible, el candidato queda como «ambiguo» y no se le asigna ningún CUIT.

**Lo que sigue sin ser viable:**

- **Cruce por domicilio, fecha de inicio o actividad:** el archivo descargable no trae esos datos. El código ya soporta el cruce por dirección si algún día un archivo oficial los incluye.
- **Constancia individual:** tiene CAPTCHA, así que no se automatiza.
- **Web services `ws_sr_constancia_inscripcion` y `ws_sr_padron_a5`:**
  - piden certificado digital y clave fiscal de nivel 3 de una persona;
  - solo consultan por CUIT;
  - devuelven el domicilio fiscal, no el del local.

Cada candidato del sitio enlaza la consulta oficial de constancias, con la aclaración de que una inscripción no prueba que el local esté abierto. No se guardan CUITs ni nombres de personas físicas, ni se piden credenciales.

## Ideas para después (no implementadas)

**Habilitaciones municipales.** Se investigó partido por partido el 2026-10-20:

| Partido | Qué hay | Evaluación |
|---|---|---|
| Vicente López | Dataset «Comercios Habilitados» en su portal de datos abiertos (vicentelopez.opendata.junar.com, dataset 199597, XLSX, licencia ODC-PDDL): razón social, rubro, calle y altura. Su Boletín Oficial propio (vicentelopez.gov.ar/boletin_oficial) publica listados de habilitaciones en PDF. | El dataset se actualiza **una vez por año** (la última fue el 12/07/2025) y la razón social puede ser el nombre de una persona. Se podría hacer una comparación anual, filtrando personas humanas. Los PDF del boletín son una opción para estudiar. |
| Pilar | Publica en SIBOM (sibom.slyt.gba.gob.ar/cities/35); último boletín del 29/09/2026. Las habilitaciones industriales y las transferencias de comercio se publican por edicto. | El último boletín no menciona habilitaciones. Habría que revisar varios números. |
| San Martín | Publica en SIBOM (cities/57); último boletín del 09/10/2026. | Ídem. |
| San Isidro, San Fernando, Tigre, Escobar, Malvinas Argentinas | Figuran en SIBOM sin boletines listados. | No se encontró una fuente procesable. |

**Otras ideas:**
- **Constituciones de sociedades en el Boletín Oficial:** mucho volumen, pero son empresas y no locales, y llegan con atraso.
- **Avisos de alquiler de locales comerciales:** serían una señal adelantada, pero solo si alguna fuente lo permite en sus términos.
- **Fuentes de prensa más amplias que reemplacen a Google Noticias**, respetando robots.txt.

## Privacidad

No se guardan nombres de personas, teléfonos, emails ni usuarios de OSM. Del padrón de ARCA se descartan las personas físicas al leerlo: nunca se guardan ni se publican sus CUITs o nombres. De los comercios se guardan el nombre comercial y la dirección del local. Los fixtures de tests se graban sin teléfonos ni emails.

## Licencias y atribuciones

- **Código:** MIT (ver `LICENSE`).
- **Datos de OpenStreetMap:** © colaboradores de OpenStreetMap, [ODbL](https://www.openstreetmap.org/copyright). La atribución está visible en el mapa y al pie del sitio.
- **Notas de prensa:** solo se guarda título, medio, fecha y link. Nunca el cuerpo.
- **Directorios y sucursales:** nombre de la tienda o sucursal y link a la página pública de cada sitio.
- **Leaflet 1.9.4:** licencia BSD-2-Clause, cargado desde cdnjs con hash de integridad.
