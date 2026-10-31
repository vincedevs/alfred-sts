"""When a conversation closes. GPT-Live bills for every open second, silence included.

After about `idle_seconds` of quiet a soft warning tone plays; if nobody speaks within
WARNING_SECONDS, the session closes (and __main__.py plays the sleep sound). While a job
is running or waiting for your answer, Alfred stays open longer, up to KEEP_OPEN_SECONDS
of quiet, so you hear the result or the question.

During the warning, our own microphone check (audio_log.py) also counts: it hears you a
moment before GPT-Live reports you speaking, which matters right at the deadline.
"""

import asyncio
import time

from loguru import logger
from pipecat.frames.frames import EndFrame

WARNING_SECONDS = 5  # the warning tone plays this long before closing
KEEP_OPEN_SECONDS = 120  # most quiet time while a job is busy
TONE_SECONDS = 1.0  # the tone and its echo in the room aren't you speaking
LISTEN_EVERY = 0.05


def check_every(idle_seconds: float) -> float:
    """How often Pipecat should report quiet: early enough to warn before closing."""
    return max(idle_seconds - WARNING_SECONDS, 1.0)


class QuietTimer:
    """is_busy(): is a job running or waiting for an answer? on_closing(): called just
    before the session is closed."""

    def __init__(self, worker, engine, warning_sound, idle_seconds: float, is_busy, on_closing):
        self._worker, self._engine, self._warning_sound = worker, engine, warning_sound
        self._interval = check_every(idle_seconds)
        self._is_busy, self._on_closing = is_busy, on_closing
        self._quiet_since: float | None = None  # when the current quiet stretch began
        self._closing_soon: asyncio.Task | None = None  # set once the warning has played
        self._closing = False  # too late: the session is closing
        self._mic_saved_us = False  # the microphone check kept it open once already

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
        if self._is_busy() and quiet < KEEP_OPEN_SECONDS:
            logger.info(f"Quiet for {quiet:.0f} s, but a job is busy: staying open")
            return
        logger.info(f"Quiet for {quiet:.0f} s: warning tone, closing in {WARNING_SECONDS} s")
        self._engine.play(self._warning_sound)
        self._closing_soon = asyncio.create_task(self._close_after_warning())

    def activity(self) -> None:
        """Someone spoke: start counting quiet again, and don't close."""
        self._quiet_since = None
        self._mic_saved_us = False
        if self._closing:
            logger.info("Speech came just after the session started closing")
        elif self._closing_soon:
            logger.info("Speech after the warning: staying open")
            self.stop()

    def stop(self) -> None:
        if self._closing_soon:
            self._closing_soon.cancel()
            self._closing_soon = None

    async def _close_after_warning(self) -> None:
        started = time.monotonic()
        mic_went_quiet = False  # only a voice that starts after the tone has faded counts
        while time.monotonic() - started < WARNING_SECONDS:
            await asyncio.sleep(LISTEN_EVERY)
            if time.monotonic() - started < TONE_SECONDS:
                continue
            mic_went_quiet = mic_went_quiet or not self._engine.activity.mic.on
            if mic_went_quiet and self._you_are_speaking():
                logger.info("Voice on the microphone after the warning: staying open")
                self._mic_saved_us = True  # once per quiet stretch, so a TV can't keep it open
                self._closing_soon = None
                return
        logger.info("No speech after the warning, closing the session")
        self._closing = True
        self._on_closing()
        await self._worker.queue_frame(EndFrame())  # lets GPT-Live finish and close cleanly

    def _you_are_speaking(self) -> bool:
        sound = self._engine.activity
        return not self._mic_saved_us and sound.mic.on and not sound.speaker.on
