"""What Alfred says when you wake him, and how you send him to sleep.

Waking: "Hey Alfred" on its own gets a short greeting ("Yes, sir?"). "Hey Alfred, what
time is it?" doesn't: he just answers. Which one it was is decided by our own microphone
check (audio_log.py) in the second after the wake word, while the GPT-Live session opens.

Sleeping: "Alfred, go to sleep" reaches the router, which calls go_to_sleep. Alfred says
goodbye and the session closes straight after (idle.py), instead of waiting out the quiet
timeout. Jobs keep running, and timers and alarms still ring; "Hey Alfred" wakes him.
"""

import asyncio
import time

from loguru import logger
from pipecat.services.llm_service import FunctionCallParams

from alfred.questions import Questions

SKIP_SECONDS = 0.4  # the end of "Hey Alfred" itself, still on the microphone
LISTEN_SECONDS = 1.2  # speech starting before this, after the wake word, is a request
LISTEN_EVERY = 0.05

GREETING = (
    "The user just said your name and nothing else. Greet them in two or three words, in "
    'character ("Yes, sir?", "At your service."), then wait for them.'
)


async def kept_talking(activity) -> bool:
    """Started right after the wake word: did the user go on speaking ("Hey Alfred, do
    X")? Only a voice while Alfred's speaker is quiet counts (not the wake chime)."""
    started = time.monotonic()
    await asyncio.sleep(SKIP_SECONDS)
    while time.monotonic() - started < LISTEN_SECONDS:
        if activity.mic.on and not activity.speaker.on:
            return True
        await asyncio.sleep(LISTEN_EVERY)
    return False


async def greet_unless_asked(kept_talking_check: asyncio.Task, tell) -> None:
    """Once the session is open: greet, unless a request followed the wake word."""
    if await kept_talking_check:
        logger.info("A request followed the wake word: no greeting")
        return
    logger.info("Only the wake word: greeting")
    tell(GREETING)


def sleep_tools(go_to_sleep_soon, questions: Questions) -> list:
    """The router's go_to_sleep tool. go_to_sleep_soon() closes the session once Alfred
    has said goodbye (idle.py)."""

    async def go_to_sleep(params: FunctionCallParams):
        """End the conversation: Alfred stops listening until someone says "Hey Alfred"
        again. Only when the user explicitly tells Alfred to sleep ("go to sleep",
        "Alfred, sleep", "you can sleep now"). Never for "thanks", "that's all",
        "goodnight", "bye" or "never mind": answer those normally.
        """
        go_to_sleep_soon()
        note = "Alfred goes to sleep as soon as he has said goodbye."
        waiting = len(questions.waiting())
        if waiting:
            note += (
                f" {waiting} question(s) from background jobs still wait for the user's "
                "answer: mention that in a few words, then"
            )
        else:
            note += " Now"
        note += " say a brief goodnight, in a few words, and nothing more."
        await params.result_callback({"status": "going to sleep", "note": note})

    return [go_to_sleep]
