# Interpretación de órdenes del sistema

El asistente puede abrir carpetas y aplicaciones locales mediante órdenes en español. La implementación se conecta a la transcripción ya producida por Whisper y utiliza la salida de Piper para preguntas, aclaraciones y resultados. No necesita modelos adicionales ni servicios externos. Abrir carpetas en Linux requiere `xdg-open` (normalmente incluido en `xdg-utils`).

## Flujo y responsabilidades

1. `RapidFuzzCommandMatcher` reconoce los prefijos de apertura definidos en `config/voice_commands.json`; `RapidFuzzIntentResolver` extrae el objetivo que sigue.
2. `SystemEntityCatalog` resuelve ese objetivo contra `config/carpetas.json` y las entradas de aplicación `.desktop` instaladas. Carga los catálogos y descubre aplicaciones una vez al iniciar; las órdenes siguientes consultan la lista en memoria.
3. `ConversationContext` conserva una orden incompleta o una lista de opciones, con vencimiento configurable.
4. `SystemCommandHandler` pregunta por el objetivo, comunica ambigüedades, acepta una selección hablada o numérica y valida el resultado.
5. `LinuxSystemActionExecutor` recibe únicamente IDs resueltos del catálogo. Abre carpetas mediante `xdg-open` y aplicaciones mediante el `Exec` prevalidado de su archivo `.desktop`.

El contrato `IntentResolver` y `IntentResult` está en `clases/contratos.py`. `SystemCommandHandler` conecta el intérprete con el controlador de voz sin mezclar el reconocimiento, la decisión y las operaciones del sistema. `SystemActionExecutor` es un puerto que permite añadir otro adaptador de plataforma sin reescribir la interpretación.

## Órdenes y conversación

Ejemplos:

- «Abre Descargas» resuelve una carpeta autorizada y la abre sin pedir confirmación si la coincidencia es inequívoca.
- «Quiero abrir una carpeta» guarda la intención, pregunta qué carpeta y acepta el siguiente turno —por ejemplo, «Documentos»— sin pedir que se repita la orden.
- «Ejecuta Firefox» busca entre las aplicaciones instaladas que tengan una entrada `.desktop`.
- Si una expresión coincide con varios recursos, Piper enumera hasta tres opciones. El usuario puede decir «segunda opción», «opción dos», `2` o el nombre del recurso.
- «Cancelar» (también sus variantes configuradas) elimina la operación pendiente.

El contexto caduca después de 30 segundos por defecto. Un turno posterior a ese plazo no reutiliza la operación antigua; se solicita una orden nueva. El sistema no interpreta ni ejecuta órdenes arbitrarias de terminal.

## Configuración

Los umbrales son puntuaciones de similitud RapidFuzz —**no probabilidades**— y se ajustan mediante pruebas con transcripciones reales:

- `command_similarity_threshold` en `config/ajustes.json`: umbral para reconocer frases de acción; por defecto, 80.
- `entity_similarity_threshold` en `config/intenciones_sistema.json`: umbral para aceptar el nombre de una carpeta o aplicación; por defecto, 84.
- `ambiguity_margin`: candidatas dentro de esta diferencia respecto a la mejor puntuación se presentan como opciones; por defecto, 5.
- `max_candidates`: límite de opciones habladas; máximo 3.
- `context_timeout_seconds`: caducidad de la conversación pendiente.

Las frases de apertura, sus variantes, las pistas de tipo («carpeta», «aplicación») y las palabras gramaticales están centralizadas en `config/voice_commands.json`, dentro de `open_resource`. Agrega allí las expresiones que Whisper puede transcribir y los términos que separan el tipo de recurso del nombre. Las frases de cancelación, respuestas de selección, límites de ambigüedad y vencimiento del contexto están en `config/intenciones_sistema.json`; ese archivo no define frases de órdenes. Si se modifica alguno de los archivos, reinicia la aplicación para volver a cargarlos.

### Añadir una carpeta

