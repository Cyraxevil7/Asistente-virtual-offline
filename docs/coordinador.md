# Coordinador del ciclo de visión

[`clases/coordinador_vision.py`](../clases/coordinador_vision.py) conecta una fuente de video, un detector, una pantalla y listeners sin depender de sus implementaciones concretas.

## Ciclo

1. Lee un fotograma de la fuente.
2. Ejecuta inferencia cuando han transcurrido dos segundos desde la detección anterior.
3. Publica `DetectionEvent` a cada listener y actualiza el último fotograma anotado.
4. Muestra la imagen anotada entre inferencias.
5. Continúa hasta que la pantalla indica cierre o se establece el `stop_event` opcional.

El evento externo permite detener la cámara por voz sin detener el reconocedor. La tecla `q` ofrece una alternativa local. Un bloque `finally` libera siempre la fuente de video y la pantalla; los errores de componentes o listeners se propagan.

## Extensión

Los listeners implementan `DetectionListener.on_detection(event)`. El asistente de voz usa este mecanismo para actualizar la escena que anuncia cada cinco segundos; `ConsoleDetectionLogger` registra el evento JSON. Consulta [contratos y eventos](./contratos.md) para el formato de datos.
