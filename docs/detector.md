# Detector de objetos YOLO

[`clases/controlador_modelo.py`](../clases/controlador_modelo.py) implementa `YOLOModelController`, adaptador entre Ultralytics y los tipos de dominio del proyecto.

## Modelo y entrada

El modelo `yolo11n` se declara en `config/modelos.json`; `ModelManager` resuelve la ruta y valida tamaño/hash al descargarlo. `config/ajustes.json` conserva el umbral de confianza predeterminado `0.25`. YOLO y OpenCV se importan y el modelo se instancia de forma diferida: no se cargan hasta que la orden de voz abre la sesión de visión.

## Inferencia y salida

`detect(frame)` ejecuta la inferencia sobre un fotograma NumPy. Convierte etiquetas, confianza y cajas delimitadoras en objetos `DetectedObject`, y conserva ancho, alto y hora UTC en `DetectionEvent`. También devuelve el fotograma anotado para mostrarlo en pantalla.

Los errores de archivo o de inferencia se propagan para que la aplicación no presente un resultado vacío como si fuera exitoso. El contrato del resultado está descrito en [contratos y eventos](./contratos.md).
