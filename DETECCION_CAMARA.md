# Captura y detección de cámara

Esta nota resume el ciclo de cámara. El detalle modular está en [docs/camara.md](./docs/camara.md), y la guía general del proyecto está en [README.md](./README.md).

El modelo `yolo11n` se obtiene mediante `ModelManager` y, por defecto, se almacena fuera del repositorio. Durante desarrollo se mantiene compatibilidad con el archivo local anterior `modelos/yolo11n.pt`; consulta [gestión de modelos](./docs/modelos.md).

La cámara solicita 3 fotogramas por segundo y la aplicación limita la frecuencia de lectura por software. El modelo hace una inferencia cada 2 segundos. La ventana conserva la última imagen anotada entre inferencias, mientras la cámara continúa capturando. El controlador de la cámara puede ignorar el FPS solicitado.

Al ejecutar `python main.py`, la cámara permanece cerrada hasta reconocer «¿qué ves?» o una frase equivalente. Para dar la orden, mantén `v` pulsada mientras hablas y suéltala para enviar el audio completo a Whisper. «Cerrar cámara» o `q` detienen la sesión y liberan los recursos; luego puedes mantener `v` para otra orden. Los errores de cámara, modelo o consumidores se propagan.

Mientras la cámara está abierta, YOLO publica detecciones y Piper anuncia los objetos cada cinco segundos. Consulta [docs/voz.md](./docs/voz.md) para las variantes de órdenes y [docs/coordinador.md](./docs/coordinador.md) para el ciclo completo.
