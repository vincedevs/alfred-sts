"""When a conversation closes. GPT-Live bills for every open second, silence included.

After about `idle_seconds` of quiet a soft warning tone plays; if nobody speaks within
WARNING_SECONDS, the session closes (and __main__.py plays the sleep sound). While a job
is running or waiting for your answer, Alfred stays open longer, up to KEEP_OPEN_SECONDS
of quiet, so you hear the result or the question.
"""

import asyncio
import time

from loguru import logger
from pipecat.frames.frames import EndFrame

WARNING_SECONDS = 5  # the warning tone plays this long before closing
KEEP_OPEN_SECONDS = 120  # most quiet time while a job is busy


def check_every(idle_seconds: float) -> float:
    """How often Pipecat should report quiet: early enough to warn before closing."""
    return max(idle_seconds - WARNING_SECONDS, 1.0)


class QuietTimer:
    def __init__(self, worker, engine, warning_sound, config, tasks, questions, announcer):
        self._worker, self._engine, self._warning_sound = worker, engine, warning_sound
        self._interval = check_every(config.idle_seconds)
        self._tasks, self._questions, self._announcer = tasks, questions, announcer
        self._quiet_since: float | None = None  # when the current quiet stretch began
        self._closing_soon: asyncio.Task | None = None  # set once the warning has played

    def listen(self, worker, user_turns) -> None:
        """Hook into Pipecat: its quiet reports, and the moment you start speaking (not
        when you finish, which may be too late to stop a closing session)."""

        @worker.event_handler("on_idle_timeout")
        async def on_idle(_worker):
            await self.on_idle()

        @user_turns.event_handler("on_user_turn_started")
        async def on_user_started(_aggregator, _strategy):
            self.activity()

    async def on_idle(self) -> None:
        """Pipecat calls this after every `check_every` seconds with nobody speaking."""
        if self._closing_soon:
            return
        now = time.monotonic()
        self._quiet_since = self._quiet_since or now - self._interval
        quiet = now - self._quiet_since
        if (self._tasks.busy or self._questions.waiting()) and quiet < KEEP_OPEN_SECONDS:
            logger.info(f"Quiet for {quiet:.0f} s, but a job is busy: staying open")
            return
        logger.info(f"Quiet for {quiet:.0f} s: warning tone, closing in {WARNING_SECONDS} s")
        self._engine.play(self._warning_sound)
        self._closing_soon = asyncio.create_task(self._close_after_warning())

    def activity(self) -> None:
        """Someone spoke: start counting quiet again, and don't close."""
        self._quiet_since = None
        if self._closing_soon:
            logger.info("Speech after the warning: staying open")
            self.stop()

    def stop(self) -> None:
        if self._closing_soon:
            self._closing_soon.cancel()
            self._closing_soon = None

    async def _close_after_warning(self) -> None:
        await asyncio.sleep(WARNING_SECONDS)
        logger.info("No speech after the warning, closing the session")
        self._announcer.closing = True
        await self._worker.queue_frame(EndFrame())  # lets GPT-Live finish and close cleanly
