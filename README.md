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
- Reconocimiento tolerante a errores con RapidFuzz: umbral del 80%, confirmación de coincidencias aproximadas y aclaración de órdenes ambiguas.
- La cámara solo se abre al reconocer una petición para ver; YOLO también se carga de forma diferida en ese momento.
- Anuncios hablados con los nombres de los objetos detectados, repetidos cada cinco segundos.
- Cierre por voz con variantes de «cerrar cámara» o con la tecla `q`; el asistente permanece en modo de escucha.
- Liberación de cámara y ventana al finalizar el ciclo, incluso cuando un componente falla.
- Pruebas unitarias del coordinador, el evento y el adaptador YOLO.

El FPS configurado es una solicitud al controlador; algunas cámaras pueden ignorarla. El límite de lectura por software reduce la frecuencia de captura de la aplicación, pero no garantiza cómo el controlador adquiere internamente los fotogramas.

## Requisitos

- Python 3.10 o posterior (el entorno actual usa Python 3.12).
- Cámara compatible con OpenCV para ejecutar la vista en vivo.
- Micrófono y `arecord` (ALSA) para transcribir voz en Linux.
- Sesión gráfica X11 para detectar globalmente la pulsación y liberación de `v` con `pynput`.
- `aplay` (ALSA) para reproducir las respuestas generadas por Piper en Linux.
- El runtime Piper (`piper-tts`) y una voz española `.onnx` con su configuración `.onnx.json`.
- `whisper-server` de whisper.cpp y un modelo GGML multilingüe para reconocer comandos localmente.
- Dependencias de `requirements.txt`.
- RapidFuzz, instalado junto con las demás dependencias para comparar transcripciones con las frases configuradas.
- Pesos YOLO disponibles en `modelos/` para inferencia local. El repositorio de trabajo incluye `modelos/yolo11n.pt` y `modelos/yolo26n.pt`.

La voz española usada por defecto es `es_ES-sharvard-medium`, guardada en `modelos/voces/`. Si no tienes sus archivos, instálalos desde el entorno virtual con:

```bash
python -m piper.download_voices --download-dir modelos/voces es_ES-sharvard-medium
```

La ejecución de la cámara requiere un entorno con soporte de ventana gráfica. Para usar GPU, instala una versión de PyTorch compatible con tu hardware y CUDA; en CPU, Ultralytics puede ejecutarse sin configurar CUDA.

## Instalación

Desde la raíz del proyecto, crea y activa un entorno virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

En Windows PowerShell, activa el entorno con:

```powershell
.venv\Scripts\Activate.ps1
```

Instala las dependencias:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

En Linux quizá sea necesario instalar paquetes del sistema para OpenCV o soporte gráfico, dependiendo de la distribución. Para aceleración GPU, consulta las instrucciones oficiales de PyTorch para elegir la compilación apropiada.

## Ejecutar el asistente

```bash
python main.py
```

Al iniciar, el programa levanta Whisper localmente pero no empieza a grabar. Mantén pulsada `v` mientras dices una frase y suéltala cuando termines; entonces el audio completo se transcribe y el resultado aparece en la terminal. Puedes hacerlo antes o durante la sesión de cámara. Di «¿qué ves?», «¿qué hay delante?» o «¿qué detectas?» para abrirla. La tasa solicitada es 3 FPS; el modelo hace inferencias cada 2 segundos.

Di «cerrar cámara», «cierra la cámara», «apaga la cámara» o «detén la cámara» mientras mantienes `v` para cerrarla. También puedes pulsar `q` en la ventana. Después del cierre, el programa espera otra pulsación de `v`; no mantiene el micrófono grabando. Los eventos JSON siguen apareciendo en la terminal. En Linux sin activar el entorno virtual también se puede usar `.venv/bin/python main.py`.

Las constantes `CAMERA_FRAMES_PER_SECOND`, `DETECTION_INTERVAL_SECONDS`, `MODEL_PATH` y `WHISPER_MODEL_PATH` en `main.py` configuran la tasa de lectura, el intervalo de inferencia, el modelo visual y el modelo de voz, respectivamente. Para cambiar Whisper, modifica `WHISPER_MODEL_PATH` y apunta a otro archivo GGML compatible, por ejemplo `modelos/ggml-small.bin`; el idioma de transcripción se fija por separado en `clases/controlador_voz.py` con `language=es`. Las frases que activan y cierran la cámara se editan en `config/voice_commands.json`, agrupadas por intención; no hace falta modificar código Python para ajustar sus variantes. El matcher RapidFuzz está en `clases/enrutador_comandos.py`, y el umbral usado por el asistente se fija en `COMMAND_SIMILARITY_THRESHOLD` (80%). El margen de ambigüedad predeterminado es de cinco puntos. El umbral de confianza visual predeterminado está en `YOLOModelController` (`0.25`).

### Añadir una orden de voz

