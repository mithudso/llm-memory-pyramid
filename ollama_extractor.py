#!/usr/bin/env python3
"""
ollama_extractor.py — zero-API-cost LLM extraction via local Ollama chat
models.

Same contract as llm_extractor's Anthropic path: callers build prompts with
llm_extraction_prompts.get_extraction_prompt (the sentinel-guarded,
zero-fabrication prompt — the injection guards are the prompt's, not the
transport's, so they apply here unchanged) and feed the returned raw text
through llm_extractor.parse_extraction_output / units_to_records, which treat
the model output as untrusted regardless of which model produced it.

Host chain config (env NAPMEM_OLLAMA_CHAT):
    "http://localhost:11434=qwen3.5:35b,http://gpu-box:11434=qwen2.5-coder:7b"
Each entry is url=model; hosts are tried in order per file. Default is the
consolidator box's local daemon with its largest instruct model. The per-host
model chain stays here; transport (request, timeout, error mapping) is the
shared `ollama-client` library, one single-host client per chain entry.

Sequential by design: extraction runs inside the hourly naptime sweep where
the GPU is also serving embeddings — one generation at a time keeps VRAM
predictable.
"""
from __future__ import annotations

import json
import logging
import os
import re

try:
    from ollama_client import OllamaClient, OllamaPool, OllamaUnavailable
except ImportError:
    # The offline runtime has no dependency on the optional shared transport.
    OllamaClient = OllamaPool = None

    class OllamaUnavailable(RuntimeError):
        """Unavailable optional transport; no network fallback is implemented here."""

from llm_extraction_prompts import PROMPT_VERSION

logger = logging.getLogger(__name__)

CHAT_HOSTS_ENV = "NAPMEM_OLLAMA_CHAT"
DEFAULT_CHAT_HOSTS = "http://localhost:11434=qwen3.5:35b"

# Bounded generation: units for a ~30KB memory file fit comfortably; num_ctx
# covers the largest mirrored files plus prompt overhead.
GEN_OPTIONS = {"temperature": 0, "num_ctx": 16384, "num_predict": 8192}
PER_FILE_TIMEOUT_S = 300
PROBE_TIMEOUT_S = 3
OLLAMA_INSTALL_MESSAGE = (
    "Ollama extraction requires the optional shared ollama-client package. "
    "Install it with: python -m pip install 'llm-memory-pyramid[ollama]'"
)


class OllamaExtractionError(Exception):
    """Raised when no configured host can serve an extraction."""


def parse_chat_hosts(raw: str | None = None) -> list[tuple[str, str]]:
    """Parses "url=model,url=model" into an ordered host chain."""
    if raw is None:
        raw = os.environ.get(CHAT_HOSTS_ENV) or DEFAULT_CHAT_HOSTS
    hosts = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        url, sep, model = entry.partition("=")
        if not sep or not url.strip() or not model.strip():
            raise ValueError(
                f"{CHAT_HOSTS_ENV} entry {entry!r} must be url=model")
        hosts.append((url.strip().rstrip("/"), model.strip()))
    if not hosts:
        raise ValueError(f"{CHAT_HOSTS_ENV}={raw!r} yields no hosts")
    return hosts


def _client_for(url: str) -> OllamaClient:
    """Single-host client: no failover or retry here, the host chain is the failover."""
    if OllamaClient is None or OllamaPool is None:
        raise OllamaExtractionError(OLLAMA_INSTALL_MESSAGE)
    return OllamaClient(OllamaPool([url], retries=0))


def ollama_available(hosts: list[tuple[str, str]] | None = None) -> bool:
    """True when at least one configured host answers and lists its model."""
    if OllamaClient is None or OllamaPool is None:
        return False
    for url, model in hosts or parse_chat_hosts():
        try:
            names = _client_for(url).list_models(url, timeout=PROBE_TIMEOUT_S)
        except (OllamaUnavailable, OSError, ValueError):
            continue
        if any(n == model or n.split(":")[0] == model.split(":")[0]
               for n in names):
            return True
    return False


