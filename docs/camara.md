# Captura y visualización de cámara

[`clases/manejo_video.py`](../clases/manejo_video.py) implementa la fuente OpenCV `OpenCVCamera`; [`clases/pantalla.py`](../clases/pantalla.py) implementa la interfaz `OpenCVDisplay`.

## Apertura y tasa de captura

La instancia de cámara se crea al procesar una orden válida de apertura, no durante el arranque del asistente. La configuración actual solicita 3 FPS al controlador y aplica también un intervalo entre lecturas para limitar el consumo de la aplicación. El controlador físico puede ignorar la solicitud de FPS.

`read()` devuelve fotogramas NumPy y propaga un error si falla la captura. `close()` libera `VideoCapture` y se puede invocar durante la limpieza del ciclo. La pantalla muestra la última imagen anotada y reconoce `q` para detener la sesión.

## Cierre por voz

La orden de voz establece un evento de parada compartido con [`VisionCoordinator`](./coordinador.md). El ciclo termina en su siguiente comprobación y su bloque de limpieza cierra la fuente y la ventana. El worker del micrófono permanece activo, por lo que la cámara se puede volver a iniciar con otra orden.

El ciclo está descrito también en [DETECCION_CAMARA.md](../DETECCION_CAMARA.md).
