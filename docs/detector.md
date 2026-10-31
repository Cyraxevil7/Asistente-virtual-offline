# Detector de objetos YOLO

[`clases/controlador_modelo.py`](../clases/controlador_modelo.py) implementa `YOLOModelController`, adaptador entre Ultralytics y los tipos de dominio del proyecto.

## Modelo y entrada

El controlador comprueba la ruta local del modelo y el umbral de confianza antes de cargar YOLO. El punto de entrada configura `modelos/yolo11n.pt` y el umbral predeterminado es `0.25`. El modelo se instancia de forma diferida: no se carga hasta que la orden de voz abre la sesión de visión.

## Inferencia y salida

`detect(frame)` ejecuta la inferencia sobre un fotograma NumPy. Convierte etiquetas, confianza y cajas delimitadoras en objetos `DetectedObject`, y conserva ancho, alto y hora UTC en `DetectionEvent`. También devuelve el fotograma anotado para mostrarlo en pantalla.

Los errores de archivo o de inferencia se propagan para que la aplicación no presente un resultado vacío como si fuera exitoso. El contrato del resultado está descrito en [contratos y eventos](./contratos.md).
