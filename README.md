# Asistente local de detección visual

Proyecto en desarrollo para construir un asistente de IA local que detecte objetos frente a la cámara y, más adelante, pueda compartir esa información con módulos de audio y otras capacidades del asistente.

El asistente espera la tecla `v`: mantenla pulsada para grabar y suéltala para enviar toda la frase a Whisper y mostrar la transcripción en la terminal. La cámara y YOLO permanecen apagados hasta que se reconoce una pregunta como «¿qué ves?». Mientras la cámara está activa, el asistente anuncia lo detectado cada cinco segundos; «cerrar cámara» apaga la cámara y deja el sistema listo para otra pulsación.

## Características actuales

- Captura desde la cámara predeterminada, con solicitud de 3 FPS y límite adicional por software.
- Inferencia con un modelo YOLO local cada 2 segundos.
- Vista previa con el último fotograma anotado, que se conserva entre inferencias.
- Eventos de detección con fecha y hora UTC, dimensiones del fotograma, etiqueta, confianza y caja delimitadora.
- Publicación de eventos a consumidores compatibles con `DetectionListener`.
- Serialización de eventos a diccionarios JSON.
- Transcripción local en español, iniciada al mantener `v` y enviada al soltarla.
- Piper interrumpe el audio en curso al pulsar `v` y permanece en pausa mientras se graba.
- Reconocimiento tolerante a errores con RapidFuzz: umbral del 80%, confirmación de coincidencias aproximadas y aclaración de órdenes ambiguas.
- Interpretación modular de órdenes para abrir carpetas y aplicaciones Linux; mantiene contexto para preguntas de seguimiento y desambiguación hablada.
- Descubrimiento de aplicaciones mediante entradas `.desktop` y catálogos editables de carpetas, alias e intenciones; no ejecuta texto de voz como comando de terminal.
- Acceso por voz a subcarpetas directas únicamente dentro de Imágenes, Documentos, Vídeos, Escritorio y Descargas; no se recorren carpetas recursivamente ni se siguen enlaces simbólicos.
- La cámara solo se abre al reconocer una petición para ver; YOLO también se carga de forma diferida en ese momento.
- Los modelos se descargan y verifican con SHA256 desde un manifiesto; los binarios y pesos no se versionan en Git.
- Anuncios hablados con los nombres de los objetos detectados, repetidos cada cinco segundos.
- Cierre por voz con variantes de «cerrar cámara» o con la tecla `q`; el asistente permanece en modo de escucha.
- Liberación de cámara y ventana al finalizar el ciclo, incluso cuando un componente falla.
- Pruebas unitarias del coordinador, el evento y el adaptador YOLO.

El FPS configurado es una solicitud al controlador; algunas cámaras pueden ignorarla. El límite de lectura por software reduce la frecuencia de captura de la aplicación, pero no garantiza cómo el controlador adquiere internamente los fotogramas.

## Requisitos

- Python 3.10 o posterior.
- Cámara compatible con OpenCV para ejecutar la vista en vivo.
- Micrófono y `arecord` (ALSA) para transcribir voz en Linux.
- Sesión gráfica X11 para detectar globalmente `v` con `pynput`.
- `aplay` (ALSA) para reproducir Piper en Linux.
- `xdg-open` (paquete `xdg-utils`) para abrir carpetas; las aplicaciones se descubren con entradas `.desktop`.
- Git, CMake y compilador C/C++ para construir `whisper-server`.
- Cámara y micrófono no son necesarios para ejecutar las pruebas simuladas.

## Instalación

Instalación básica en cuatro comandos desde una terminal compatible con Bash:

```bash
git clone https://github.com/Cyraxevil7/Asistente-virtual-offline.git && cd Asistente-virtual-offline
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/descargar_modelos.py
```

En Windows PowerShell, crea y activa el entorno con `py -m venv .venv` y `.venv\Scripts\Activate.ps1`; instala las mismas dependencias y ejecuta el script desde ese entorno.

En Linux pueden ser necesarias bibliotecas del sistema para OpenCV/GUI. `pynput` requiere una sesión gráfica X11 compatible para recibir la tecla global `v`.

