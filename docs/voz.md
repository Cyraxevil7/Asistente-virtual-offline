# Control por voz, Whisper y Piper

La implementación está en [`clases/controlador_voz.py`](../clases/controlador_voz.py). Whisper.cpp reconoce voz; Piper sintetiza la respuesta. Ambos se ejecutan localmente.

## Selección de modelo e idioma

La ruta del modelo activo se configura con `WHISPER_MODEL_PATH` en [`main.py`](../main.py); actualmente apunta a `modelos/ggml-base.bin`. Para cambiar el tamaño, descarga otro modelo GGML compatible y modifica esa constante para que apunte al archivo elegido. El reconocimiento solicita español mediante el campo `language=es` que `WhisperCppCommandRecognizer` envía al servidor en [`clases/controlador_voz.py`](../clases/controlador_voz.py).

## Escucha y transcripción

`WhisperCppCommandRecognizer` inicia un `whisper-server` persistente y espera su endpoint de salud. `arecord` transmite audio PCM mono a 16 kHz mientras se mantiene pulsada la tecla `v`. Al soltarla, se cierra el flujo, se empaqueta la grabación completa como WAV, se envía a `/inference` y se extrae el texto de la respuesta JSON. Whisper conserva el modelo cargado entre peticiones.

`PushToTalkKeyboard` recibe eventos globales de pulsación y liberación usando `pynput`; protege contra repeticiones de tecla para que cada pulsación inicie una sola grabación. `VoiceAssistant` imprime la transcripción con hora local y procesa la orden solo después de que Whisper termine. La captura no tiene un límite temporal fijo.

La escucha global requiere una sesión gráfica compatible con X11. En sesiones Wayland, el sistema puede impedir que `pynput` reciba teclas globales; inicia una sesión X11 si la tecla no es detectada.

## Órdenes y tolerancia a errores

Las órdenes configurables están en [`config/voice_commands.json`](../config/voice_commands.json). Cada identificador tiene una descripción hablada y una lista de frases. El motor `RapidFuzzCommandMatcher` implementa el contrato `CommandMatcher` y se compara con `WRatio` usando un umbral fijo del **80%**. La configuración y las frases se cargan una sola vez al construir el asistente, no en cada transcripción.

La respuesta depende del resultado:

- Una coincidencia exacta (100%) ejecuta su acción.
- Una coincidencia aproximada desde 80% pide confirmación por Piper; responde «sí», di «no» o repite la orden con más claridad. La acción queda pendiente y no se ejecuta hasta aclararla.
- Si varias órdenes distintas quedan a cinco puntos o menos de la mejor coincidencia, Piper enumera sus descripciones y pide elegir una.
- Si ninguna llega a 80%, Piper indica que no encontró el comando y ofrece las acciones disponibles.

Las frases se normalizan para ignorar mayúsculas, tildes y puntuación. Puedes añadir órdenes futuras creando una definición con `description` y `phrases` en el JSON, y registrando su acción mediante `command_handlers` al construir `VoiceAssistant`. Así el reconocimiento y la lógica de desambiguación no necesitan duplicarse. Las definiciones inválidas, frases repetidas entre órdenes o acciones sin handler se notifican explícitamente.

Se conservó deliberadamente la frase `"de ten la camara"` en la lista de cierre, como parche para ciertos problemas de transcripción. Para dar cualquier orden, mantén `v` mientras hablas y suéltala para procesar la frase.

## Respuestas y periodicidad

Al activarse la cámara, el asistente conserva las detecciones más recientes. Piper anuncia cada cinco segundos los nombres únicos de objetos traducidos al español; si la escena está vacía, dice que no detecta objetos. Las preguntas reconocidas mientras la cámara ya está abierta también pueden generar una respuesta inmediata.

`PiperSpeechOutput` carga la voz `modelos/voces/es_ES-sharvard-medium.onnx` una vez y usa `aplay` para reproducir el WAV sintetizado. El intervalo se configura al crear `VoiceAssistant` en [`main.py`](../main.py).

## Errores y límites

Si Whisper no inicia o falla la captura o transcripción, el error se registra y se muestra en la terminal. Cierra la aplicación con `Ctrl+C`; el reconocedor detiene la grabación activa y el servidor local. El micrófono solo se captura mientras `v` está pulsada. La guía de la tecla está en [`clases/entrada_teclado.py`](../clases/entrada_teclado.py).
