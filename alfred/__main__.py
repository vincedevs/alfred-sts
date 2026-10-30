"""Start Alfred: `uv run alfred`.

The whole program is one loop:
    listen for "Hey Alfred" -> wake sound -> talk with GPT-Live -> (idle) -> listen again

Background jobs (tasks.py) run alongside that loop; a soft chime plays when one finishes.

Every run writes a full DEBUG log to logs/alfred-<date>-<time>.log; the terminal
shows ALFRED_LOG_LEVEL (INFO by default).
"""

import asyncio
import os
import platform
import signal
import sys
from datetime import datetime
from importlib.metadata import version

from loguru import logger

from alfred.audio import AudioEngine, load_sound
from alfred.config import PROJECT_ROOT, Config, ConfigError, load_config
from alfred.db import Database
from alfred.tasks import TaskRunner
from alfred.voice import run_conversation
from alfred.wakeword import WakeWordDetector

LOG_DIR = PROJECT_ROOT / "logs"
NEAR_MISS_SCORE = 0.2  # wake-word scores above this are logged, to help tune the threshold


async def run(config: Config) -> None:
    detector = WakeWordDetector(config.wakeword_dir, config.wake_threshold)
    wake_sound = load_sound(PROJECT_ROOT / "sounds" / "listening_start.wav")
    done_sound = load_sound(PROJECT_ROOT / "sounds" / "task_done.wav")
    engine = AudioEngine(config.input_device, config.output_device, config.echo_cancellation)
    engine.start()

    config.workspace_dir.mkdir(parents=True, exist_ok=True)
    db = Database(config.database_path)
    tasks = TaskRunner(db, config, on_finished=lambda _task: engine.play(done_sound))
    if resumed := tasks.resume_unfinished():
        logger.info(f"Resumed {resumed} unfinished job(s)")
    handle_shutdown_signals(tasks)
    try:
        while True:
            logger.info('Waiting for "Hey Alfred"...')
            await wait_for_wake_word(engine, detector)
            logger.info(f"Wake word heard (score {detector.last_score:.2f})")
            engine.play(wake_sound)  # tells you Alfred is listening
            await run_conversation(engine, config, tasks, db)

            # Pipecat's runner swallows the cancellation Ctrl+C sends, so pass it on.
            if asyncio.current_task().cancelling():
                raise asyncio.CancelledError
            detector.reset()
            engine.clear_mic()  # don't let the end of the conversation wake us again
    finally:
        await tasks.close()  # unfinished jobs stay recorded and resume next start
        db.close()
        engine.close()


def handle_shutdown_signals(tasks: TaskRunner) -> None:
    """Ctrl+C (or a stop from systemd later) ends Alfred cleanly. Tell the job runner first:
    the same Ctrl+C also interrupts Claude's process, and that must not count as a failure."""
    main_task = asyncio.current_task()
    stopping = False

    def shut_down() -> None:
        nonlocal stopping
        if stopping:
            os._exit(1)  # a second Ctrl+C quits at once
        stopping = True
        logger.info("Shutting down (press Ctrl+C again to force)...")
        tasks.begin_shutdown()
        main_task.cancel()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shut_down)


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

    packages = ("pipecat-ai", "claude-agent-sdk", "livekit", "sounddevice", "onnxruntime")
    logger.debug(
        f"Python {platform.python_version()} on {platform.platform()}; "
        + ", ".join(f"{name} {version(name)}" for name in packages)
    )
    settings = {k: v for k, v in vars(config).items() if k != "openai_api_key"}
    logger.debug(f"Settings: {settings}")

    # Claude signs in with one of these (never logged): see .env.example.
    if os.environ.get("ANTHROPIC_API_KEY"):
        logger.info("Claude jobs: using ANTHROPIC_API_KEY (billed per use)")
    elif os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        logger.info("Claude jobs: using your Claude plan (CLAUDE_CODE_OAUTH_TOKEN)")
    else:
        logger.warning("No Claude sign-in in .env: background jobs will fail")


def main() -> None:
    try:
        config = load_config()
    except ConfigError as error:
        sys.exit(f"Config error: {error}")

    setup_logging(config)
    try:
        asyncio.run(run(config))
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Bye.")
    except Exception:
        logger.exception("Alfred crashed")
        sys.exit(1)


if __name__ == "__main__":
    main()
