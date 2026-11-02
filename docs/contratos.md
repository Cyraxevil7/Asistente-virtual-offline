# Contratos y eventos

Los protocolos de [`clases/contratos.py`](../clases/contratos.py) permiten sustituir módulos manteniendo la coordinación:

- `VideoSource`: `read()` produce un fotograma NumPy; `close()` libera la fuente.
- `ObjectDetector`: `detect(frame)` devuelve un `DetectionResult`.
- `Display`: muestra fotogramas y comunica cuándo debe cerrarse.
- `DetectionListener`: recibe eventos mediante `on_detection(event)`.
- `CommandMatcher`: asocia una transcripción con cero o más candidatas disponibles.
- `IntentResolver`: convierte texto libre en intención, parámetros y resultado de resolución.

`CommandCandidate` contiene el identificador de la orden, su descripción hablada, la frase configurada coincidente y el puntaje de similitud. `CommandMatch` agrupa las candidatas más relevantes para que el controlador de voz pueda ejecutar una coincidencia exacta, solicitar confirmación o pedir aclaración. La implementación predeterminada usa [`RapidFuzzCommandMatcher`](../clases/enrutador_comandos.py); puede sustituirse mediante el parámetro `command_matcher` de `VoiceAssistant`.

`IntentResult` contiene la intención, parámetros, tipo e ID de entidad, candidatas, estado de interpretación y motivo de aclaración. `confidence` conserva la puntuación RapidFuzz de 0 a 100; no es una probabilidad. `IntentCandidate` representa cada recurso disponible o no disponible con su tipo, ID, nombre y puntuación.

`VoiceAssistant` conserva el `CommandMatcher` actual para las órdenes de cámara e inyecta un manejador opcional para órdenes del sistema. `RapidFuzzIntentResolver` y `SystemCommandHandler` usan esos contratos para resolver la intención de apertura y mantener el diálogo sin acoplar la detección visual al sistema operativo. Consulta [interpretación de órdenes del sistema](./comandos_sistema.md) para el flujo, los catálogos y los límites de seguridad.

## Datos de detección

[`clases/deteccion.py`](../clases/deteccion.py) define tipos inmutables:

- `BoundingBox`: coordenadas de la caja delimitadora en píxeles.
- `DetectedObject`: etiqueta, confianza y caja.
- `DetectionEvent`: instante UTC, dimensiones del fotograma y colección de objetos.
- `DetectionResult`: evento más imagen anotada.

`DetectionEvent.to_dict()` produce una estructura JSON lista para registro o transporte. El coordinador publica los eventos a todos los listeners de forma síncrona; si se integra un consumidor lento, debe delegar su trabajo a una cola o worker para no retrasar la captura.

El coordinador utiliza estos contratos para unir OpenCV, YOLO y voz sin acoplarlos entre sí.
