"""The safety net for "I'll do that" with no hand-off (fake GPT-Live, no network)."""

import asyncio

from alfred import promises as promises_module
from alfred.promises import PromiseCheck, is_promise


def test_promises_and_claims_are_recognised():
    said = (
        "Very good, sir. I'll put on a Laufey track.",
        "Certainly, sir. The living room lights are blue now.",
        "Let me check that for you.",
        "I’ve set a timer for ten minutes.",  # curly apostrophe, as GPT-Live writes it
        "All sorted.",
        "That's done.",
    )
    for text in said:
        assert is_promise(text), text
    harmless = (
        "I'll be here if you need me.",
        "I'll let you know when it's ready.",
        "Still sorting it, if you'll bear with me.",
        "It's 3:17 p.m., sir.",
        "Why did the ghost go into the bar? For the boos, sir.",
        "Thirty seconds are up, sir.",
        "Not in the way people do.",
    )
    for text in harmless:
        assert not is_promise(text), text


class FakeLLM:
    def __init__(self):
        self.notes = []

    def create_task(self, coroutine, name):
        return asyncio.ensure_future(coroutine)

    async def send_client_event(self, event):
        self.notes.append(event.content)


def test_a_promise_without_a_hand_off_gets_a_reminder(monkeypatch):
    monkeypatch.setattr(promises_module, "GRACE_SECONDS", 0.02)

    async def main():
        llm = FakeLLM()
        check = PromiseCheck(llm)
        check.alfred_said("I'll put on a Laufey track.")
        await asyncio.sleep(0.05)
        assert len(llm.notes) == 1 and "hand it to your backend now" in llm.notes[0].lower()

        check.alfred_said("I'll put it on now.")  # reminded a moment ago: once is enough
        await asyncio.sleep(0.05)
        assert len(llm.notes) == 1

    asyncio.run(main())


def test_a_hand_off_before_or_after_is_fine(monkeypatch):
    monkeypatch.setattr(promises_module, "GRACE_SECONDS", 0.02)

    async def main():
        llm = FakeLLM()
        check = PromiseCheck(llm)
        check.alfred_said("Let me check the weather.")
        check.handed_off()  # the hand-off follows a moment later
        await asyncio.sleep(0.05)
        check.alfred_said("I've turned the lights blue.")  # right after a hand-off
        await asyncio.sleep(0.05)
        assert llm.notes == []

    asyncio.run(main())
