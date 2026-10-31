"""Logging: the terminal shows ALFRED_LOG_LEVEL (INFO by default), and every run writes a
full DEBUG log to logs/alfred-<date>-<time>.log. Logs older than KEEP_DAYS are deleted
at startup: they record what was said, and an always-on Alfred would fill the disk."""

import os
import platform
import sys
import time
from importlib.metadata import version

from loguru import logger

from alfred.config import PROJECT_ROOT, SECRET_SETTINGS, Config

LOG_DIR = PROJECT_ROOT / "logs"
KEEP_DAYS = 14


def setup_logging(config: Config) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    removed = delete_old_logs()
    log_file = LOG_DIR / f"alfred-{config.now():%Y%m%d-%H%M%S}.log"
    logger.remove()
    logger.add(sys.stderr, level=config.log_level)
    logger.add(log_file, level="DEBUG", backtrace=True, diagnose=False)
    logger.info(f"Logging everything to {log_file.relative_to(PROJECT_ROOT)}")
    if removed:
        logger.debug(f"Deleted {removed} log(s) older than {KEEP_DAYS} days")

    packages = ("pipecat-ai", "claude-agent-sdk", "livekit", "sounddevice", "onnxruntime")
    logger.debug(
        f"Python {platform.python_version()} on {platform.platform()}; "
        + ", ".join(f"{name} {version(name)}" for name in packages)
    )
    settings = {k: v for k, v in vars(config).items() if k not in SECRET_SETTINGS}
    logger.debug(f"Settings: {settings}")

    # Claude signs in with one of these (never logged): see .env.example.
    if os.environ.get("ANTHROPIC_API_KEY"):
        logger.info("Claude jobs: using ANTHROPIC_API_KEY (billed per use)")
    elif os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        logger.info("Claude jobs: using your Claude plan (CLAUDE_CODE_OAUTH_TOKEN)")
    else:
        logger.warning("No Claude sign-in in .env: background jobs will fail")


def delete_old_logs() -> int:
    cutoff = time.time() - KEEP_DAYS * 86400
    old = [log for log in LOG_DIR.glob("alfred-*.log") if log.stat().st_mtime < cutoff]
    for log in old:
        log.unlink()
    return len(old)
