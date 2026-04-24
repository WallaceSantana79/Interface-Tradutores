from __future__ import annotations

import shutil
import subprocess
import re
from dataclasses import dataclass
from pathlib import Path

from .models import JobResult


BUZZ_FLATPAK_APP_ID = "io.github.chidiwilliams.Buzz"

BUZZ_MODEL_TYPES = (
    "whisper",
    "whispercpp",
    "fasterwhisper",
    "huggingface",
    "openaiapi",
)
BUZZ_MODEL_SIZES = (
    "tiny",
    "tiny.en",
    "base",
    "base.en",
    "small",
    "small.en",
    "medium",
    "medium.en",
    "large",
    "large-v2",
    "large-v3",
    "large-v3-turbo",
    "custom",
    "lumii",
)
BUZZ_TASKS = ("transcribe", "translate")
BUZZ_OUTPUT_FORMATS = ("srt", "vtt", "txt")
BUZZ_LANGUAGE_MENU_OPTIONS = (
    "Detectar idioma (auto)",
    "Português (pt)",
    "English (en)",
    "Español (es)",
    "Français (fr)",
    "Deutsch (de)",
    "Italiano (it)",
    "Русский (ru)",
    "日本語 (ja)",
    "한국어 (ko)",
    "中文 (zh)",
)

_LANGUAGE_ALIAS_TO_CODE = {
    "english": "en",
    "en": "en",
    "portuguese": "pt",
    "portugues": "pt",
    "português": "pt",
    "pt": "pt",
    "spanish": "es",
    "espanol": "es",
    "español": "es",
    "es": "es",
    "french": "fr",
    "francais": "fr",
    "français": "fr",
    "fr": "fr",
    "german": "de",
    "deutsch": "de",
    "de": "de",
    "italian": "it",
    "italiano": "it",
    "it": "it",
    "russian": "ru",
    "russo": "ru",
    "ru": "ru",
    "japanese": "ja",
    "japones": "ja",
    "japonês": "ja",
    "ja": "ja",
    "korean": "ko",
    "coreano": "ko",
    "ko": "ko",
    "chinese": "zh",
    "chines": "zh",
    "chinês": "zh",
    "zh": "zh",
}

_COMMON_MEDIA_SUFFIXES = {
    ".aac",
    ".ac3",
    ".aiff",
    ".amr",
    ".avi",
    ".flac",
    ".flv",
    ".m4a",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
    ".wma",
}


@dataclass(frozen=True)
class BuzzDetectionResult:
    available: bool
    message: str
    command_prefix: tuple[str, ...]


@dataclass(frozen=True)
class BuzzRunConfig:
    input_path: Path
    model_type: str = "fasterwhisper"
    model_size: str = "large-v3-turbo"
    task: str = "transcribe"
    language: str = ""
    word_timestamps: bool = False
    extract_speech: bool = False
    output_formats: tuple[str, ...] = ("srt",)
    output_directory: Path | None = None
    hide_gui: bool = True