## Ejecutar el asistente

```bash
python main.py
```

Al iniciar, la aplicación comprueba los modelos y, si falta alguno, prepara primero Piper para anunciar por voz las descargas siguientes. Si Piper todavía no está disponible, informa por terminal y usa `espeak-ng`/`espeak` solo si ya están instalados. Después inicia Whisper localmente, pero no empieza a grabar. Mantén pulsada `v` mientras dices una frase y suéltala para transcribirla. Di «¿qué ves?», «¿qué hay delante?» o «¿qué detectas?» para abrir la cámara. La tasa sigue en 3 FPS y YOLO infiere cada 2 segundos.

Di «cerrar cámara», «cierra la cámara», «apaga la cámara» o «detén la cámara» mientras mantienes `v` para cerrarla. También puedes pulsar `q` en la ventana. Después del cierre, el programa espera otra pulsación de `v`; no mantiene el micrófono grabando. Los eventos JSON siguen apareciendo en la terminal. En Linux sin activar el entorno virtual también se puede usar `.venv/bin/python main.py`.

Los valores de cámara, intervalos y umbrales están en `config/ajustes.json`; los metadatos de modelos están en `config/modelos.json`. `whisper_model_id` permite seleccionar `whisper-base` o `whisper-tiny`; el idioma se fija en `clases/controlador_voz.py` como español (`language=es`). Para descargar la alternativa opcional: `python scripts/descargar_modelos.py --solo whisper-tiny`. `ModelManager` obtiene rutas por ID y guarda los archivos fuera del repositorio en el directorio de datos del usuario. La variable `ASISTENTE_MODELS_DIR` cambia ese directorio. En desarrollo sigue reconociendo el layout anterior local en `modelos/`. Para indicar otro `whisper-server`, define `ASISTENTE_WHISPER_SERVER`.

Las frases de cámara y las variantes de «abrir carpeta/aplicación» se editan en `config/voice_commands.json`. RapidFuzz conserva el umbral predeterminado del 80% y el margen de ambigüedad de cinco puntos. El umbral visual predeterminado sigue en 0.25.

### Añadir una orden de voz

Cada entrada de `config/voice_commands.json` requiere un identificador, una `description` que Piper pueda decir y una lista no vacía de `phrases` que Whisper podría transcribir. Para ampliar el vocabulario de apertura, edita la entrada `open_resource`: `phrases` son los inicios de orden, `entity_type_phrases` define términos como «carpeta» o «aplicación» y `target_stop_words` elimina palabras gramaticales antes de buscar el recurso. Los límites de ambigüedad, selección, cancelación y vencimiento del diálogo se configuran aparte en `config/intenciones_sistema.json`; este archivo ya no contiene frases de apertura. Las frases se comparan sin distinguir mayúsculas, acentos ni puntuación.

Para añadir una acción, registra un handler usando el mismo identificador en `command_handlers` al crear `VoiceAssistant`. Por ejemplo, conserva los handlers de cámara que proporciona `on_camera_command` y agrega el handler de la nueva orden:

```python
assistant = VoiceAssistant(
    recognizer,
    speech_output,
    on_camera_command=handle_camera,
    command_handlers={"new_command": handle_new_command},
)
```

El identificador `new_command` debe existir también en el JSON. La validación del asistente informa si una orden configurada no tiene una acción registrada.

### Servidor Whisper y salida Piper

`whisper-server` es una herramienta de ejecución, no un modelo. Con Git, CMake y un compilador C/C++ instalados, constrúyelo en el directorio ignorado `vendor/`:

```bash
bash scripts/construir_whisper.sh
```

Piper se instala como biblioteca Python mediante `requirements.txt`; sus pesos ONNX se descargan mediante el manifiesto. El script de compilación no descarga modelos.

Whisper permanece cargado en un servidor local. Cada grabación empieza al pulsar `v` y termina al soltarla. El texto reconocido se imprime en la terminal antes de procesar la orden.

