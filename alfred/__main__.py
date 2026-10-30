"""Start Alfred: `uv run alfred`.

The whole program is one loop:
    listen for "Hey Alfred" -> wake sound -> talk with GPT-Live -> (idle) -> listen again

Every run writes a full DEBUG log to logs/alfred-<date>-<time>.log; the terminal
shows ALFRED_LOG_LEVEL (INFO by default).
"""

import asyncio
import platform
import sys
from datetime import datetime
from importlib.metadata import version

from loguru import logger

from alfred.audio import AudioEngine, load_sound
from alfred.config import PROJECT_ROOT, Config, ConfigError, load_config
from alfred.voice import run_conversation
from alfred.wakeword import WakeWordDetector

LOG_DIR = PROJECT_ROOT / "logs"
NEAR_MISS_SCORE = 0.2  # wake-word scores above this are logged, to help tune the threshold


async def run(config: Config) -> None:
    detector = WakeWordDetector(config.wakeword_dir, config.wake_threshold)
    wake_sound = load_sound(PROJECT_ROOT / "sounds" / "listening_start.wav")
    engine = AudioEngine(config.input_device, config.output_device, config.echo_cancellation)
    engine.start()
    try:
        while True:
            logger.info('Waiting for "Hey Alfred"...')
            await wait_for_wake_word(engine, detector)
            logger.info(f"Wake word heard (score {detector.last_score:.2f})")
            engine.play(wake_sound)  # tells you Alfred is listening
            await run_conversation(engine, config)

            # Pipecat's runner swallows the cancellation Ctrl+C sends, so pass it on.
            if asyncio.current_task().cancelling():
                raise asyncio.CancelledError
            detector.reset()
            engine.clear_mic()  # don't let the end of the conversation wake us again
    finally:
        engine.close()


async def wait_for_wake_word(engine: AudioEngine, detector: WakeWordDetector) -> None:
    last_logged = 0.0
    while not detector.process(await engine.mic.get()):
        score = detector.last_score
        if score >= NEAR_MISS_SCORE and score != last_logged:
            logger.debug(f"Wake word near miss: score {score:.2f}")
            last_logged = score


def setup_logging(config: Config) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"alfred-{datetime.now():%Y%m%d-%H%M%S}.log"
    logger.remove()
    logger.add(sys.stderr, level=config.log_level)
    logger.add(log_file, level="DEBUG", backtrace=True, diagnose=False)
    logger.info(f"Logging everything to {log_file.relative_to(PROJECT_ROOT)}")

    packages = ("pipecat-ai", "livekit", "sounddevice", "onnxruntime", "numpy")
    logger.debug(
        f"Python {platform.python_version()} on {platform.platform()}; "
        + ", ".join(f"{name} {version(name)}" for name in packages)
    )
    settings = {k: v for k, v in vars(config).items() if k != "openai_api_key"}
    logger.debug(f"Settings: {settings}")


def main() -> None:
    try:
        config = load_config()
    except ConfigError as error:
        sys.exit(f"Config error: {error}")

    setup_logging(config)
    try:
        asyncio.run(run(config))
    except KeyboardInterrupt:
        logger.info("Bye.")
    except Exception:
        logger.exception("Alfred crashed")
        sys.exit(1)


if __name__ == "__main__":
    main()
