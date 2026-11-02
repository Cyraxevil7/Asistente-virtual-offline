# Control por voz, Whisper y Piper

La implementación está en [`clases/controlador_voz.py`](../clases/controlador_voz.py). Whisper.cpp reconoce voz; Piper sintetiza la respuesta. Ambos se ejecutan localmente.

## Selección de modelo e idioma

El modelo se selecciona mediante `whisper_model_id` en `config/ajustes.json` (por defecto `whisper-base`; `whisper-tiny` es la alternativa ligera). Sus URL, tamaños y SHA256 están en `config/modelos.json`. Los archivos se guardan fuera del repositorio por defecto, bajo el directorio de datos del usuario; `ASISTENTE_MODELS_DIR` permite cambiarlo. En desarrollo, `ModelManager` reconoce también el layout local previo bajo `modelos/`. El reconocimiento solicita español mediante el campo `language=es` que `WhisperCppCommandRecognizer` envía al servidor.

## Escucha y transcripción

`WhisperCppCommandRecognizer` inicia un `whisper-server` persistente y espera su endpoint de salud. `arecord` transmite audio PCM mono a 16 kHz mientras se mantiene pulsada la tecla `v`. Al soltarla, se cierra el flujo, se empaqueta la grabación completa como WAV, se envía a `/inference` y se extrae el texto de la respuesta JSON. Whisper conserva el modelo cargado entre peticiones.

`PushToTalkKeyboard` recibe eventos globales de pulsación y liberación usando `pynput`; protege contra repeticiones de tecla para que cada pulsación inicie una sola grabación. `VoiceAssistant` imprime la transcripción con hora local y procesa la orden solo después de que Whisper termine. La captura no tiene un límite temporal fijo.

Al pulsar `v`, `VoiceAssistant` pausa `PiperSpeechOutput` antes de abrir el micrófono: termina el reproductor activo e invalida cualquier audio que aún se estuviera sintetizando. Mientras se mantiene la tecla no se inicia otra reproducción. Al soltarla, la salida de voz se reanuda y Whisper transcribe la grabación.

La escucha global requiere una sesión gráfica compatible con X11. En sesiones Wayland, el sistema puede impedir que `pynput` reciba teclas globales; inicia una sesión X11 si la tecla no es detectada.

## Órdenes y tolerancia a errores

Las órdenes configurables están en [`config/voice_commands.json`](../config/voice_commands.json). Cada identificador tiene una descripción hablada y una lista de frases. `open_resource` contiene las variantes de apertura, los términos que indican carpeta o aplicación y palabras gramaticales que deben ignorarse al resolver el objetivo. `RapidFuzzCommandMatcher` implementa el contrato `CommandMatcher`; compara frases con `WRatio` usando el umbral del **80%** configurado en `config/ajustes.json`. La configuración se carga una sola vez al construir el asistente, no en cada transcripción.

La respuesta depende del resultado:

- Una coincidencia exacta (100%) ejecuta su acción.
- Una coincidencia aproximada desde 80% pide confirmación por Piper; responde «sí», di «no» o repite la orden con más claridad. La acción queda pendiente y no se ejecuta hasta aclararla.
- Si varias órdenes distintas quedan a cinco puntos o menos de la mejor coincidencia, Piper enumera sus descripciones y pide elegir una.
- Si ninguna llega a 80%, Piper indica que no encontró el comando y ofrece las acciones disponibles.

Las frases se normalizan para ignorar mayúsculas, tildes y puntuación. Las órdenes parametrizadas, como abrir una carpeta o aplicación, se atienden mediante el manejador del sistema y no requieren una acción directa en `command_handlers`. Para extender su vocabulario, edita `open_resource` en el JSON; para incorporar otra orden independiente, crea una definición con `description` y `phrases` y registra su acción mediante `command_handlers` al construir `VoiceAssistant`. Así el reconocimiento y la lógica de desambiguación no necesitan duplicarse. Las definiciones inválidas, frases repetidas entre órdenes o acciones sin handler se notifican explícitamente.

Se conservó deliberadamente la frase `"de ten la camara"` en la lista de cierre, como parche para ciertos problemas de transcripción. Para dar cualquier orden, mantén `v` mientras hablas y suéltala para procesar la frase.

## Respuestas y periodicidad

Al activarse la cámara, el asistente conserva las detecciones más recientes. Piper anuncia cada cinco segundos los nombres únicos de objetos traducidos al español; si la escena está vacía, dice que no detecta objetos. Las preguntas reconocidas mientras la cámara ya está abierta también pueden generar una respuesta inmediata.

`PiperSpeechOutput` carga la voz `piper-es-voz` una vez y usa `aplay` para reproducir el WAV sintetizado. La aplicación prepara primero esa voz y la usa para anunciar descargas posteriores. Si falta y el sistema tiene `espeak-ng` o `espeak`, intenta usarlo solo como aviso de instalación; no es una dependencia obligatoria. El intervalo se configura en `config/ajustes.json`.

## Errores y límites

Si Whisper no inicia o falla la captura o transcripción, el error se registra y se muestra en la terminal. Cierra la aplicación con `Ctrl+C`; el reconocedor detiene la grabación activa y el servidor local. El micrófono solo se captura mientras `v` está pulsada. La guía de la tecla está en [`clases/entrada_teclado.py`](../clases/entrada_teclado.py).

`VoiceAssistant` conserva RapidFuzz para las órdenes de cámara y envía primero cada transcripción al manejador modular del sistema. Este resuelve órdenes de apertura a carpetas autorizadas o aplicaciones `.desktop`, pregunta por objetivos incompletos y permite elegir entre alternativas. Las frases y catálogos se configuran externamente; consulta [interpretación de órdenes del sistema](./comandos_sistema.md). La ruta anterior de cámara permanece activa para las órdenes de visión.
