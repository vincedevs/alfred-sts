"""fd-benchmark's entry for Alfred (from its adapters/assistant_entry_template.py).

fd-benchmark's launcher loads this file, then calls build() with its own transport.
Point the launcher here with this line in fd-benchmark/.env:

    FDBENCH_ENTRY=/path/to/alfred-sts/benchmark/assistant_entry.py

Imports from Alfred happen inside build(): the launcher adds the project to sys.path
only after loading this file.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# A file that identifies Alfred's project folder (relative to it).
PROJECT_MARKER = "alfred/voice.py"


def describe() -> dict:
    """The models, for the results card in fd-benchmark's report."""
    from alfred.config import load_config

    config = load_config()
    speech = f"{config.live_model} (speech to speech: hears and speaks itself)"
    return {
        "ASR": speech,
        "LLM": f"{speech}; router {config.router_model} for look-ups",
        "TTS": speech,
        "VAD": f"{config.live_model} turn detection",
    }


def audio_rates() -> tuple[int, int]:
    """Alfred's pipeline runs at 16 kHz both ways (alfred/audio.py: SAMPLE_RATE)."""
    return 16000, 16000


async def build(transport, log_dir: Path):
    """Build Alfred's conversation with fd-benchmark's transport.
    Returns (a coroutine that runs it, an async function that stops it)."""
    from loguru import logger

    from alfred.config import ConfigError, load_config
    from benchmark.voice import build_benchmark_conversation

    try:
        config = load_config()  # Alfred's own .env: API key, models, voice, home
    except ConfigError as error:
        sys.exit(f"Alfred's config: {error}")

    # Benchmark logs go to fd-benchmark's folder, not Alfred's logs/.
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"alfred-bench-{datetime.now():%Y%m%d-%H%M%S}.log"
    logger.remove()
    logger.add(sys.stderr, level=config.log_level)
    logger.add(log_file, level="DEBUG", backtrace=True, diagnose=False)
    logger.info(f"Alfred in benchmark mode; logging to {log_file}")

    return await build_benchmark_conversation(transport, config)
