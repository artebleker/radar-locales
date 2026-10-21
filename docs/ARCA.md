# ARCA: corroboración tributaria

**Estado: verificación manual enlazada.**

No existe una vía oficial, gratuita, automatizable y permitida para corroborar aperturas con datos de ARCA. La integración automática se investigó y no es viable. El sitio ofrece un enlace a la consulta oficial de constancias para verificar a mano.

- **Fecha de comprobación:** 2026-10-20.
- **Método:** pedidos reales desde la máquina de desarrollo con el User-Agent del proyecto, y lectura de los manuales oficiales.

## Qué se probó

| Vía | URL oficial | Resultado de la prueba real | Datos disponibles | ¿Sirve para el radar? |
|---|---|---|---|---|
| Archivo de condición tributaria (datos descargables) | https://www.arca.gob.ar/genericos/cInscripcion/archivoCompleto.asp → `https://www.afip.gob.ar/genericos/cInscripcion/archivos/apellidoNombreDenominacion.zip` | HTTP 200, zip de 86 MB, `Last-Modified: 17/10/2026` (actualización semanal) | CUIT, denominación, Ganancias, IVA, categoría de monotributo, integrante de sociedad, empleador y actividad de monotributo (solo 12 códigos genéricos: 01 Comercial, 10 Ventas, etc.) | **No.** No tiene domicilio, ni fechas, ni actividad detallada, así que no permite ubicar un contribuyente en zona norte ni fechar nada. Además incluye apellido y nombre de personas humanas. |
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

No se guarda ni se publica ningún CUIT. No se piden credenciales.

No existe `radar/fuentes/arca.py`, porque no hay una integración automática viable que implementar.
