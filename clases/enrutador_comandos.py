"""Carga y comparación aproximada de las órdenes de voz configuradas."""

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz, process

from clases.contratos import CommandCandidate, CommandMatch


DEFAULT_COMMAND_PHRASES_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "voice_commands.json"
)
COMMAND_SIMILARITY_THRESHOLD = 80
COMMAND_AMBIGUITY_MARGIN = 5


@dataclass(frozen=True, slots=True)
class _CommandDefinition:
    description: str
    phrases: tuple[str, ...]
    entity_type_phrases: dict[str, tuple[str, ...]]
    target_stop_words: tuple[str, ...]


class RapidFuzzCommandMatcher:
    """Compara una transcripción con frases editables y devuelve candidatas."""

    def __init__(
        self,
        config_path: str | Path = DEFAULT_COMMAND_PHRASES_PATH,
        similarity_threshold: int = COMMAND_SIMILARITY_THRESHOLD,
        ambiguity_margin: int = COMMAND_AMBIGUITY_MARGIN,
    ) -> None:
        if not 0 <= similarity_threshold <= 100:
            raise ValueError("El umbral de similitud debe estar entre 0 y 100.")
        if ambiguity_margin < 0:
            raise ValueError("El margen de ambigüedad no puede ser negativo.")

        self._similarity_threshold = similarity_threshold
        self._ambiguity_margin = ambiguity_margin
        self._commands = _load_commands(config_path)
        self._phrase_to_command: dict[str, str] = {}
        self._descriptions: dict[str, str] = {}
        for command_id, definition in self._commands.items():
            self._descriptions[command_id] = definition.description
            for phrase in definition.phrases:
                existing_command = self._phrase_to_command.get(phrase)
                if existing_command is not None and existing_command != command_id:
                    raise ValueError(
                        f"La frase '{phrase}' está asignada a más de una orden."
                    )
                self._phrase_to_command[phrase] = command_id

    @property
    def command_ids(self) -> frozenset[str]:
        """Identificadores disponibles para registrar sus acciones."""
        return frozenset(self._commands)

    @property
    def command_descriptions(self) -> dict[str, str]:
        """Descripciones legibles para presentar órdenes al usuario."""
        return self._descriptions.copy()

    @property
    def parameterized_command_ids(self) -> frozenset[str]:
        """Órdenes cuyo objetivo se interpreta después de reconocer el prefijo."""
        return frozenset(
            command_id
            for command_id, definition in self._commands.items()
            if definition.entity_type_phrases
        )

    def command_target_settings(
        self, command_id: str
    ) -> tuple[dict[str, tuple[str, ...]], frozenset[str]]:
        """Devuelve pistas de entidad y palabras de objetivo del JSON del comando."""
        try:
            definition = self._commands[command_id]
        except KeyError as error:
            raise KeyError(f"No existe el comando configurado '{command_id}'.") from error
        entity_type_phrases = definition.entity_type_phrases
        stop_words = set(definition.target_stop_words)
        for phrases in entity_type_phrases.values():
            for phrase in phrases:
                stop_words.update(phrase.split())
        return entity_type_phrases, frozenset(stop_words)

    def match(
        self,
        transcript: str,
        allowed_command_ids: frozenset[str] | None = None,
    ) -> CommandMatch:
        """Devuelve una o más órdenes cuya similitud alcanza el umbral."""
        normalized_transcript = normalize_command_text(transcript)
        if not normalized_transcript:
            return CommandMatch(())

        phrases = [
            phrase
            for phrase, command_id in self._phrase_to_command.items()
            if allowed_command_ids is None or command_id in allowed_command_ids
        ]
        if not phrases:
            return CommandMatch(())

        best_by_command: dict[str, CommandCandidate] = {}
        for phrase, similarity, _ in process.extract(
            normalized_transcript,
            phrases,
            scorer=fuzz.WRatio,
            score_cutoff=self._similarity_threshold,
            limit=None,
        ):
            command_id = self._phrase_to_command[phrase]
            previous = best_by_command.get(command_id)
            if previous is None or similarity > previous.similarity:
                best_by_command[command_id] = CommandCandidate(
                    command_id=command_id,
                    description=self._descriptions[command_id],
                    matched_phrase=phrase,
                    similarity=similarity,
                )

        if not best_by_command:
            return CommandMatch(())

        ranked_candidates = sorted(
            best_by_command.values(),
            key=lambda candidate: candidate.similarity,
            reverse=True,
        )
        top_similarity = ranked_candidates[0].similarity
        close_candidates = tuple(
            candidate
            for candidate in ranked_candidates
            if top_similarity - candidate.similarity <= self._ambiguity_margin
        )
        return CommandMatch(close_candidates)

    def match_prefix(
        self,
        transcript: str,
        allowed_command_ids: frozenset[str] | None = None,
    ) -> CommandMatch:
        """Reconoce frases de acción al inicio aunque el objetivo venga después."""
        normalized_words = normalize_command_text(transcript).split()
        if not normalized_words:
            return CommandMatch(())

        best_by_command: dict[str, CommandCandidate] = {}
        for command_id, definition in self._commands.items():
            if (
                allowed_command_ids is not None
                and command_id not in allowed_command_ids
            ):
                continue
            for phrase in definition.phrases:
                phrase_words = phrase.split()
                minimum_words = max(1, len(phrase_words) - 1)
                maximum_words = min(len(normalized_words), len(phrase_words) + 1)
                for word_count in range(minimum_words, maximum_words + 1):
                    prefix = " ".join(normalized_words[:word_count])
                    similarity = fuzz.WRatio(phrase, prefix)
                    if similarity < self._similarity_threshold:
                        continue
                    candidate = CommandCandidate(
                        command_id=command_id,
                        description=definition.description,
                        matched_phrase=prefix,
                        similarity=similarity,
                    )
                    previous = best_by_command.get(command_id)
                    if previous is None or (
                        candidate.similarity,
                        len(candidate.matched_phrase.split()),
                    ) > (
                        previous.similarity,
                        len(previous.matched_phrase.split()),
                    ):
                        best_by_command[command_id] = candidate

        if not best_by_command:
            return CommandMatch(())
        ranked_candidates = sorted(
            best_by_command.values(),
            key=lambda candidate: (
                -candidate.similarity,
                candidate.command_id,
            ),
        )
        top_similarity = ranked_candidates[0].similarity
        return CommandMatch(
            tuple(
                candidate
                for candidate in ranked_candidates
                if top_similarity - candidate.similarity <= self._ambiguity_margin
            )
        )


