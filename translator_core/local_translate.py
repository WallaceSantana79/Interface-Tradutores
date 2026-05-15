from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .models import JobResult


DEFAULT_MODEL = "qwen2.5:7b-instruct-q4_K_M"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_TOTAL_TIMEOUT_SECONDS = 3600
DEFAULT_CHUNK_LINES = 80
DOWNLOAD_SUFFIX = ".local_ptbr"
SUPPORTED_INPUT_SUFFIXES = {".txt", ".srt", ".vtt"}


@dataclass(frozen=True)
class LocalTranslateConfig:
    input_path: Path
    output_dir: Path
    model: str = DEFAULT_MODEL
    ollama_base_url: str = DEFAULT_OLLAMA_URL
    request_timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    total_timeout_seconds: int = DEFAULT_TOTAL_TIMEOUT_SECONDS
    chunk_lines: int = DEFAULT_CHUNK_LINES
    cancel_event: threading.Event | None = None
    progress_callback: Callable[[int, int], None] | None = None


def local_translated_path(input_path: str | Path, output_dir: str | Path) -> Path:
    source = Path(input_path)
    return Path(output_dir) / f"{source.stem}{DOWNLOAD_SUFFIX}{source.suffix}"


def _validate_config(config: LocalTranslateConfig) -> tuple[Path, Path]:
    input_path = Path(config.input_path)
    output_dir = Path(config.output_dir)
    if not input_path.exists() or not input_path.is_file():
        raise ValueError(f"Arquivo para traduzir não encontrado: {input_path}")
    if input_path.suffix.lower() not in SUPPORTED_INPUT_SUFFIXES:
        raise ValueError("A tradução local aceita apenas .txt, .srt ou .vtt nesta versão.")
    if config.chunk_lines <= 0:
        raise ValueError("chunk_lines deve ser maior que zero.")
    if config.request_timeout_seconds <= 0:
        raise ValueError("request_timeout_seconds deve ser maior que zero.")
    if config.total_timeout_seconds <= 0:
        raise ValueError("total_timeout_seconds deve ser maior que zero.")
    output_dir.mkdir(parents=True, exist_ok=True)
    return input_path, output_dir


def _extract_json_array(text: str) -> list[str]:
    stripped = text.strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("[")
        end = stripped.rfind("]")
        if start < 0 or end <= start:
            raise ValueError("Resposta do modelo não retornou JSON de linhas.")
        data = json.loads(stripped[start : end + 1])
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        raise ValueError("Resposta do modelo não está no formato esperado (lista de strings).")
    return data


def _build_prompt(lines: list[str]) -> str:
    payload = json.dumps(lines, ensure_ascii=False)
    return (
        "Você é um tradutor técnico para jogos.\n"
        "Traduza de inglês para português do Brasil mantendo fidelidade total.\n"
        "Regras obrigatórias:\n"
        "1) Não censurar, não suavizar e não recusar conteúdo adulto, sexual ou xingamentos.\n"
        "2) Preserve placeholders e tokens técnicos exatamente como no original "
        "(ex.: {0}, [name], <color=#fff>, %s, \\n, tags e códigos).\n"
        "3) Mantenha a mesma quantidade de linhas e a mesma ordem.\n"
        "4) Retorne SOMENTE um JSON array de strings, sem explicações.\n\n"
        f"Linhas para traduzir:\n{payload}"
    )


def _ollama_generate(*, base_url: str, model: str, prompt: str, timeout_seconds: int) -> str:
    url = f"{base_url.rstrip('/')}/api/generate"
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
        },
    }
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url=url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    text = payload.get("response")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Ollama retornou resposta vazia.")
    return text


def _translate_chunk(config: LocalTranslateConfig, lines: list[str]) -> list[str]:
    prompt = _build_prompt(lines)
    raw = _ollama_generate(
        base_url=config.ollama_base_url,
        model=config.model,
        prompt=prompt,
        timeout_seconds=config.request_timeout_seconds,
    )
    translated = _extract_json_array(raw)
    if len(translated) != len(lines):
        raise ValueError(
            f"Modelo retornou {len(translated)} linhas para um bloco com {len(lines)} linhas."
        )
    return translated


