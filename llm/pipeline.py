"""Minimal triager/distiller/linker LLM processing pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from llm.providers import LLMProvider, LLMRequest, LLMResponse
from run_logger import RunLogger, hash_file


PROMPT_TRIAGER = "triager.v1"
PROMPT_DISTILLER = "distiller.v1"
PROMPT_LINKER = "linker.v1"


@dataclass(frozen=True)
class StageResult:
    prompt_version: str
    text: str
    status: str


@dataclass(frozen=True)
class ProcessResult:
    run_id: str
    input_file_hash: str
    status: str
    triage: StageResult
    distillation: StageResult
    links: StageResult
    run_path: Path


def _call_stage(
    *,
    provider: LLMProvider,
    logger: RunLogger,
    prompt_version: str,
    input_text: str,
    input_file_hash: str,
) -> StageResult:
    started = time.perf_counter()
    status = "ok"
    error = None
    response: LLMResponse | None = None
    try:
        response = provider.complete(
            LLMRequest(
                prompt_version=prompt_version,
                input_text=input_text,
                input_file_hash=input_file_hash,
            )
        )
        return StageResult(
            prompt_version=prompt_version,
            text=response.text,
            status=status,
        )
    except Exception as exc:
        status = "error"
        error = exc.__class__.__name__
        raise
    finally:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        config = provider.config
        logger.log_llm_call(
            {
                "provider": config.provider,
                "model": config.model,
                "prompt_version": prompt_version,
                "input_file_hash": input_file_hash,
                "tokens": response.tokens if response else None,
                "latency": elapsed_ms,
                "status": status,
                "error": error,
            }
        )


def triager(
    *,
    provider: LLMProvider,
    logger: RunLogger,
    input_text: str,
    input_file_hash: str,
) -> StageResult:
    return _call_stage(
        provider=provider,
        logger=logger,
        prompt_version=PROMPT_TRIAGER,
        input_text=input_text,
        input_file_hash=input_file_hash,
    )


def distiller(
    *,
    provider: LLMProvider,
    logger: RunLogger,
    input_text: str,
    input_file_hash: str,
    triage: StageResult,
) -> StageResult:
    return _call_stage(
        provider=provider,
        logger=logger,
        prompt_version=PROMPT_DISTILLER,
        input_text=f"{triage.text}\n\n{input_text}",
        input_file_hash=input_file_hash,
    )


def linker(
    *,
    provider: LLMProvider,
    logger: RunLogger,
    input_text: str,
    input_file_hash: str,
    distillation: StageResult,
) -> StageResult:
    return _call_stage(
        provider=provider,
        logger=logger,
        prompt_version=PROMPT_LINKER,
        input_text=f"{distillation.text}\n\n{input_text}",
        input_file_hash=input_file_hash,
    )


def process_file(
    input_path: Path,
    *,
    provider: LLMProvider,
    logger: RunLogger | None = None,
) -> ProcessResult:
    logger = logger or RunLogger()
    input_path = input_path.resolve()
    raw_text = input_path.read_text(encoding="utf-8")
    input_file_hash = hash_file(input_path)

    logger.log_event(
        "process_started",
        {
            "input_file_hash": input_file_hash,
            "input_path_name": input_path.name,
        },
    )
    triage = triager(
        provider=provider,
        logger=logger,
        input_text=raw_text,
        input_file_hash=input_file_hash,
    )
    distillation = distiller(
        provider=provider,
        logger=logger,
        input_text=raw_text,
        input_file_hash=input_file_hash,
        triage=triage,
    )
    links = linker(
        provider=provider,
        logger=logger,
        input_text=raw_text,
        input_file_hash=input_file_hash,
        distillation=distillation,
    )
    result = ProcessResult(
        run_id=logger.run_id,
        input_file_hash=input_file_hash,
        status="ok",
        triage=triage,
        distillation=distillation,
        links=links,
        run_path=logger.run_path,
    )
    logger.log_event(
        "process_completed",
        {
            "input_file_hash": input_file_hash,
            "status": result.status,
        },
    )
    logger.write_state(
        {
            "input_file_hash": input_file_hash,
            "status": result.status,
            "run_path": str(logger.run_path),
        }
    )
    return result