Agrega una entrada a `config/carpetas.json` con un ID estable, nombre, alias y ruta. Se puede usar una ruta absoluta o `~` mediante `path`. Para una carpeta estándar XDG, usa `xdg_user_dir` y `fallback_path`; el valor de `~/.config/user-dirs.dirs` tiene prioridad y permite nombres de directorio localizados o personalizados. Si no existe esa configuración, se utiliza el fallback habitual en inglés, por ejemplo `Downloads`. La carpeta debe existir al resolver la orden; no se aceptan rutas procedentes de la transcripción.

```json
{
  "id": "downloads",
  "name": "Descargas",
  "xdg_user_dir": "DOWNLOAD",
  "fallback_path": "Downloads",
  "aliases": ["descargas", "downloads"]
}
```

Las subcarpetas se indexan al iniciar, únicamente en el primer nivel dentro de las raíces con IDs `pictures`, `documents`, `videos`, `desktop` y `downloads` (Imágenes, Documentos, Vídeos, Escritorio y Descargas). Puedes decir directamente «Abre Facturas» si esa carpeta está dentro de Documentos. Si hay carpetas con el mismo nombre, Piper pedirá elegir e indicará la raíz de cada opción.

El descubrimiento no recorre subcarpetas de forma recursiva ni sigue enlaces simbólicos. Mantiene las búsquedas rápidas y evita salir de las raíces permitidas. Las carpetas ocultas no se añaden. Si se crea, elimina o renombra una subcarpeta mientras el asistente está abierto, reinicia la aplicación para actualizar el índice.

Las carpetas principales ya declaradas en `config/carpetas.json` siguen disponibles. Las subcarpetas fuera de esas cinco raíces no se indexan, aunque se hayan añadido alias adicionales a otra carpeta. La autorización se comprueba de nuevo al abrir; si la ruta desapareció o dejó de ser hija directa de su raíz, el ejecutor la rechaza. No se aceptan rutas dictadas como texto.

### Añadir alias a una aplicación

Las aplicaciones se descubren bajo `applications/` de `XDG_DATA_HOME` y `XDG_DATA_DIRS`; no se recorre el resto del sistema de archivos. Se ignoran entradas ocultas, no visibles o que no se puedan ejecutar. Los nombres se obtienen del `.desktop` (incluido `Name[es]` si corresponde). En `config/aplicaciones.json` se pueden asociar alias a IDs de escritorio instalados. Incluye alias comunes para Firefox/navegadores y reproductores de música; solo se activan si existe la entrada correspondiente:

```json
{
  "desktop_ids": ["firefox.desktop"],
  "aliases": ["fire fox", "navegador"]
}
```

La voz solo elige entre aplicaciones descubiertas; una entrada de alias no instala ni inventa una aplicación. Los IDs de escritorio y los nombres pueden variar entre distribuciones.

## Seguridad y límites actuales

- Carpetas y aplicaciones tienen catálogos separados; los nombres hablados nunca se convierten directamente en rutas ni comandos.
- El ejecutor usa `subprocess.Popen` con una lista de argumentos y sin `shell=True`. Para carpetas, el único argumento variable es la ruta validada del catálogo. Para aplicaciones, los argumentos vienen del `.desktop` descubierto y sus códigos de archivo compatibles se resuelven al cargarlo.
- El prefijo de acción se compara al inicio de la frase, y el texto restante se resuelve como nombre de recurso contra el catálogo normalizado. Se rechazan rutas, metacaracteres y argumentos de terminal que aparezcan en la transcripción antes de resolver el objetivo.
- Las carpetas se comprueban de nuevo antes de abrirlas. El ejecutor de aplicaciones comprueba de nuevo que siga existiendo el archivo `.desktop` y que el ejecutable esté disponible.
- En esta etapa, la nueva capa implementa **abrir carpetas y aplicaciones**. Cerrar aplicaciones, buscar archivos y leer documentos quedan como extensiones futuras; no se mapean a comandos genéricos.
- La detección de cámara existente sigue usando sus frases RapidFuzz. «Abrir cámara» se deja pasar al enrutamiento anterior para conservar ese control.

Ejecuta las pruebas aisladas de esta capa con:

```bash
.venv/bin/python -m pytest -q tests/test_system_commands.py
```
