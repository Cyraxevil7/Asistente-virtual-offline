# Orquestación de la aplicación

El punto de entrada es [`main.py`](../main.py). Mantiene el flujo de arranque y conecta el reconocedor, la cámara, YOLO, la pantalla y los consumidores de eventos.

## Inicio

1. Carga los ajustes de `config/ajustes.json` y valida `config/modelos.json`.
2. Prepara Piper primero; si faltan otros modelos requeridos, descarga y anuncia el progreso con esa voz.
3. Inicia Whisper y el listener global de teclado; la cámara queda cerrada y no se graba audio.
4. Al mantener `v`, se captura voz. Al soltarla, Whisper transcribe el audio completo y el texto se muestra en la terminal.
5. Espera órdenes de cámara en una cola entre el worker de transcripción y el hilo principal.

YOLO y OpenCV se importan dentro de la rama que procesa la orden de apertura, de modo que ni esos paquetes ni el modelo visual se cargan mientras el usuario solo está probando el micrófono.

## Ciclo de vida

- Al recibir una orden de apertura, la aplicación limpia el evento de cierre, crea YOLO, abre la cámara a 3 FPS y ejecuta `VisionCoordinator`.
- «Cerrar cámara» establece un evento compartido; el coordinador termina el ciclo y libera cámara y ventana.
- La tecla `q` también termina el ciclo de visión.
- Después del cierre, la escucha de voz continúa. El evento JSON de cada detección se imprime en la terminal.
- Al interrumpir la aplicación, el bloque `finally` detiene Whisper y los workers de voz.

Las tasas y los umbrales se configuran en `config/ajustes.json`; las rutas de archivos se resuelven desde `config/modelos.json` mediante `ModelManager`. La captura solicita 3 FPS, la inferencia ocurre cada dos segundos y el anuncio hablado se repite cada cinco segundos. La detección global de teclas usa `pynput` y requiere una sesión gráfica X11 compatible.

Los archivos se buscan primero en el directorio de datos del usuario; `ASISTENTE_MODELS_DIR` permite seleccionar otro. Durante desarrollo se mantiene compatibilidad con los modelos ya existentes bajo `modelos/`. El servidor Whisper se busca en `vendor/whisper.cpp/build/bin/whisper-server` y después en la ruta local previa; `ASISTENTE_WHISPER_SERVER` permite indicar otra ubicación.

Para instalar modelos: `python scripts/descargar_modelos.py`. Para ejecutar: `python main.py`. Construcción de `whisper-server`: `bash scripts/construir_whisper.sh`. La guía de rutas y descargas está en [gestión de modelos](./modelos.md).
