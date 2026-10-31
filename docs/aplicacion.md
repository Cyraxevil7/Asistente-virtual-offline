# Orquestación de la aplicación

El punto de entrada es [`main.py`](../main.py). Mantiene el flujo de arranque y conecta el reconocedor, la cámara, YOLO, la pantalla y los consumidores de eventos.

## Inicio

1. Crea Whisper y el reconocedor local.
2. Inicia el asistente de voz y el listener global de teclado; la cámara queda cerrada y no se graba audio.
3. Al mantener `v`, se captura voz. Al soltarla, Whisper transcribe el audio completo y el texto se muestra en la terminal.
4. Espera órdenes de cámara en una cola entre el worker de transcripción y el hilo principal.

YOLO y OpenCV se crean dentro de la rama que procesa la orden de apertura, de modo que no se carga el modelo visual ni se abre la cámara mientras el usuario solo está probando el micrófono.

## Ciclo de vida

- Al recibir una orden de apertura, la aplicación limpia el evento de cierre, crea YOLO, abre la cámara a 3 FPS y ejecuta `VisionCoordinator`.
- «Cerrar cámara» establece un evento compartido; el coordinador termina el ciclo y libera cámara y ventana.
- La tecla `q` también termina el ciclo de visión.
- Después del cierre, la escucha de voz continúa. El evento JSON de cada detección se imprime en la terminal.
- Al interrumpir la aplicación, el bloque `finally` detiene Whisper y los workers de voz.

Las rutas de modelos y las tasas predeterminadas se definen junto al punto de entrada. La captura de cámara solicita 3 FPS, la inferencia ocurre cada dos segundos y el anuncio hablado se repite cada cinco segundos. La detección global de teclas usa `pynput` y requiere una sesión gráfica X11 compatible.

Para ejecutar: `python main.py`. Dependencias y construcción de `whisper-server`: [README.md](../README.md).