def _coerce_array_text(content: str) -> str:
    """Ollama json-mode sometimes yields a single object wrapping the array
    ({"units": [...]}); unwrap it so parse_extraction_output's strict
    array-only contract still applies to what the model meant."""
    try:
        data = json.loads(content)
    except (ValueError, RecursionError):
        return content
    if isinstance(data, dict):
        # A lone unit object (json-mode grammars force a top-level object,
        # so a one-unit extraction arrives bare): wrap it.
        if "type" in data and "text" in data:
            return json.dumps([data])
        lists = [v for v in data.values() if isinstance(v, list)]
        if len(lists) == 1:
            return json.dumps(lists[0])
    return content


THINK_RE = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL)


def _chat_once(url: str, model: str, prompt: str, client: OllamaClient | None = None) -> str:
    # No `format: "json"`: Ollama's json-mode grammar forces a top-level
    # OBJECT, but the extraction contract is a top-level ARRAY — the cage
    # made compliant answers impossible. The prompt's return-only-JSON
    # instruction plus the strict downstream parser carry the contract.
    # `think: false` disables qwen3-style reasoning preambles; hosts whose
    # models don't think ignore the field.
    content = (client or _client_for(url)).chat(
        [{"role": "user", "content": prompt}], model=model,
        options=GEN_OPTIONS, think=False, timeout=PER_FILE_TIMEOUT_S)
    if not isinstance(content, str) or not content.strip():
        raise OllamaExtractionError(f"{url} returned no message content")
    # Strip only a reasoning preamble, never literal markup inside JSON text.
    content = THINK_RE.sub("", content, count=1).strip()
    if not content:
        raise OllamaExtractionError(f"{url} returned only a think block")
    return _coerce_array_text(content)


def extract_ollama(prompts_by_session: dict[str, str],
                   hosts: list[tuple[str, str]] | None = None, *,
                   extraction_info: dict[str, dict[str, str]] | None = None) -> dict[str, str]:
    """
    Runs each session's extraction prompt through the host chain.
    Returns {session_id: raw_output_text} for the sessions that produced a
    response; sessions where every host failed are omitted so the caller can
    route them to the heuristic fallback (same contract as extract_batch).
    An optional output collector receives the actual successful model for
    each session. Failed sessions have no entry; configured fallback candidates
    are never reported as if they produced an extraction.
    """
    if extraction_info is not None:
        if not isinstance(extraction_info, dict):
            raise ValueError("extraction_info collector must be an object")
        for session_id in prompts_by_session:
            extraction_info.pop(session_id, None)
    hosts = hosts or parse_chat_hosts()
    clients = {url: _client_for(url) for url, _ in hosts}
    outputs: dict[str, str] = {}
    dead_hosts: set[str] = set()
    failed_models: set[tuple[str, str]] = set()
    for session_id, prompt in prompts_by_session.items():
        last_err: Exception | None = None
        for url, model in hosts:
            if url in dead_hosts or (url, model) in failed_models:
                continue
            try:
                outputs[session_id] = _chat_once(url, model, prompt, clients[url])
                if extraction_info is not None:
                    extraction_info[session_id] = {
                        "method": "ollama", "model": model, "prompt_version": PROMPT_VERSION}
                last_err = None
                break
            except OllamaUnavailable as exc:
                # The library also raises OllamaUnavailable for permanent
                # model errors (e.g. 404). Its pool marks down only transport
                # and transient failures; another model may work on this URL.
                if clients[url].pool.is_down(url):
                    logger.warning("Ollama host %s unreachable (%s); benching", url, exc)
                    dead_hosts.add(url)
                else:
                    logger.warning("Ollama model %s/%s unavailable; skipping model", url, model)
                    failed_models.add((url, model))
                last_err = exc
            except OSError as exc:
                # Connection-level failure: bench the host for this sweep
                # instead of paying its timeout again for every file.
                logger.warning("Ollama host %s unreachable (%s); benching", url, exc)
                dead_hosts.add(url)
                last_err = exc
            except (OllamaExtractionError, ValueError) as exc:
                logger.warning("Ollama %s/%s failed for %s: %s",
                               url, model, session_id, exc)
                last_err = exc
        if session_id not in outputs and last_err is not None:
            logger.error("Session %s: all Ollama hosts failed (%s)",
                         session_id, last_err)
    return outputs
