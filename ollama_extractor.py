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
    "http://localhost:11434=qwen3.5:35b,http://192.168.4.1:11434=qwen2.5-coder:7b"
Each entry is url=model; hosts are tried in order per file. Default is the
consolidator box's local daemon with its largest instruct model.

Stdlib-only (urllib), sequential by design: extraction runs inside the hourly
naptime sweep where the GPU is also serving embeddings — one generation at a
time keeps VRAM predictable.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

CHAT_HOSTS_ENV = "NAPMEM_OLLAMA_CHAT"
DEFAULT_CHAT_HOSTS = "http://localhost:11434=qwen3.5:35b"

# Bounded generation: units for a ~30KB memory file fit comfortably; num_ctx
# covers the largest mirrored files plus prompt overhead.
GEN_OPTIONS = {"temperature": 0, "num_ctx": 16384, "num_predict": 8192}
PER_FILE_TIMEOUT_S = 300
PROBE_TIMEOUT_S = 3


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


def ollama_available(hosts: list[tuple[str, str]] | None = None) -> bool:
    """True when at least one configured host answers and lists its model."""
    for url, model in hosts or parse_chat_hosts():
        try:
            with urllib.request.urlopen(url + "/api/tags",
                                        timeout=PROBE_TIMEOUT_S) as resp:
                names = [m.get("name", "")
                         for m in json.load(resp).get("models", [])]
        except (urllib.error.URLError, OSError, ValueError):
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
    except ValueError:
        return content
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        if len(lists) == 1:
            return json.dumps(lists[0])
    return content


def _chat_once(url: str, model: str, prompt: str) -> str:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",
        "options": GEN_OPTIONS,
    }).encode()
    req = urllib.request.Request(
        url + "/api/chat", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=PER_FILE_TIMEOUT_S) as resp:
        data = json.load(resp)
    content = (data.get("message") or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise OllamaExtractionError(f"{url} returned no message content")
    return _coerce_array_text(content)


def extract_ollama(prompts_by_session: dict[str, str],
                   hosts: list[tuple[str, str]] | None = None) -> dict[str, str]:
    """
    Runs each session's extraction prompt through the host chain.
    Returns {session_id: raw_output_text} for the sessions that produced a
    response; sessions where every host failed are omitted so the caller can
    route them to the heuristic fallback (same contract as extract_batch).
    """
    hosts = hosts or parse_chat_hosts()
    outputs: dict[str, str] = {}
    dead_hosts: set[str] = set()
    for session_id, prompt in prompts_by_session.items():
        last_err: Exception | None = None
        for url, model in hosts:
            if url in dead_hosts:
                continue
            try:
                outputs[session_id] = _chat_once(url, model, prompt)
                last_err = None
                break
            except (urllib.error.URLError, OSError) as exc:
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