Whisper reconoce voz y Piper genera el audio de respuesta; la voz se carga solo al iniciar el programa y se reproduce con `aplay`. Los anuncios usan el último evento de YOLO y solo incluyen nombres de objetos, sin confianza ni coordenadas.

La precisión depende del ruido, el micrófono y el tamaño del modelo. Si una orden se transcribe incorrectamente, la terminal permite revisar exactamente qué texto recibió el asistente.

## Arquitectura

| Archivo | Responsabilidad |
| --- | --- |
| `main.py` | Inicia el listener de teclado, enruta órdenes y crea cámara/YOLO de forma diferida. |
| `clases/manejo_video.py` | Implementación de cámara OpenCV y captura limitada por software. |
| `clases/controlador_modelo.py` | Carga de pesos locales y conversión de salida YOLO al modelo de dominio. |
| `clases/deteccion.py` | Tipos inmutables `BoundingBox`, `DetectedObject`, `DetectionEvent` y `DetectionResult`. |
| `clases/contratos.py` | Protocolos de fuente de video, detector, pantalla, consumidor y matcher de órdenes. |
| `clases/pantalla.py` | Vista previa OpenCV y detección de la tecla para salir. |
| `clases/coordinador_vision.py` | Coordinación de captura, inferencia, publicación de eventos y limpieza de recursos. |
| `clases/controlador_voz.py` | Captura de audio con ALSA, transcripción con un servidor persistente whisper.cpp, enrutamiento de órdenes y síntesis local Piper. |
| `clases/entrada_teclado.py` | Detecta la pulsación sostenida de `v` y activa el inicio/cierre de grabación. |
| `clases/enrutador_comandos.py` | Normaliza y compara transcripciones con RapidFuzz; valida las definiciones de órdenes. |
| `clases/comandos_sistema.py` | Resuelve intención, entidades, contexto, selecciones y aclaraciones de órdenes del sistema. |
| `clases/catalogo_sistema.py` | Carga carpetas XDG autorizadas y descubre aplicaciones instaladas mediante `.desktop`. |
| `clases/ejecutor_sistema_linux.py` | Abre recursos del catálogo sin `shell=True` ni texto de voz en comandos. |
| `clases/gestor_modelos.py` | Valida el manifiesto, resuelve ubicaciones compatibles y descarga archivos con SHA256 y reemplazo atómico. |
| `config/voice_commands.json` | Frases de cámara y apertura, variantes de órdenes, pistas de entidad y descripciones habladas. |
| `config/intenciones_sistema.json` | Umbral de entidad, límites de ambigüedad, tiempo de contexto, cancelaciones y selecciones numéricas. |
| `config/carpetas.json` | IDs, alias y rutas/fallbacks XDG de carpetas autorizadas. |
| `config/aplicaciones.json` | Alias opcionales ligados a IDs de aplicaciones `.desktop`. |
| `config/modelos.json` | IDs, rutas relativas, fuentes, tamaños y SHA256 de cada modelo. |
| `config/ajustes.json` | FPS, intervalos, umbrales y modelo Whisper activo. |
| `scripts/` | Descarga/verificación de modelos, hashes, compilación Whisper y medición opcional de recursos. |
| `vendor/` | Herramientas descargadas o compiladas; ignorado por Git. |
| `modelos/` | Compatibilidad local de desarrollo; los modelos no se versionan. |

Los protocolos desacoplan las implementaciones: se puede sustituir la cámara, el modelo o la pantalla sin cambiar el coordinador. El formato `DetectionEvent` sirve como contrato estable para añadir registro, almacenamiento o comunicación con otros módulos.

Documentación modular del código:

- [Orquestación de la aplicación](./docs/aplicacion.md)
- [Control por voz, Whisper y Piper](./docs/voz.md)
- [Captura y visualización de cámara](./docs/camara.md)
- [Detector YOLO](./docs/detector.md)
- [Coordinación del ciclo de visión](./docs/coordinador.md)
- [Contratos y eventos](./docs/contratos.md)
- [Interpretación de órdenes del sistema](./docs/comandos_sistema.md)
- [Gestión de modelos y herramientas](./docs/modelos.md)
- [Medición de rendimiento](./docs/rendimiento.md)