Cada entrada de `config/voice_commands.json` requiere un identificador, una `description` que Piper pueda decir y una lista no vacía de `phrases` que Whisper podría transcribir. Las frases se comparan sin distinguir mayúsculas, acentos ni puntuación. Una coincidencia aproximada solicita confirmación antes de ejecutar la acción; órdenes con puntuaciones cercanas requieren que se aclare cuál se desea. Las frases asignadas a órdenes distintas no deben duplicarse.

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

### Dependencias de reconocimiento de voz

El directorio `modelos/ggml-org-whisper.cpp-d2a764c/` contiene el código fuente de whisper.cpp, pero sus archivos `for-tests-*.bin` son marcadores de prueba sin pesos reales. El modelo multilingüe `modelos/ggml-base.bin` y el ejecutable local `whisper-server` deben estar disponibles para usar voz.

Para compilar whisper.cpp en Linux, se requieren CMake y un compilador C/C++:

```bash
python -m pip install cmake
cmake -S modelos/ggml-org-whisper.cpp-d2a764c \
  -B modelos/ggml-org-whisper.cpp-d2a764c/build \
  -DCMAKE_BUILD_TYPE=Release \
  -DWHISPER_BUILD_TESTS=OFF \
  -DWHISPER_BUILD_EXAMPLES=ON \
  -DWHISPER_BUILD_SERVER=ON
cmake --build modelos/ggml-org-whisper.cpp-d2a764c/build \
  --config Release --target whisper-server -j2
```

Descarga el modelo base multilingüe (~142 MiB):

```bash
bash modelos/ggml-org-whisper.cpp-d2a764c/models/download-ggml-model.sh base modelos
```

Whisper permanece cargado en un servidor local. Cada grabación empieza al pulsar `v` y termina al soltarla, así que no se corta por un límite fijo de tiempo. El texto reconocido se imprime en la terminal antes de procesar la orden.

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
| `clases/controlador_voz.py` | Captura de audio con ALSA, transcripción con un servidor persistente whisper.cpp, gestión extensible de órdenes y síntesis local Piper. |
| `clases/entrada_teclado.py` | Detecta la pulsación sostenida de `v` y activa el inicio/cierre de grabación. |
| `clases/enrutador_comandos.py` | Normaliza y compara transcripciones con RapidFuzz; valida las definiciones de órdenes. |
| `config/voice_commands.json` | Descripciones y frases editables para activar y cerrar la cámara por voz. |
| `tests/test_vision.py` | Pruebas unitarias con dobles, sin necesidad de cámara física. |
| `tests/test_voz.py` | Pruebas del formato de respuesta y de las llamadas a herramientas de audio simuladas. |
| `modelos/` | Pesos YOLO locales. |

Los protocolos desacoplan las implementaciones: se puede sustituir la cámara, el modelo o la pantalla sin cambiar el coordinador. El formato `DetectionEvent` sirve como contrato estable para añadir registro, almacenamiento o comunicación con otros módulos.

Documentación modular del código:

- [Orquestación de la aplicación](./docs/aplicacion.md)
- [Control por voz, Whisper y Piper](./docs/voz.md)
- [Captura y visualización de cámara](./docs/camara.md)
- [Detector YOLO](./docs/detector.md)
- [Coordinación del ciclo de visión](./docs/coordinador.md)
- [Contratos y eventos](./docs/contratos.md)

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

Ejecuta las pruebas desde la raíz:

```bash
python -m unittest discover -s tests -v
```

Las pruebas utilizan componentes simulados para verificar serialización, publicación y liberación de recursos. No comprueban la cámara física. La inferencia local puede probarse sin cámara con una imagen o un fotograma NumPy y `YOLOModelController`.

## Scripts experimentales existentes

- `trainning.py` y `pruebas.py` contienen intentos de entrenamiento. Antes de ejecutar entrenamiento, revisa su configuración, rutas, dataset y espacio de almacenamiento. En particular, `pruebas.py` elimina las carpetas `runs` y `datasets` relativas al directorio actual antes de entrenar; no lo ejecutes si contienen datos que quieras conservar.
- `MODELO.PY` ejecuta una predicción sobre una URL de imagen y guarda el resultado. Ese flujo depende de internet y no forma parte del ciclo de visión local.
- Estos scripts son experimentales e independientes del punto de entrada `main.py`.

## Próximas etapas posibles

1. Definir un módulo de registro persistente para eventos y rotación de archivos.
2. Incorporar una cola o bus de eventos para desacoplar consumidores lentos.
3. Mejorar la detección de preguntas y añadir comandos adicionales de voz.
4. Añadir configuración externa para cámara, modelos y umbrales.
5. Ampliar pruebas con grabaciones de voz de prueba y manejo de errores de hardware.

El resumen del ciclo de cámara está en [DETECCION_CAMARA.md](./DETECCION_CAMARA.md). La documentación modular detallada está en `docs/`.
