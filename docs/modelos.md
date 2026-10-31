# Modelos, descargas y herramientas locales

El catálogo versionado está en [`config/modelos.json`](../config/modelos.json) y la implementación en [`clases/gestor_modelos.py`](../clases/gestor_modelos.py). El manifiesto registra para cada archivo su ID, ruta relativa, URL oficial, SHA256, tamaño esperado y si es requerido.

## Ubicación

Los modelos se guardan fuera del repositorio en el directorio de datos del usuario, bajo `asistente/modelos` (por ejemplo, `~/.local/share/asistente/modelos` en Linux). La variable `ASISTENTE_MODELS_DIR` permite sobrescribir esa ubicación.

El manifiesto reserva subdirectorios `whisper/`, `piper/` y `yolo/` en el directorio de datos. Para no mover ni borrar las copias existentes, durante desarrollo se mantienen como fallback las rutas anteriores dentro de `modelos/`. Las descargas nuevas no se escriben en el repositorio.

`ModelManager.is_ready(id)` comprueba existencia y tamaño sin calcular SHA256. `ensure(id, on_progress)` valida el SHA256 antes de publicar la descarga, usa un archivo `.part`, reanuda si el servidor acepta solicitudes HTTP Range y reemplaza el destino de forma atómica solo tras verificar el resultado.

## Descargar, cambiar y verificar

```bash
python scripts/descargar_modelos.py
python scripts/descargar_modelos.py --solo whisper-tiny
python scripts/descargar_modelos.py --verificar
python scripts/calcular_hashes.py
```

La descarga normal incluye solo los modelos requeridos. `whisper-tiny` es opcional; para activarlo, cambia `whisper_model_id` en `config/ajustes.json` y descárgalo con `--solo whisper-tiny`. Para completar/actualizar el manifiesto con archivos locales, `calcular_hashes.py` imprime su tamaño y SHA256. `--verificar` vuelve a calcular los hashes de los modelos requeridos (o del ID indicado con `--solo`) y retorna error si falta un archivo o no coincide.

La aplicación también prepara los modelos que necesite al iniciar: primero la voz Piper y su configuración, después Whisper y YOLO. Así, si la voz ya está disponible, los mensajes de progreso se anuncian por audio. Antes de que Piper esté disponible se informa por terminal y se intenta `espeak-ng`/`espeak` si ya está instalado; no se instala ni se requiere automáticamente.

## Servidor Whisper y Piper

`whisper-server` no es un modelo y no se guarda en Git. En Linux, `bash scripts/construir_whisper.sh` clona el repositorio oficial de whisper.cpp en el directorio ignorado `vendor/` y compila el servidor para CPU. El entorno necesita Git, CMake y un compilador C/C++.

Piper se usa como biblioteca Python `piper-tts`, declarada en `requirements.txt`; el asistente no necesita mantener una copia de su código fuente ni otro ejecutable Piper en `vendor/`. El modelo de voz y su archivo `.onnx.json` sí se descargan por separado y se verifican.

Los valores SHA256 y tamaños de Whisper y Piper se contrastaron con el manifiesto público de Hugging Face y con los archivos locales existentes; el hash de YOLO coincide con el digest del asset de la versión `v8.4.0` de Ultralytics. El manifiesto contiene las URLs verificadas para volver a obtenerlos.