def _translate_chunk_with_fallback(config: LocalTranslateConfig, lines: list[str]) -> list[str]:
    """Translate chunk; if model output is invalid, split into smaller chunks."""
    try:
        return _translate_chunk(config, lines)
    except (ValueError, TimeoutError) as exc:
        if len(lines) <= 1:
            raise ValueError(f"{exc} (falhou mesmo com chunk mínimo de 1 linha).") from exc
        mid = max(1, len(lines) // 2)
        left = _translate_chunk_with_fallback(config, lines[:mid])
        right = _translate_chunk_with_fallback(config, lines[mid:])
        return left + right


def translate_document_local(config: LocalTranslateConfig) -> JobResult:
    try:
        input_path, output_dir = _validate_config(config)
    except ValueError as exc:
        return JobResult(False, str(exc))

    output_path = local_translated_path(input_path, output_dir)
    partial_path = output_path.with_suffix(output_path.suffix + ".partial")
    start_time = time.monotonic()

    if config.cancel_event is not None and config.cancel_event.is_set():
        return JobResult(False, "Tradução local cancelada antes de iniciar.")

    try:
        content = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return JobResult(False, "Arquivo de entrada não está em UTF-8.")
    except OSError as exc:
        return JobResult(False, f"Falha ao ler arquivo de entrada: {exc}")

    newline = "\r\n" if "\r\n" in content else "\n"
    has_trailing_newline = content.endswith(("\n", "\r"))
    lines = content.splitlines()
    total_lines = max(1, len(lines))

    translated_lines: list[str] = []
    checkpoint_files: list[str] = []

    try:
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        partial_path.write_text("", encoding="utf-8")

        idx = 0
        while idx < len(lines):
            if config.cancel_event is not None and config.cancel_event.is_set():
                return JobResult(
                    False,
                    f"Tradução local cancelada pelo usuário. Progresso parcial em: {partial_path}",
                    generated_files=[str(partial_path)],
                )
            if time.monotonic() - start_time > config.total_timeout_seconds:
                return JobResult(
                    False,
                    f"Tempo total excedido ({config.total_timeout_seconds}s). Progresso parcial em: {partial_path}",
                    generated_files=[str(partial_path)],
                )

            chunk = lines[idx : idx + config.chunk_lines]
            translated_chunk = _translate_chunk_with_fallback(config, chunk)
            translated_lines.extend(translated_chunk)
            idx += len(chunk)

            partial_text = newline.join(translated_lines)
            if has_trailing_newline or idx < len(lines):
                partial_text += newline
            partial_path.write_text(partial_text, encoding="utf-8")

            if str(partial_path) not in checkpoint_files:
                checkpoint_files.append(str(partial_path))
            if config.progress_callback is not None:
                config.progress_callback(idx, total_lines)

        final_text = newline.join(translated_lines)
        if has_trailing_newline:
            final_text += newline
        output_path.write_text(final_text, encoding="utf-8")
        try:
            partial_path.unlink(missing_ok=True)
        except OSError:
            pass
        return JobResult(
            True,
            f"Tradução local concluída: {output_path}",
            generated_files=[str(output_path)],
        )
    except urllib.error.URLError as exc:
        return JobResult(
            False,
            "Não foi possível conectar ao Ollama local. "
            f"Verifique se o serviço está ativo em {config.ollama_base_url}. Detalhe: {exc}",
            generated_files=checkpoint_files,
        )
    except TimeoutError as exc:
        return JobResult(
            False,
            f"Tempo excedido em uma requisição de tradução ({config.request_timeout_seconds}s). Detalhe: {exc}",
            generated_files=checkpoint_files,
        )
    except Exception as exc:
        return JobResult(
            False,
            f"Falha na tradução local: {exc}",
            generated_files=checkpoint_files,
        )
