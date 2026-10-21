# ARCA: corroboración tributaria

**Estado: integración automática implementada (parcial), más verificación manual enlazada.**

Actualización del 2026-10-21. El radar descarga cada 30 días el archivo masivo oficial de condición tributaria y asocia a los candidatos el **CUIT de una persona jurídica** cuando el nombre coincide sin ambigüedad. Es una asociación por **nombre**, de **confianza baja**: el archivo no trae domicilio, así que el CUIT puede ser el de la empresa dueña de la marca y no el de quien opera el local. No modifica el puntaje ni prueba que el local esté abierto. Los web services y la constancia individual siguen sin ser viables; el detalle sigue más abajo.

## Integración automática (desde 2026-10-21)

- **Archivo:** `https://www.afip.gob.ar/genericos/cInscripcion/archivos/apellidoNombreDenominacion.zip`. En la medición real del 2026-10-21 era un zip de 86 MB con un único .txt de ancho fijo: 51 caracteres por línea, 6.199.556 filas, codificación latin-1 y `Last-Modified` del 17/10/2026.
- **Proceso** (`radar/padron/`):
  - descarga cada `frecuencia_dias` (30) y no reprocesa si el sha256 no cambió;
  - se conservan el mes actual y el anterior;
  - si la descarga o el formato fallan, se conserva el padrón anterior y la fuente figura como «Falló» en la salud del sitio.
- **Privacidad:**
  - las personas físicas (prefijos 20, 23, 24 y 27) se descartan al leer el archivo y nunca se guardan;
  - en disco (`data/padron_local/`, fuera de git) y en la caché de GitHub Actions queda solo un derivado de 7 MB con las 534.981 personas jurídicas;
  - el zip original no pasa por la caché HTTP.
- **Cruce** (`radar/enriquecer_cuit.py`): se asigna un CUIT solo si la coincidencia es única. Si hay más de una sociedad posible, el candidato se marca como ambiguo y no se le asigna ninguna.
  - **Nombre exacto normalizado:** se quitan tildes y formas societarias (SA, SRL, SAS…).
  - **Nombre similar:** `token_set_ratio` de 88 o más y, además, todas las palabras del candidato tienen que estar en la razón social o el orden de palabras tiene que coincidir en 95 o más.
  - **Nombres demasiado genéricos:** no se cruzan los de menos de 5 letras ni los de una sola palabra con menos de 7.
  - **Cruce por dirección (`direccion_exacta` y `direccion_y_nombre`):** está implementado y probado, pero solo se activa si el archivo trae domicilio. El actual no lo trae.
- **Resultado del 2026-10-21:** de los 34 candidatos del día, 4 recibieron CUIT (Mr. Tasty SRL, Sherwin Williams Argentina, Sei Tu SA y Havanna SA) y 3 quedaron como ambiguos sin asignar.
- **Altas mensuales:** `radar altas-cuit` compara los dos últimos padrones y escribe `data/altas_cuit/AAAA-MM.csv`, que es privado y está fuera de git. Solo incluye personas jurídicas. El rubro es el código grueso de monotributo; no hay domicilio ni fecha de inicio porque el archivo no los trae.

## Investigación original

- **Fecha de comprobación:** 2026-10-20.
- **Método:** pedidos reales desde la máquina de desarrollo con el User-Agent del proyecto, y lectura de los manuales oficiales.

## Qué se probó

