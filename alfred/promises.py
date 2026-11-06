"""A safety net for "I'll put that on" (or "the lights are blue now") with nothing
happening.

GPT-Live is told never to say it will do something, or that it's done, without handing
it to its backend (prompts/voice.md). Now and then it does anyway: it said "I'll put on a
Laufey track" and "the living room lights are blue now" without a single tool call.
When Alfred promises or claims an action and nothing reached his backend recently (nor
within GRACE_SECONDS after), GPT-Live is reminded quietly to hand it off now. News that
Alfred was given to pass on (a job's result, a reminder) counts as his backend speaking.
"""

import asyncio
import re
import time

from loguru import logger
from pipecat.services.openai.live import events as live_events

GRACE_SECONDS = 3.0  # a hand-off usually starts within a second of the promise
RECENT_SECONDS = 15.0  # a hand-off this recent covers the promise ("Certainly, I'll check")
PROMISE = re.compile(
    # "I'll put…", "let me check…", "I'm going to…", but not "I'll be here", "I'll let you know"
    r"\b(i['’]ll|i will|let me|i['’]m going to)\s+"
    r"(?!be\b|wait\b|stay\b|leave\b|let you\b|bear\b|keep quiet\b)\w+"
    # "I've turned…", "they're blue now", "it's now playing", "that's done"
    r"|\bi['’]ve\s+(?!been\b|got\b|no\b|never\b|heard\b)\w+"
    r"|\b(is|are|['’]re|['’]s)\s+(now\s+\w+|\w+\s+now)\b"
    r"|\b(that['’]s|it['’]s|all)\s+(done|set|sorted|sent|stopped|cancelled|canceled)\b"
    # "switching them off now", "turning them on now", "putting you through"
    r"|\b(switching|turning|putting|playing|setting|sending|starting|stopping|changing|"
    r"dimming|pausing|skipping|ringing|calling|cancelling|canceling|adding)\b"
    r"[^.?!]{0,40}?\b(now|through|on|off|up|down)\b",
    re.IGNORECASE,
)


def is_promise(text: str) -> bool:
    return bool(PROMISE.search(text))


class PromiseCheck:
    def __init__(self, llm, waiting=lambda: []):
        """waiting(): the questions jobs are waiting on (questions.py), so the reminder
        can say where an answer the user just gave should go."""
        self._llm, self._waiting = llm, waiting
        self._handed_off_at = -1e9  # when GPT-Live last handed something to its backend
        self._reminded_at = -1e9

    def handed_off(self) -> None:
        """GPT-Live handed something to its backend, or was given news to pass on."""
        self._handed_off_at = time.monotonic()

    def alfred_said(self, text: str) -> None:
        if is_promise(text) and not self._handed_off_recently(time.monotonic()):
            self._llm.create_task(self._check(text), "promise-check")

    def _handed_off_recently(self, moment: float) -> bool:
        return moment - self._handed_off_at < RECENT_SECONDS

    async def _check(self, text: str) -> None:
        said_at = time.monotonic()
        await asyncio.sleep(GRACE_SECONDS)
        if self._handed_off_at > said_at - RECENT_SECONDS:
            return  # it did hand it off
        if time.monotonic() - self._reminded_at < RECENT_SECONDS:
            return  # reminded just now: once is enough
        self._reminded_at = time.monotonic()
        logger.warning(f"Alfred promised without handing off: {text[:80]!r}. Reminding him.")
        note = (
            f'You told the user "{text[:120]}", but you haven\'t handed it to your backend, '
            "so nothing has happened. Hand it to your backend now. Don't apologise or "
            "explain. If it's already done (a tool result or your backend confirmed it), "
            "say nothing at all."
        )
        if waiting := self._waiting():
            question = waiting[0]
            note += (
                f' A background job is waiting for the user\'s answer to: "{question.text}". '
                "If what the user said answers it, hand their exact answer to your backend "
                f"for job {question.task_id}."
            )
        event = live_events.SessionCommentaryAppendEvent(delegation_id=None, content=note)
        await self._llm.send_client_event(event)
