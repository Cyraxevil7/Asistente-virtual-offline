"""Interpretación local de órdenes para abrir recursos del sistema."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from rapidfuzz import fuzz

from clases.catalogo_sistema import (
    PROJECT_ROOT,
    SystemResource,
    SystemEntityCatalog,
)
from clases.contratos import IntentCandidate, IntentResult
from clases.enrutador_comandos import (
    DEFAULT_COMMAND_PHRASES_PATH,
    RapidFuzzCommandMatcher,
    normalize_command_text,
)


LOGGER = logging.getLogger(__name__)
DEFAULT_INTENTS_PATH = PROJECT_ROOT / "config" / "intenciones_sistema.json"
_LEGACY_CAMERA_TARGETS = frozenset({"camera", "camara", "webcam"})
_LEGACY_CAMERA_COMMANDS = frozenset({"abrir"})
SYSTEM_OPEN_COMMAND_ID = "open_resource"
_UNSAFE_COMMAND_CHARACTERS = re.compile(r"[/\\;|&$`<>]")
_COMMAND_OPTION = re.compile(r"(?:^|\s)-{1,2}\S+")


class SystemActionExecutor(Protocol):
    """Puerto para sustituir la ejecución Linux por otro sistema operativo."""

    def open_folder(self, entity_id: str) -> None:
        """Abre una carpeta autorizada por su ID estable."""

    def launch_application(self, entity_id: str) -> None:
        """Ejecuta una aplicación descubierta por su ID estable."""


class CommandSpeechOutput(Protocol):
    """Salida de voz mínima que necesita el gestor de comandos."""

    def speak(self, text: str) -> None:
        """Reproduce una respuesta del asistente."""


class ConversationState:
    """Estados públicos del diálogo de órdenes del sistema."""

    WAITING_ORDER = "esperando_orden"
    WAITING_TARGET = "esperando_objetivo"
    WAITING_SELECTION = "esperando_seleccion"
    EXECUTING = "ejecutando"


@dataclass(frozen=True, slots=True)
class IntentConfiguration:
    entity_threshold: int
    ambiguity_margin: int
    max_candidates: int
    context_timeout_seconds: float
    cancel_phrases: frozenset[str]
    selection_phrases: dict[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class PendingOperation:
    intent_id: str
    entity_type: str | None
    target_text: str
    candidates: tuple[IntentCandidate, ...]
    state: str
    expires_at: float


class ConversationContext:
    """Mantiene una sola operación pendiente con caducidad monotónica."""

    def __init__(
        self,
        timeout_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("El tiempo de espera del contexto debe ser positivo.")
        self._timeout_seconds = timeout_seconds
        self._clock = clock
        self._pending: PendingOperation | None = None
        self.state = ConversationState.WAITING_ORDER

    @property
    def pending(self) -> PendingOperation | None:
        return self._pending

    def set_pending(
        self,
        *,
        intent_id: str,
        entity_type: str | None,
        target_text: str,
        candidates: tuple[IntentCandidate, ...],
        state: str,
    ) -> None:
        if state not in {
            ConversationState.WAITING_TARGET,
            ConversationState.WAITING_SELECTION,
        }:
            raise ValueError(f"Estado pendiente no permitido: {state}")
        self.state = state
        self._pending = PendingOperation(
            intent_id=intent_id,
            entity_type=entity_type,
            target_text=target_text,
            candidates=candidates,
            state=state,
            expires_at=self._clock() + self._timeout_seconds,
        )

    def clear(self) -> None:
        self._pending = None
        self.state = ConversationState.WAITING_ORDER

    def expire_if_needed(self) -> bool:
        if self._pending is None or self._clock() < self._pending.expires_at:
            return False
        self.clear()
        return True


class RapidFuzzIntentResolver:
    """Identifica intenciones y objetivos usando únicamente frases y catálogos."""

    def __init__(
        self,
        catalog: SystemEntityCatalog,
        configuration_path: str | Path = DEFAULT_INTENTS_PATH,
        command_matcher: RapidFuzzCommandMatcher | None = None,
    ) -> None:
        self._catalog = catalog
        self._configuration = _load_intent_configuration(Path(configuration_path))
        self._command_matcher = command_matcher or RapidFuzzCommandMatcher(
            DEFAULT_COMMAND_PHRASES_PATH
        )
        if SYSTEM_OPEN_COMMAND_ID not in self._command_matcher.command_ids:
            raise ValueError(
                f"Falta '{SYSTEM_OPEN_COMMAND_ID}' en config/voice_commands.json."
            )

    @property
    def configuration(self) -> IntentConfiguration:
        return self._configuration

    def is_cancel(self, text: str) -> bool:
        normalized = normalize_command_text(text)
        return normalized in self._configuration.cancel_phrases

    def resolve(
        self,
        text: str,
        *,
        entity_type_override: str | None = None,
        allowed_resources: frozenset[tuple[str, str]] | None = None,
    ) -> IntentResult:
        """Devuelve resultado estructurado; el score no es una probabilidad."""
        normalized = normalize_command_text(text)
        if not normalized:
            return _result(
                status="no_intent",
                state=ConversationState.WAITING_ORDER,
                clarification_reason="transcripcion_vacia",
            )

        prefix_match = self._command_matcher.match_prefix(
            text, allowed_command_ids=frozenset({SYSTEM_OPEN_COMMAND_ID})
        )
        if not prefix_match.candidates:
            if entity_type_override is not None:
                # El diálogo pendiente ya fijó la acción; este turno aporta el objetivo.
                intent_score = 100.0
                matched_prefix = ""
            else:
                return _result(
                    status="no_intent",
                    state=ConversationState.WAITING_ORDER,
                    clarification_reason="comando_no_reconocido",
                )
        else:
            prefix_candidate = prefix_match.candidates[0]
            intent_score = float(
                fuzz.WRatio(normalized, prefix_candidate.matched_phrase)
            )
            matched_prefix = prefix_candidate.matched_phrase
        if entity_type_override is None and normalized in _LEGACY_CAMERA_COMMANDS:
            return _result(
                intent_id="open",
                confidence=intent_score,
                status="legacy_camera",
                state=ConversationState.WAITING_ORDER,
                clarification_reason="orden_de_camara_existente",
            )

        if _UNSAFE_COMMAND_CHARACTERS.search(text) or _COMMAND_OPTION.search(text):
            return _result(
                intent_id="open",
                confidence=intent_score,
                status="rejected",
                state=ConversationState.WAITING_ORDER,
                clarification_reason="ruta_o_argumento_no_admitido",
            )

        entity_type_phrases, stop_words = self._command_matcher.command_target_settings(
            SYSTEM_OPEN_COMMAND_ID
        )
        entity_type = entity_type_override or self._detect_entity_type(
            normalized, entity_type_phrases
        )
        target_text = self._extract_target(normalized, matched_prefix, stop_words)
        parameters: dict[str, object] = {"target_text": target_text}
        if entity_type is not None:
            parameters["entity_type"] = entity_type
        if not target_text:
            return _result(
                intent_id="open",
                confidence=intent_score,
                parameters=parameters,
                entity_type=entity_type,
                status="incomplete",
                state=ConversationState.WAITING_TARGET,
                clarification_reason="falta_objetivo",
            )

        if (
            entity_type is None
            and normalize_command_text(target_text) in _LEGACY_CAMERA_TARGETS
        ):
            return _result(
                intent_id="open",
                confidence=intent_score,
                parameters=parameters,
                status="legacy_camera",
                state=ConversationState.WAITING_ORDER,
                clarification_reason="orden_de_camara_existente",
            )

        candidates = self.resolve_entities(
            target_text,
            entity_type=entity_type,
            allowed_resources=allowed_resources,
        )
        if not candidates:
            return _result(
                intent_id="open",
                confidence=intent_score,
                parameters=parameters,
                entity_type=entity_type,
                status="not_found",
                state=ConversationState.WAITING_ORDER,
                clarification_reason="objetivo_no_encontrado",
            )
        if len(candidates) > 1:
            return _result(
                intent_id="open",
                confidence=intent_score,
                parameters=parameters,
                entity_type=entity_type,
                candidates=candidates,
                status="ambiguous",
                state=ConversationState.WAITING_SELECTION,
                clarification_reason="varias_coincidencias",
            )
        candidate = candidates[0]
        if not candidate.available:
            return _result(
                intent_id="open",
                confidence=intent_score,
                parameters=parameters,
                entity_type=candidate.entity_type,
                entity_id=candidate.entity_id,
                candidates=candidates,
                status="unavailable",
                state=ConversationState.WAITING_ORDER,
                clarification_reason="recurso_no_disponible",
            )
        return _result(
            intent_id="open",
            confidence=intent_score,
            parameters=parameters,
            entity_type=candidate.entity_type,
            entity_id=candidate.entity_id,
            candidates=candidates,
            status="complete",
            state=ConversationState.WAITING_ORDER,
        )

    def resolve_entities(
        self,
        target_text: str,
        *,
        entity_type: str | None = None,
        allowed_resources: frozenset[tuple[str, str]] | None = None,
    ) -> tuple[IntentCandidate, ...]:
        return self._catalog.resolve(
            target_text,
            entity_type=entity_type,
            allowed_resources=allowed_resources,
            similarity_threshold=self._configuration.entity_threshold,
            ambiguity_margin=self._configuration.ambiguity_margin,
            max_candidates=self._configuration.max_candidates,
        )

    def get_resource(self, entity_type: str, entity_id: str) -> SystemResource:
        """Consulta el catálogo validado para validar ejecución y respuesta."""
        return self._catalog.get(entity_type, entity_id)

    def selection_index(self, text: str, candidate_count: int) -> int | None:
        normalized = normalize_command_text(text)
        if normalized.isdigit():
            index = int(normalized) - 1
            return index if 0 <= index < candidate_count else None
        for key, phrases in self._configuration.selection_phrases.items():
            if any(normalized == normalize_command_text(phrase) for phrase in phrases):
                option = int(key) - 1
                return option if 0 <= option < candidate_count else None
        return None

    def _detect_entity_type(
        self, normalized: str, entity_type_phrases: dict[str, tuple[str, ...]]
    ) -> str | None:
        matches = {
            entity_type
            for entity_type, phrases in entity_type_phrases.items()
            if any(_contains_phrase(normalized, phrase) for phrase in phrases)
        }
        return next(iter(matches)) if len(matches) == 1 else None

    def _extract_target(
        self,
        normalized: str,
        matched_prefix: str,
        configured_stop_words: frozenset[str],
    ) -> str:
        prefix_word_count = len(matched_prefix.split())
        words = [
            word
            for word in normalized.split()[prefix_word_count:]
            if word not in configured_stop_words
        ]
        return " ".join(words)


class SystemCommandHandler:
    """Coordina interpretación, contexto, diálogo y ejecución por puerto."""

    def __init__(
        self,
        resolver: RapidFuzzIntentResolver,
        executor: SystemActionExecutor,
        speech_output: CommandSpeechOutput,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._resolver = resolver
        self._executor = executor
        self._speech_output = speech_output
        self.context = ConversationContext(
            resolver.configuration.context_timeout_seconds,
            clock=clock,
        )

    def handle(self, transcript: str) -> bool:
        """Procesa solo órdenes del sistema; devuelve false para otras funciones."""
        expired = self.context.expire_if_needed()
        if self._resolver.is_cancel(transcript):
            if self.context.pending is None:
                self._speech_output.speak("No hay una operación pendiente para cancelar.")
            else:
                self.context.clear()
                self._speech_output.speak("De acuerdo, cancelé la operación.")
            return True

        result = self._resolver.resolve(transcript)
        if self.context.pending is not None:
            pending = self.context.pending
            pending_keys = {
                (candidate.entity_type, candidate.entity_id)
                for candidate in pending.candidates
            }
            if (
                result.status == "complete"
                and result.entity_type is not None
                and result.entity_id is not None
                and pending.state == ConversationState.WAITING_SELECTION
                and (result.entity_type, result.entity_id) not in pending_keys
            ) or (
                result.status not in {"no_intent", "legacy_camera"}
                and result.entity_type is not None
                and pending.entity_type is not None
                and result.entity_type != pending.entity_type
            ):
                self.context.clear()
            else:
                return self._continue_pending(transcript, result)
        elif expired and result.status == "no_intent":
            self._speech_output.speak(
                "La solicitud pendiente venció. Dime de nuevo qué quieres abrir."
            )
            return True

        if result.status == "no_intent":
            return False
        if result.status == "legacy_camera":
            return False
        return self._handle_result(result)

    def _handle_result(self, result: IntentResult) -> bool:
        if result.intent_id and result.intent_id != "open":
            self._speech_output.speak(
                "Esa acción todavía no está disponible. Por ahora puedo abrir "
                "carpetas y aplicaciones."
            )
            return True
        if result.status == "incomplete":
            self.context.set_pending(
                intent_id=result.intent_id,
                entity_type=result.entity_type,
                target_text=str(result.parameters.get("target_text", "")),
                candidates=(),
                state=ConversationState.WAITING_TARGET,
            )
            self._speak_target_question(result.entity_type)
            return True
        if result.status == "not_found":
            self._speech_output.speak(
                "No encontré una carpeta o aplicación disponible con ese nombre. "
                "Puedes repetirlo o decir «cancelar»."
            )
            return True
        if result.status == "rejected":
            self._speech_output.speak(
                "No acepto rutas ni argumentos de terminal. Di solo el nombre "
                "de una carpeta o aplicación autorizada."
            )
            return True
        if result.status == "unavailable":
            candidate = result.candidates[0]
            self._speech_output.speak(
                f"La carpeta {candidate.label} no existe o no está disponible."
            )
            return True
        if result.status == "ambiguous":
            self.context.set_pending(
                intent_id=result.intent_id,
                entity_type=result.entity_type,
                target_text=str(result.parameters.get("target_text", "")),
                candidates=result.candidates,
                state=ConversationState.WAITING_SELECTION,
            )
            self._speak_candidates(result.candidates)
            return True
        if result.status == "complete" and result.entity_type and result.entity_id:
            self._execute(result.intent_id, result.entity_type, result.entity_id)
            return True
        raise RuntimeError(f"Estado de interpretación no manejado: {result.status}")

    def _continue_pending(self, transcript: str, result: IntentResult) -> bool:
        pending = self.context.pending
        if pending is None:
            raise RuntimeError("Se perdió el contexto de la operación pendiente.")
        if pending.state == ConversationState.WAITING_SELECTION:
            selection = self._resolver.selection_index(
                transcript, len(pending.candidates)
            )
            if selection is not None:
                candidate = pending.candidates[selection]
                self._execute(
                    pending.intent_id,
                    candidate.entity_type,
                    candidate.entity_id,
                )
                return True
            allowed_resources = frozenset(
                (candidate.entity_type, candidate.entity_id)
                for candidate in pending.candidates
            )
            candidates = self._resolver.resolve_entities(
                str(result.parameters.get("target_text", transcript)),
                entity_type=pending.entity_type,
                allowed_resources=allowed_resources,
            )
            if len(candidates) == 1 and candidates[0].available:
                candidate = candidates[0]
                self._execute("open", candidate.entity_type, candidate.entity_id)
                return True
            if candidates:
                self.context.set_pending(
                    intent_id=pending.intent_id,
                    entity_type=pending.entity_type,
                    target_text=pending.target_text,
                    candidates=candidates,
                    state=ConversationState.WAITING_SELECTION,
                )
                self._speak_candidates(candidates)
            else:
                self._speak_selection_reprompt(pending.candidates)
            return True

        candidates = self._resolver.resolve_entities(
            str(result.parameters.get("target_text", transcript)),
            entity_type=pending.entity_type,
        )
        if len(candidates) == 1 and candidates[0].available:
            candidate = candidates[0]
            self._execute(pending.intent_id, candidate.entity_type, candidate.entity_id)
            return True
        if len(candidates) == 1:
            self.context.clear()
            self._speak_unavailable(candidates[0])
            return True
        if len(candidates) > 1:
            self.context.set_pending(
                intent_id=pending.intent_id,
                entity_type=pending.entity_type,
                target_text=pending.target_text,
                candidates=candidates,
                state=ConversationState.WAITING_SELECTION,
            )
            self._speak_candidates(candidates)
            return True
        if candidates and not candidates[0].available:
            self.context.clear()
            self._speak_unavailable(candidates[0])
            return True
        self._speak_target_question(pending.entity_type, repeat=True)
        return True

    def _execute(self, intent_id: str, entity_type: str, entity_id: str) -> None:
        resource = self._resolver.get_resource(entity_type, entity_id)
        self.context.state = ConversationState.EXECUTING
        try:
            if intent_id != "open":
                raise RuntimeError(f"No hay ejecutor para la intención '{intent_id}'.")
            if entity_type == "folder":
                self._executor.open_folder(entity_id)
            elif entity_type == "application":
                self._executor.launch_application(entity_id)
            else:
                raise RuntimeError(f"Tipo de recurso no ejecutable: {entity_type}")
        except OSError:
            LOGGER.exception("No se pudo abrir el recurso local %s.", entity_id)
            self._speech_output.speak(
                f"No pude abrir {resource.name}. Comprueba que siga disponible."
            )
        else:
            self._speech_output.speak(f"Abriendo {resource.name}.")
        finally:
            self.context.clear()

    def _speak_target_question(
        self, entity_type: str | None, *, repeat: bool = False
    ) -> None:
        prefix = "No entendí el nombre. " if repeat else ""
        if entity_type == "folder":
            question = "¿Qué carpeta quieres abrir?"
        elif entity_type == "application":
            question = "¿Qué aplicación quieres abrir?"
        else:
            question = "¿Qué quieres abrir: una carpeta o una aplicación?"
        self._speech_output.speak(prefix + question)

    def _speak_candidates(self, candidates: tuple[IntentCandidate, ...]) -> None:
        resource_types = {candidate.entity_type for candidate in candidates}
        if len(resource_types) > 1:
            resource_kind = "recursos"
        elif "application" in resource_types:
            resource_kind = "aplicaciones"
        else:
            resource_kind = "carpetas"
        ordinal = ("primera", "segunda", "tercera")
        options = " ".join(
            f"Opción {ordinal[index]}: "
            f"{'carpeta' if candidate.entity_type == 'folder' else 'aplicación'} "
            f"{candidate.label}."
            for index, candidate in enumerate(candidates)
        )
        self._speech_output.speak(
            f"He encontrado varias {resource_kind}. "
            f"Di el número o el nombre. {options}"
        )

    def _speak_selection_reprompt(
        self, candidates: tuple[IntentCandidate, ...]
    ) -> None:
        names = ", ".join(candidate.label for candidate in candidates)
        self._speech_output.speak(
            f"No reconocí la opción. Di el número o el nombre: {names}."
        )

    def _speak_unavailable(self, candidate: IntentCandidate) -> None:
        resource_type = "carpeta" if candidate.entity_type == "folder" else "aplicación"
        self._speech_output.speak(
            f"La {resource_type} {candidate.label} no existe o no está disponible."
        )


def _load_intent_configuration(path: Path) -> IntentConfiguration:
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as error:
        raise ValueError(f"JSON inválido en el catálogo de intenciones: {path}") from error

    expected_keys = {
        "version",
        "entity_similarity_threshold",
        "ambiguity_margin",
        "max_candidates",
        "context_timeout_seconds",
        "cancel_phrases",
        "selection_phrases",
    }
    if not isinstance(data, dict) or set(data) != expected_keys or data["version"] != 1:
        raise ValueError(f"Formato inválido en el catálogo de intenciones: {path}")
    entity_threshold = _validated_int(data, "entity_similarity_threshold", 0, 100, path)
    ambiguity_margin = _validated_int(data, "ambiguity_margin", 0, 100, path)
    max_candidates = _validated_int(data, "max_candidates", 1, 3, path)
    timeout = data["context_timeout_seconds"]
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or timeout <= 0
    ):
        raise ValueError("'context_timeout_seconds' debe ser positivo.")
    cancel_phrases = _validated_phrases(data, "cancel_phrases", path)
    selection_data = data["selection_phrases"]
    if not isinstance(selection_data, dict) or set(selection_data) != {
        "1",
        "2",
        "3",
    }:
        raise ValueError("'selection_phrases' debe ser un objeto no vacío.")
    selection_phrases: dict[str, tuple[str, ...]] = {}
    for key, phrases in selection_data.items():
        if key not in {"1", "2", "3"} or not isinstance(phrases, list):
            raise ValueError("Las opciones de selección permitidas son 1, 2 y 3.")
        if any(not isinstance(phrase, str) or not phrase.strip() for phrase in phrases):
            raise ValueError("Las frases de selección deben ser textos no vacíos.")
        selection_phrases[key] = tuple(phrase.strip() for phrase in phrases)

    return IntentConfiguration(
        entity_threshold=entity_threshold,
        ambiguity_margin=ambiguity_margin,
        max_candidates=max_candidates,
        context_timeout_seconds=float(timeout),
        cancel_phrases=frozenset(
            normalize_command_text(phrase) for phrase in cancel_phrases
        ),
        selection_phrases=selection_phrases,
    )


def _validated_int(
    data: dict[str, object], key: str, minimum: int, maximum: int, path: Path
) -> int:
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"'{key}' debe ser un entero entre {minimum} y {maximum}: {path}")
    return value


def _validated_phrases(
    data: dict[str, object], key: str, path: Path
) -> tuple[str, ...]:
    phrases = data[key]
    if (
        not isinstance(phrases, list)
        or not phrases
        or any(not isinstance(phrase, str) or not phrase.strip() for phrase in phrases)
    ):
        raise ValueError(f"'{key}' debe ser una lista no vacía de textos: {path}")
    return tuple(phrase.strip() for phrase in phrases)


def _contains_phrase(text: str, phrase: str) -> bool:
    return f" {normalize_command_text(phrase)} " in f" {text} "


def _result(
    *,
    intent_id: str = "",
    confidence: float = 0,
    parameters: dict[str, object] | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    candidates: tuple[IntentCandidate, ...] = (),
    status: str,
    state: str,
    clarification_reason: str | None = None,
) -> IntentResult:
    return IntentResult(
        intent_id=intent_id,
        parameters=parameters or {},
        confidence=confidence,
        entity_type=entity_type,
        entity_id=entity_id,
        candidates=candidates,
        status=status,
        state=state,
        clarification_reason=clarification_reason,
    )
