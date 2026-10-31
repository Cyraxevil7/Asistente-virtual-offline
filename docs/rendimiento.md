# Medición de rendimiento y memoria

El equipo objetivo es un ThinkPad con Intel i5 de 6.ª generación, 8 GB de RAM y gráfica integrada. No se publican estimaciones de memoria o CPU: los resultados deben medirse en ese equipo y con los modelos y versiones efectivamente instalados.

## Carga de componentes

- La cámara, OpenCV, Ultralytics y YOLO se importan/cargan únicamente al abrir la cámara.
- Whisper se ejecuta en `whisper-server`, un proceso hijo que se puede medir por separado.
- Piper y YOLO se ejecutan dentro del proceso Python de la aplicación; `psutil` no puede atribuir con exactitud su RSS/CPU individual sin moverlos a procesos separados.
- Whisper permanece disponible mientras la cámara está activa para conservar la orden hablada «cerrar cámara». Esa coexistencia es necesaria para mantener el control por voz actual. La tecla `v` limita la captura de audio al tiempo que se pulsa.

## Capturar mediciones

Instala el extra de desarrollo con `python -m pip install -r requirements-dev.txt`. Inicia la aplicación y obtén su PID:

```bash
pgrep -n -f '[p]ython main.py'
```

En otra terminal, ejecuta el medidor mientras la aplicación permanece en cada estado. Sustituye `PID` por el número anterior:

```bash
python scripts/medir_recursos.py --pid PID --fase reposo --duracion 120
python scripts/medir_recursos.py --pid PID --fase camara --duracion 120
python scripts/medir_recursos.py --pid PID --fase transcripcion --duracion 120
```

Para registrar cada fase, deja la cámara cerrada, ábrela con una orden de voz y realiza una transcripción push-to-talk, respectivamente. Corre el script durante cada etapa; genera muestras cada segundo por defecto. El CSV se escribe fuera del repositorio en el directorio de datos del usuario. `--intervalo`, `--duracion` y `--salida` permiten ajustar el muestreo.

El registro incluye RSS/CPU del proceso principal, RSS/CPU del proceso Whisper y RSS total del árbol de procesos. La memoria de YOLO/Piper queda dentro del RSS principal; comparar `reposo` con `camara` permite observar el cambio real del proceso, pero no atribuirlo exclusivamente a YOLO. No ejecutes varias instancias de la app durante la medición.

Los resultados son específicos del equipo, resolución de cámara, sistema operativo, estado de caché y modelos seleccionados. Registra esos datos junto al CSV al comparar cambios; no se consideran valores de referencia hasta medirlos en el hardware destino.