def normalize_command_text(text: str) -> str:
    """Normaliza mayúsculas, acentos y puntuación antes de la comparación."""
    decomposed_text = unicodedata.normalize("NFD", text.casefold())
    without_diacritics = "".join(
        character
        for character in decomposed_text
        if unicodedata.category(character) != "Mn"
    )
    normalized_text = "".join(
        character if character.isalnum() else " "
        for character in without_diacritics
    )
    return " ".join(normalized_text.split())


def _load_commands(path: str | Path) -> dict[str, _CommandDefinition]:
    """Carga y valida definiciones de órdenes independientes de sus acciones."""
    config_path = Path(path)
    try:
        with config_path.open(encoding="utf-8") as config_file:
            configuration = json.load(config_file)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"El archivo de órdenes de voz no contiene JSON válido: {config_path}"
        ) from error

    if not isinstance(configuration, dict) or not configuration:
        raise ValueError(f"Debe haber al menos una orden configurada: {config_path}")

    commands: dict[str, _CommandDefinition] = {}
    for command_id, definition in configuration.items():
        if not isinstance(command_id, str) or not command_id.strip():
            raise ValueError(f"Hay un identificador de orden inválido: {config_path}")
        if not isinstance(definition, dict) or not {"description", "phrases"} <= set(
            definition
        ) or not set(definition) <= {
            "description",
            "phrases",
            "entity_type_phrases",
            "target_stop_words",
        }:
            raise ValueError(
                f"'{command_id}' debe contener 'description' y 'phrases': {config_path}"
            )
        description = definition["description"]
        phrases = definition["phrases"]
        if not isinstance(description, str) or not description.strip():
            raise ValueError(
                f"La descripción de '{command_id}' debe ser texto no vacío."
            )
        if (
            not isinstance(phrases, list)
            or not phrases
            or any(not isinstance(phrase, str) or not phrase.strip() for phrase in phrases)
        ):
            raise ValueError(
                f"Las frases de '{command_id}' deben ser una lista no vacía de textos."
            )
        normalized_phrases = tuple(
            normalize_command_text(phrase) for phrase in phrases
        )
        if any(not phrase for phrase in normalized_phrases):
            raise ValueError(
                f"Las frases de '{command_id}' deben contener caracteres válidos."
            )
        entity_type_phrases = definition.get("entity_type_phrases", {})
        if (
            not isinstance(entity_type_phrases, dict)
            or any(
                entity_type not in {"folder", "application"}
                or not isinstance(type_phrases, list)
                or any(
                    not isinstance(type_phrase, str) or not type_phrase.strip()
                    for type_phrase in type_phrases
                )
                for entity_type, type_phrases in entity_type_phrases.items()
            )
        ):
            raise ValueError(f"'entity_type_phrases' inválido para '{command_id}'.")
        target_stop_words = definition.get("target_stop_words", [])
        if (
            not isinstance(target_stop_words, list)
            or any(
                not isinstance(word, str)
                or not word.strip()
                or len(normalize_command_text(word).split()) != 1
                for word in target_stop_words
            )
        ):
            raise ValueError(f"'target_stop_words' inválido para '{command_id}'.")
        commands[command_id] = _CommandDefinition(
            description=description.strip(),
            phrases=normalized_phrases,
            entity_type_phrases={
                entity_type: tuple(
                    normalize_command_text(type_phrase)
                    for type_phrase in type_phrases
                )
                for entity_type, type_phrases in entity_type_phrases.items()
            },
            target_stop_words=tuple(
                normalize_command_text(word) for word in target_stop_words
            ),
        )
    return commands