def detectar_buzz() -> BuzzDetectionResult:
    flatpak_bin = shutil.which("flatpak")
    if not flatpak_bin:
        return BuzzDetectionResult(
            available=False,
            message="Flatpak não encontrado no sistema.",
            command_prefix=(),
        )

    try:
        result = subprocess.run(
            [flatpak_bin, "info", BUZZ_FLATPAK_APP_ID],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return BuzzDetectionResult(
            available=False,
            message=f"Falha ao consultar Flatpak/Buzz: {exc}",
            command_prefix=(),
        )

    if result.returncode != 0:
        return BuzzDetectionResult(
            available=False,
            message=(
                "Buzz não está instalado no Flatpak. "
                f"Instale com: flatpak install flathub {BUZZ_FLATPAK_APP_ID}"
            ),
            command_prefix=(),
        )

    return BuzzDetectionResult(
        available=True,
        message="Buzz detectado via Flatpak.",
        command_prefix=(flatpak_bin, "run", "--command=buzz", BUZZ_FLATPAK_APP_ID),
    )


def _validate_config(config: BuzzRunConfig) -> tuple[Path, Path]:
    input_path = Path(config.input_path)
    if not input_path.exists() or not input_path.is_file():
        raise ValueError(f"Arquivo de mídia inválido: {input_path}")
    if input_path.suffix.lower() not in _COMMON_MEDIA_SUFFIXES:
        raise ValueError(
            "Formato de mídia não suportado pela validação local. "
            "Use um arquivo de áudio/vídeo comum (mp4, mkv, mp3, wav, etc.)."
        )

    if config.model_type not in BUZZ_MODEL_TYPES:
        raise ValueError(f"Tipo de modelo inválido: {config.model_type}")
    if config.model_size not in BUZZ_MODEL_SIZES:
        raise ValueError(f"Tamanho de modelo inválido: {config.model_size}")
    if config.task not in BUZZ_TASKS:
        raise ValueError(f"Tarefa inválida: {config.task}")

    normalized_formats = tuple(dict.fromkeys(config.output_formats))
    if not normalized_formats:
        raise ValueError("Selecione pelo menos um formato de saída (srt/vtt/txt).")
    for output_format in normalized_formats:
        if output_format not in BUZZ_OUTPUT_FORMATS:
            raise ValueError(f"Formato de saída inválido: {output_format}")

    output_dir = Path(config.output_directory) if config.output_directory else input_path.parent
    if not output_dir.exists() or not output_dir.is_dir():
        raise ValueError(f"Pasta de saída inválida: {output_dir}")

    return (input_path, output_dir)


def normalize_buzz_language(raw_value: str) -> str:
    raw = (raw_value or "").strip()
    if not raw:
        return ""

    lowered = raw.casefold()
    if lowered in {"auto", "detect", "detectar", "detectar idioma", "detectar idioma (auto)"}:
        return ""

    code_match = re.search(r"\(([a-z]{2})\)\s*$", lowered)
    if code_match:
        return code_match.group(1)

    prefix_match = re.match(r"^([a-z]{2})\b", lowered)
    if prefix_match:
        return prefix_match.group(1)

    alias = _LANGUAGE_ALIAS_TO_CODE.get(lowered)
    if alias:
        return alias

    if re.fullmatch(r"[a-z]{2}", lowered):
        return lowered

    raise ValueError(
        "Idioma inválido. Use um código de 2 letras (ex.: en, pt, es) "
        "ou selecione uma opção do menu."
    )


def montar_comando_buzz(config: BuzzRunConfig) -> list[str]:
    detection = detectar_buzz()
    if not detection.available:
        raise ValueError(detection.message)

    input_path, output_dir = _validate_config(config)

    command = [
        *detection.command_prefix,
        "add",
        str(input_path),
        "--model-type",
        config.model_type,
        "--model-size",
        config.model_size,
        "--task",
        config.task,
        "--output-directory",
        str(output_dir),
    ]

    language = normalize_buzz_language(config.language)
    if language:
        command.extend(["--language", language])
    if config.word_timestamps:
        command.append("--word-timestamps")
    if config.extract_speech:
        command.append("--extract-speech")
    for output_format in dict.fromkeys(config.output_formats):
        command.append(f"--{output_format}")
    if config.hide_gui:
        command.append("--hide-gui")
    return command


def expected_output_paths(config: BuzzRunConfig) -> list[Path]:
    input_path, output_dir = _validate_config(config)
    output_paths: list[Path] = []
    for output_format in dict.fromkeys(config.output_formats):
        output_paths.append(output_dir / f"{input_path.stem}.{output_format}")
    return output_paths


def iniciar_execucao_buzz(config: BuzzRunConfig) -> subprocess.Popen[str]:
    command = montar_comando_buzz(config)
    return subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def executar_buzz(config: BuzzRunConfig) -> JobResult:
    try:
        command = montar_comando_buzz(config)
    except ValueError as exc:
        return JobResult(False, str(exc))

    process = subprocess.run(command, check=False, capture_output=True, text=True)
    stdout = (process.stdout or "").strip()
    stderr = (process.stderr or "").strip()

    if process.returncode != 0:
        details = stderr or stdout or "Falha desconhecida ao executar Buzz."
        return JobResult(False, f"Falha ao gerar legenda com Buzz: {details}")

    generated = [str(path) for path in expected_output_paths(config) if path.exists()]
    warnings: list[str] = []
    if not generated:
        warnings.append(
            "Buzz executou sem erro, mas nenhum arquivo de saída esperado foi localizado."
        )

    message = "Legendas geradas com Buzz."
    if stdout:
        message += " Verifique o resumo no terminal/log do Buzz."
    return JobResult(True, message, warnings=warnings, generated_files=generated)


def finalizar_execucao_buzz(
    *,
    config: BuzzRunConfig,
    returncode: int,
    stdout: str,
    stderr: str,
) -> JobResult:
    if returncode != 0:
        details = (stderr or stdout or "Falha desconhecida ao executar Buzz.").strip()
        return JobResult(False, f"Falha ao gerar legenda com Buzz: {details}")

    generated = [str(path) for path in expected_output_paths(config) if path.exists()]
    warnings: list[str] = []
    if not generated:
        warnings.append(
            "Buzz concluiu com sucesso, mas os arquivos esperados não foram encontrados na pasta de saída."
        )
    return JobResult(
        True,
        "Legendas geradas com Buzz.",
        warnings=warnings,
        generated_files=generated,
    )