| Vía | URL oficial | Resultado de la prueba real | Datos disponibles | ¿Sirve para el radar? |
|---|---|---|---|---|
| Archivo de condición tributaria (datos descargables) | https://www.arca.gob.ar/genericos/cInscripcion/archivoCompleto.asp → `https://www.afip.gob.ar/genericos/cInscripcion/archivos/apellidoNombreDenominacion.zip` | HTTP 200, zip de 86 MB, `Last-Modified: 17/10/2026` (actualización semanal) | CUIT, denominación, Ganancias, IVA, categoría de monotributo, integrante de sociedad, empleador y actividad de monotributo (solo 12 códigos genéricos: 01 Comercial, 10 Ventas, etc.) | **Parcialmente.** No tiene domicilio, ni fechas, ni actividad detallada, así que no permite ubicar ni fechar nada. Desde 2026-10-21 se usa para asociar por nombre el CUIT de personas jurídicas (ver arriba); las personas humanas se descartan. |
| Constancia de inscripción individual | https://seti.afip.gob.ar/padron-puc-constancia-internet/ConsultaConstanciaAction.do (formulario en `/jsp/Constancia.jsp`) | HTTP 200. El formulario tiene CAPTCHA (componente `ag-captcha` y campo `tokenCaptcha`) | Por CUIT: datos de la constancia | **No se automatiza**, porque habría que evadir el CAPTCHA. Se usa como **enlace de verificación manual**. |
| Web service `ws_sr_constancia_inscripcion` (v3.5, 13/12/2023) | Manual: https://www.arca.gob.ar/ws/WSCI/manual-ws-sr-ws-constancia-inscripcion.pdf · Producción: `https://aws.arca.gov.ar/sr-padron/webservices/personaServiceA5` | Manual descargado y leído. No se invocó el servicio, porque requiere credenciales | Por CUIT: domicilio **fiscal**, estado de la clave, actividades con `periodo` (AAAAMM) | **No es viable.** Los requisitos están más abajo. |
| Web service `ws_sr_padron_a5` (v1.0, 13/01/2017) | Manual: https://www.afip.gob.ar/ws/ws_sr_padron_a5/manual_ws_sr_padron_a5_v1.0.pdf | Manual descargado y leído | Ídem: domicilio fiscal, actividades con período | **No es viable**, por los mismos motivos. |

## Requisitos de los web services

Están verificados en los manuales oficiales.

1. **Ticket de acceso del WSAA en cada pedido** (token y sign). Lo dicen los dos manuales en la sección 2.2: «Para la utilización de los métodos… se debe enviar en cada solicitud, el token y el sign».
2. **Certificado digital de producción.** Lo dice https://www.afip.gob.ar/ws/WSAA/wsaa_obtener_certificado_produccion.pdf: «Se presupone que ya se posee clave fiscal de nivel acorde a los servicios que se utilizan (3)». Se tramita con la clave fiscal de una persona, en «Administración de Certificados Digitales».
3. **Asociación del certificado al servicio** desde el Administrador de Relaciones de Clave Fiscal: https://www.afip.gob.ar/ws/WSAA/wsaa_asociar_certificado_a_wsn_produccion.pdf.

En la práctica, el trámite es gratis, pero el proyecto tendría que operar con la clave fiscal de nivel 3 y el certificado de una persona real, y guardar la clave privada como secreto de GitHub. Eso va contra la regla de no recolectar credenciales ni certificados del usuario, y crea un riesgo que no se justifica.

## Por qué tampoco aportaría aunque hubiera acceso

- **Se consulta por CUIT.** El radar conoce nombres comerciales («Mr. Tasty», «Skinko»), no CUITs, y no hay ninguna búsqueda oficial por nombre de fantasía ni por domicilio.
- **Devuelve el domicilio fiscal, no el del local.** Ninguno de los dos servicios lista los locales o establecimientos declarados.
- **El `periodo` de una actividad no es una fecha de apertura.** Indica cuándo se dio de alta la actividad en el padrón. Una empresa puede abrir diez locales sin cambiarlo. Por regla, nunca se usaría como fecha de apertura.

## Qué hace el sitio

En el detalle de cada candidato se muestra un enlace a la consulta oficial de constancias, con esta nota: «Si conocés el CUIT del comercio, podés verificar su inscripción en ARCA. Una inscripción no prueba que el local esté abierto».

Desde el 2026-10-21 también se muestran el CUIT y la razón social asociados por el padrón, solo de personas jurídicas, con el tipo de coincidencia y su confianza. Nunca se guardan ni se publican CUITs de personas físicas. No se piden credenciales.

La integración automática está en `radar/padron/` y `radar/enriquecer_cuit.py`. No es una «fuente» de señales: enriquece a los candidatos que ya existen y no les cambia el puntaje.
