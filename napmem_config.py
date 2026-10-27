"""Portable TOML configuration with explicit CLI > environment > file precedence.

Resolving settings does not create directories, initialize a store, import a
model client, or probe a service. Paths in a file are relative to that file.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import sys
import tomllib
from typing import Any, Mapping
from urllib.parse import urlsplit


ENVIRONMENT = {
    "pyramid": "NAPMEM_PYRAMID", "mode": "NAPMEM_MODE", "scope": "NAPMEM_SCOPE",
    "source_roots": "NAPMEM_SOURCE_ROOTS", "embedding_backend": "NAPMEM_EMBED_BACKEND",
    "extraction": "NAPMEM_EXTRACTION", "ollama_url": "NAPMEM_OLLAMA_URL",
    "ollama_model": "NAPMEM_OLLAMA_MODEL", "chat_model": "NAPMEM_CHAT_MODEL",
    "anthropic_model": "NAPMEM_ANTHROPIC_MODEL",
}


def user_data_dir(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    home = Path(env.get("HOME") or Path.home())
    if env.get("NAPMEM_DATA_DIR"):
        return Path(env["NAPMEM_DATA_DIR"]).expanduser().absolute()
    if env.get("XDG_DATA_HOME"):
        return Path(env["XDG_DATA_HOME"]).expanduser().absolute() / "napmem"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "NapMem"
    if os.name == "nt":
        return Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local") / "NapMem"
    return home / ".local" / "share" / "napmem"


def default_config_path(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    home = Path(env.get("HOME") or Path.home())
    if env.get("XDG_CONFIG_HOME"):
        return Path(env["XDG_CONFIG_HOME"]).expanduser().absolute() / "napmem" / "config.toml"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "NapMem" / "config.toml"
    if os.name == "nt":
        return Path(env.get("APPDATA") or home / "AppData" / "Roaming") / "NapMem" / "config.toml"
    return home / ".config" / "napmem" / "config.toml"


def _path(value: Any, base: Path, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be a nonempty path")
    path = Path(value).expanduser()
    return os.path.abspath(path if path.is_absolute() else base / path)


@dataclass(frozen=True)
class NapMemConfig:
    pyramid: str
    config_path: str
    mode: str = "offline"
    scope: str | None = None
    source_roots: tuple[str, ...] = ()
    embedding_backend: str = "hashed"
    extraction: str = "heuristic"
    ollama_url: str | None = None
    ollama_model: str | None = None
    chat_model: str | None = None
    anthropic_model: str | None = None
    origins: dict[str, str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_config(cli: Mapping[str, Any] | None = None, *,
                   environ: Mapping[str, str] | None = None) -> NapMemConfig:
    """Resolve and validate one configuration without changing external state."""
    cli = dict(cli or {})
    env = os.environ if environ is None else environ
    config_name = cli.get("config") or env.get("NAPMEM_CONFIG")
    config_path = Path(_path(config_name, Path.cwd(), "config") if config_name else default_config_path(env))
    explicit_config = bool(config_name)
    file_values: dict[str, Any] = {}
    try:
        with config_path.open("rb") as stream:
            raw = tomllib.load(stream)
    except FileNotFoundError:
        if explicit_config:
            raise ValueError(f"Configuration file does not exist: {config_path}") from None
    else:
        # Accept a single [napmem] table or plain top-level settings, never both.
        if "napmem" in raw:
            if set(raw) != {"napmem"} or not isinstance(raw["napmem"], dict):
                raise ValueError("Configuration must contain only a [napmem] table")
            raw = raw["napmem"]
        if set(raw) - set(ENVIRONMENT):
            raise ValueError("Unknown configuration fields: " + ", ".join(sorted(set(raw) - set(ENVIRONMENT))))
        file_values = raw
    values: dict[str, Any] = {
        "pyramid": str(user_data_dir(env) / "napmem_pyramid.json"), "mode": "offline", "scope": None,
        "source_roots": [], "embedding_backend": "hashed", "extraction": "heuristic",
        "ollama_url": None, "ollama_model": None, "chat_model": None, "anthropic_model": None,
    }
    origins = {key: "default" for key in values}
    for origin, incoming in (("file", file_values),
                             ("environment", {key: env[name] for key, name in ENVIRONMENT.items() if env.get(name)}),
                             ("cli", {key: cli[key] for key in ENVIRONMENT if cli.get(key) is not None})):
        for key, value in incoming.items():
            base = config_path.parent if origin == "file" else Path.cwd()
            if key == "pyramid":
                value = _path(value, base, key)
            elif key == "source_roots":
                if origin == "environment":
                    value = value.split(os.pathsep)
                if not isinstance(value, (list, tuple)):
                    raise ValueError("source_roots must be an array of paths")
                value = [_path(item, base, "source root") for item in value]
            values[key], origins[key] = value, origin
    for field, choices in (("mode", ("offline", "local", "remote")),
                           ("embedding_backend", ("hashed", "ollama")),
                           ("extraction", ("heuristic", "ollama", "anthropic"))):
        if values[field] not in choices:
            raise ValueError(f"{field} must be one of: {', '.join(choices)}")
    for field in ("scope", "ollama_url", "ollama_model", "chat_model", "anthropic_model"):
        value = values[field]
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 4096
                                  or any(ord(char) < 32 for char in value)):
            raise ValueError(f"{field} must be a nonempty string without control characters")
    if values["scope"] is not None and values["scope"] != "*":
        from napmem_model import normalize_record
        normalize_record({"id": "config_scope", "text": "", "scope": values["scope"]})
    if values["ollama_url"] is not None:
        url = urlsplit(values["ollama_url"])
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
            raise ValueError("ollama_url must be an HTTP(S) endpoint without embedded credentials")
    if values["mode"] == "offline" and (values["embedding_backend"] != "hashed" or values["extraction"] != "heuristic"):
        raise ValueError("Offline mode requires hashed embeddings and heuristic extraction; select local or remote explicitly")
    values["pyramid"] = os.path.abspath(values["pyramid"])
    values["source_roots"] = tuple(dict.fromkeys(values["source_roots"]))
    return NapMemConfig(**values, config_path=str(config_path), origins=origins)


@contextmanager
def runtime_environment(config: NapMemConfig):
    """Apply settings for this command and restore the caller's environment."""
    settings = {"NAPMEM_EMBED_BACKEND": config.embedding_backend}
    for field, variable in (("ollama_url", "NAPMEM_OLLAMA_URL"), ("ollama_model", "NAPMEM_OLLAMA_MODEL")):
        value = getattr(config, field)
        if value is not None:
            settings[variable] = value
    previous = {key: os.environ.get(key) for key in settings}
    os.environ.update(settings)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
