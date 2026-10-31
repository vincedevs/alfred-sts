"""Settings for Alfred, read once at startup from environment variables (and .env)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


SECRET_SETTINGS = ("openai_api_key", "email_app_password")  # never logged


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
    data_dir: Path = Path.home() / ".alfred"  # database and Claude's workspace
    agent_model: str = "claude-haiku-5-5"  # Claude model for background jobs
    task_budget_usd: float = 0.25  # a job stops if it would cost more than this
    email_address: str | None = None  # the Gmail account jobs send from
    email_app_password: str | None = None  # a Gmail app password, never your real one
    # Alfred doesn't start talking on his own between these hours (start, end), except for
    # reminders you set. None: no quiet hours.
    quiet_hours: tuple[int, int] | None = (22, 7)
    # Where you are: places, units, money and spelling default to these.
    home: str = "Manila, Philippines"
    units: str = "metric"  # metric | imperial
    currency: str = "Philippine pesos (PHP, ₱)"
    # Every time Alfred works with (reminders, quiet hours, "now") is in this time zone,
    # whatever the computer is set to: a new Raspberry Pi starts on UTC.
    timezone: str = "Asia/Manila"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "alfred.db"

    @property
    def workspace_dir(self) -> Path:
        """The only folder Claude may read and write files in."""
        return self.data_dir / "workspace"

    @property
    def audit_path(self) -> Path:
        return self.data_dir / "audit.jsonl"

    @property
    def profile_path(self) -> Path:
        """What Alfred knows about you: one fact per line, yours to read and edit."""
        return self.data_dir / "profile.md"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def now(self) -> datetime:
        """The current time where you are."""
        return datetime.now(self.tz)

    def local(self, timestamp: float) -> datetime:
        """A stored Unix time, as your local time."""
        return datetime.fromtimestamp(timestamp, self.tz)

    def home_text(self) -> str:
        """For every prompt (Alfred's voice, the router, jobs): where the user is."""
        offset = self.now().strftime("%z")
        examples = "°C, km, kg" if self.units == "metric" else "°F, miles, pounds"
        return (
            f"\n\n## Where the user is\nThe user lives in {self.home} (local time is "
            f"UTC{offset[:3]}:{offset[3:]}). Unless they say otherwise: assume places, "
            f"news, weather, shops and events near home; give {self.units} units "
            f"({examples}) and prices in {self.currency}; use local dates and times."
        )

    def is_quiet(self, now: datetime | None = None) -> bool:
        if not self.quiet_hours:
            return False
        start, end = self.quiet_hours
        hour = (now or self.now()).hour
        return start <= hour or hour < end if start > end else start <= hour < end


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """Build a Config from `env`, or from the real environment plus .env if `env` is None."""
    if env is None:
        # override: .env wins over variables left in your shell (e.g. by `source .env`).
        load_dotenv(PROJECT_ROOT / ".env", override=True)
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
        data_dir=Path(env.get("ALFRED_DATA") or defaults.data_dir).expanduser(),
        agent_model=env.get("ALFRED_AGENT_MODEL") or defaults.agent_model,
        task_budget_usd=_number(
            env, "ALFRED_TASK_BUDGET_USD", defaults.task_budget_usd, 0.01, 10.0
        ),
        email_address=(env.get("ALFRED_EMAIL") or "").strip() or None,
        email_app_password=(env.get("ALFRED_EMAIL_APP_PASSWORD") or "").replace(" ", "") or None,
        quiet_hours=_hours(env.get("ALFRED_QUIET_HOURS"), defaults.quiet_hours),
        home=env.get("ALFRED_HOME") or defaults.home,
        units=_choice(env, "ALFRED_UNITS", defaults.units, ("metric", "imperial")),
        currency=env.get("ALFRED_CURRENCY") or defaults.currency,
        timezone=_timezone(env.get("ALFRED_TIMEZONE") or defaults.timezone),
    )


def load_prompt(name: str) -> str:
    """Prompts live as plain text in prompts/<name>.md."""
    return (PROJECT_ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8").strip()


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


def _timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        message = f"ALFRED_TIMEZONE must be a time zone like Asia/Manila, got {name!r}."
        raise ConfigError(message) from None
    return name


def _choice(env: Mapping[str, str], name: str, default: str, allowed: tuple[str, ...]) -> str:
    raw = (env.get(name) or "").strip().lower() or default
    if raw not in allowed:
        raise ConfigError(f"{name} must be one of {', '.join(allowed)}, got {raw!r}.")
    return raw


def _hours(raw: str | None, default: tuple[int, int] | None) -> tuple[int, int] | None:
    """ "22-7" means 10 pm to 7 am; "off" means no quiet hours."""
    raw = (raw or "").strip().lower()
    if not raw:
        return default
    if raw in ("off", "none", "no"):
        return None
    try:
        start, end = (int(part) for part in raw.split("-"))
    except ValueError:
        raise ConfigError(f"ALFRED_QUIET_HOURS must look like 22-7 or off, got {raw!r}.") from None
    if not (0 <= start <= 23 and 0 <= end <= 23):
        raise ConfigError(f"ALFRED_QUIET_HOURS hours must be 0 to 23, got {raw!r}.")
    return start, end


def _device(raw: str | None) -> int | str | None:
    """sounddevice accepts a device index or part of a device name."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    return int(raw) if raw.isdigit() else raw
