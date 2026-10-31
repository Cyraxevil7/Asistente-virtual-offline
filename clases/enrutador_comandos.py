"""Carga y comparación aproximada de las órdenes de voz configuradas."""

import json
import unicodedata
from pathlib import Path

from rapidfuzz import fuzz, process

from clases.contratos import CommandCandidate, CommandMatch


DEFAULT_COMMAND_PHRASES_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "voice_commands.json"
)
COMMAND_SIMILARITY_THRESHOLD = 80
COMMAND_AMBIGUITY_MARGIN = 5


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
        for command_id, (description, phrases) in self._commands.items():
            self._descriptions[command_id] = description
            for phrase in phrases:
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


def _load_commands(path: str | Path) -> dict[str, tuple[str, tuple[str, ...]]]:
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

    commands: dict[str, tuple[str, tuple[str, ...]]] = {}
    for command_id, definition in configuration.items():
        if not isinstance(command_id, str) or not command_id.strip():
            raise ValueError(f"Hay un identificador de orden inválido: {config_path}")
        if not isinstance(definition, dict) or set(definition) != {
            "description",
            "phrases",
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
        commands[command_id] = (description.strip(), normalized_phrases)
    return commands