## Integrar un consumidor (por ejemplo, audio)

Implementa `DetectionListener.on_detection(event)` y pásalo en `listeners` al crear `VisionCoordinator`, o añádelo mediante `add_listener`. Ejemplo:

```python
class MiConsumidor:
    def on_detection(self, event):
        datos = event.to_dict()
        # Enviar o registrar los datos en el módulo correspondiente.
```

La entrega de eventos es síncrona: cada consumidor se ejecuta dentro del ciclo de visión. Para procesamiento de audio, red o almacenamiento que tarde, el consumidor debería enviar el evento a una cola y procesarlo en un worker independiente para no frenar la captura.

La estructura de evento serializada incluye un instante UTC ISO 8601, dimensiones y una lista `objects`; cada objeto tiene `label`, `confidence` y `bounding_box` con coordenadas en píxeles:

```json
{
  "timestamp": "2026-10-21T12:00:00+00:00",
  "frame_width": 640,
  "frame_height": 480,
  "objects": [
    {
      "label": "bus",
      "confidence": 0.91,
      "bounding_box": {"x1": 15.0, "y1": 20.0, "x2": 300.0, "y2": 240.0}
    }
  ]
}
```

## Pruebas

Instala el entorno de desarrollo y ejecuta las pruebas desde la raíz:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

Las pruebas usan componentes simulados para modelos y voz; no requieren descargar modelos ni disponer de cámara/micrófono. La inferencia local real puede probarse sin cámara con una imagen o un fotograma NumPy y `YOLOModelController`.

## Limpieza manual del historial Git

El commit de higiene deja de rastrear `modelos/` en la versión actual, pero no elimina los binarios grandes de los commits anteriores. Antes de subir la rama, la limpieza histórica debe hacerse manualmente. **No ejecutes estos comandos sin revisar el impacto, cerrar la aplicación y coordinarlo con quienes tengan clones del repositorio.** Haz primero una copia externa de los modelos y un bundle del historial:

```bash
cp -a modelos "$HOME/modelos-backup-$(date +%Y%m%d-%H%M%S)"
git bundle create ../asistente-antes-de-filter-repo.bundle --all
```

Después de verificar ambas copias, estos son los comandos que reescriben el historial y actualizan GitHub. Se muestran como referencia; no forman parte de los scripts del proyecto:

```bash
git filter-repo --path modelos/ --invert-paths
git remote add origin https://github.com/Cyraxevil7/Asistente-virtual-offline.git
git push --force --all origin
git push --force --tags origin
```

`git filter-repo` elimina `modelos/` de todos los commits alcanzados por las referencias que reescribe. `push --force` reemplaza el historial remoto; los colaboradores necesitarán volver a clonar o sincronizar cuidadosamente sus ramas. Los archivos locales no se borran con la exclusión de Git ni con el commit que los retiró del índice.

## Scripts experimentales existentes

- `trainning.py` y `pruebas.py` contienen intentos de entrenamiento. Antes de ejecutar entrenamiento, revisa su configuración, rutas, dataset y espacio de almacenamiento. En particular, `pruebas.py` elimina las carpetas `runs` y `datasets` relativas al directorio actual antes de entrenar; no lo ejecutes si contienen datos que quieras conservar.
- `MODELO.PY` ejecuta una predicción sobre una URL de imagen y guarda el resultado. Ese flujo depende de internet y no forma parte del ciclo de visión local.
- Estos scripts son experimentales e independientes del punto de entrada `main.py`.

## Próximas etapas posibles

1. Definir un módulo de registro persistente para eventos y rotación de archivos.
2. Incorporar una cola o bus de eventos para desacoplar consumidores lentos.
3. Mejorar la detección de preguntas y añadir comandos adicionales de voz.
4. Añadir acciones de cierre, búsqueda y lectura mediante nuevos ejecutores explícitos.
5. Ampliar pruebas con grabaciones de voz de prueba y manejo de errores de hardware.

El resumen del ciclo de cámara está en [DETECCION_CAMARA.md](./DETECCION_CAMARA.md). La documentación modular detallada está en `docs/`.
