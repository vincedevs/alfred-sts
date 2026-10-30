"""Settings for Alfred, read once at startup from environment variables (and .env)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ConfigError(Exception):
    """A setting is missing or invalid. The message says how to fix it."""


@dataclass(frozen=True)
class Config:
    openai_api_key: str
    live_model: str = "gpt-live-1"
    router_model: str = "gpt-6-luna"
    voice: str | None = None  # None lets OpenAI pick
    wakeword_dir: Path = PROJECT_ROOT / "models"
    wake_threshold: float = 0.5
    idle_seconds: float = 25.0
    input_device: int | str | None = None  # None means the system default
    output_device: int | str | None = None
    echo_cancellation: bool = True
    log_level: str = "INFO"  # what the terminal shows; the log file always gets everything


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """Build a Config from `env`, or from the real environment plus .env if `env` is None."""
    if env is None:
        load_dotenv(PROJECT_ROOT / ".env")
        env = os.environ

    api_key = env.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ConfigError("OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in.")

    defaults = Config(openai_api_key=api_key)
    return Config(
        openai_api_key=api_key,
        live_model=env.get("ALFRED_LIVE_MODEL") or defaults.live_model,
        router_model=env.get("ALFRED_ROUTER_MODEL") or defaults.router_model,
        voice=env.get("ALFRED_VOICE") or None,
        wakeword_dir=Path(env.get("ALFRED_WAKEWORD_DIR") or defaults.wakeword_dir),
        wake_threshold=_number(env, "ALFRED_WAKE_THRESHOLD", defaults.wake_threshold, 0.0, 1.0),
        idle_seconds=_number(env, "ALFRED_IDLE_SECONDS", defaults.idle_seconds, 5.0, 600.0),
        input_device=_device(env.get("ALFRED_INPUT_DEVICE")),
        output_device=_device(env.get("ALFRED_OUTPUT_DEVICE")),
        echo_cancellation=_on_off(env, "ALFRED_ECHO_CANCELLATION", defaults.echo_cancellation),
        log_level=(env.get("ALFRED_LOG_LEVEL") or defaults.log_level).upper(),
    )


def _number(env: Mapping[str, str], name: str, default: float, low: float, high: float) -> float:
    raw = env.get(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}.") from None
    if not low <= value <= high:
        raise ConfigError(f"{name} must be between {low} and {high}, got {value}.")
    return value


def _on_off(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = (env.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in ("on", "true", "yes", "1"):
        return True
    if raw in ("off", "false", "no", "0"):
        return False
    raise ConfigError(f"{name} must be on or off, got {raw!r}.")


def _device(raw: str | None) -> int | str | None:
    """sounddevice accepts a device index or part of a device name."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    return int(raw) if raw.isdigit() else raw
