"""What Alfred says when you wake him, and how you send him to sleep.

Waking: "Hey Alfred" on its own gets a short greeting ("Yes, sir?"). "Hey Alfred, what
time is it?" doesn't: he just answers. Which one it was is decided by our own microphone
check (audio_log.py) in the moments after the wake word, while the GPT-Live session opens.
The wake chime's faint echo lingers on the mic, so only clear speech counts.

Sleeping: "Alfred, go to sleep" is recognised here, from what you said, not by a model:
GPT-Live said "Goodnight, sir." but often didn't hand the request on. It counts only when
the whole sentence is the command ("sleep right now", "I said go to sleep"), so "remind me
to go to sleep at 11" is left alone. Alfred says goodnight and the session closes as soon
as he's done (idle.py). Jobs keep running, timers and
alarms still ring, waiting questions are asked next time, and "Hey Alfred" wakes him.
"""

import asyncio
import re
import time

from loguru import logger

from alfred.announcer import FILLER, quick_answer

SKIP_SECONDS = 0.4  # the end of "Hey Alfred" itself, still on the microphone
LISTEN_SECONDS = 1.5  # speech this soon after the wake word is a request
CHIME_SETTLE = 0.35  # the wake chime has been quiet this long
SPEECH_DBFS = -50.0  # the chime's echo measured -54 to -58; speech -29 to -45
LISTEN_EVERY = 0.05

GREETING = (
    "The user just said your name and nothing else. Greet them in two or three words, in "
    'character ("Yes, sir?", "At your service."), then wait for them.'
)

# The only words a sleep command may have besides "sleep": "go to sleep", "sleep right
# now", "Alfred, you can go back to sleep", "I told you to sleep", "time to sleep, sir".
# Any other word ("remind me…", "are you going…", "don't…", "couldn't") means it's not one.
SLEEP_COMMAND_WORDS = {
    "sleep", "go", "back", "to", "now", "right", "please", "just", "alfred", "sir", "you",
    "can", "could", "should", "i", "said", "told", "time", "it's", "its", "is", "then",
    "already", "alright", "all", "hey", "mode",
}  # fmt: skip
OFFER = re.compile(r"\bgo to sleep\b.*\?")  # Alfred asked "Shall I go to sleep?"


async def kept_talking(activity) -> bool:
    """Started right after the wake word: did the user go on speaking ("Hey Alfred, do
    X")? Only clear speech once the wake chime has died away counts."""
    started = time.monotonic()
    speaker_quiet_since = started
    await asyncio.sleep(SKIP_SECONDS)
    while time.monotonic() - started < LISTEN_SECONDS:
        now = time.monotonic()
        mic = activity.mic
        if activity.speaker.on:
            speaker_quiet_since = now
        elif mic.on and mic.level >= SPEECH_DBFS and now - speaker_quiet_since >= CHIME_SETTLE:
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


def asks_to_sleep(said: str) -> bool:
    """An explicit request to sleep, and nothing else. Not "thanks", "goodnight", "don't
    go to sleep", "are you going to sleep?" or "remind me to go to sleep at 11"."""
    words = set(re.findall(r"[a-z']+", said.lower().replace("’", "'"))) - FILLER
    return "sleep" in words and words <= SLEEP_COMMAND_WORDS


class SleepCommand:
    """Watches the conversation for "go to sleep" (or a yes after Alfred offers it) and
    then calls go_to_sleep()."""

    def __init__(self, go_to_sleep):
        self._go_to_sleep = go_to_sleep
        self._offered = False

    def alfred_said(self, text: str) -> None:
        self._offered = bool(OFFER.search(text.lower()))

    def user_said(self, text: str) -> None:
        offered, self._offered = self._offered, False
        if asks_to_sleep(text) or (offered and quick_answer(text) == "yes"):
            logger.info(f"Told to go to sleep: {text!r}")
            self._go_to_sleep()
