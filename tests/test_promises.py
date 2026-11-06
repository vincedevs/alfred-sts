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
        "Certainly, sir; switching them off now.",
        "Of course. Turning them on now.",
        "Very good. Putting you through.",
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
        "Still on with that, just a moment, sir.",
        "Thank you for waiting.",
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


def test_the_reminder_says_where_an_answer_to_a_job_goes(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(promises_module, "GRACE_SECONDS", 0.02)

    async def main():
        llm = FakeLLM()
        question = SimpleNamespace(task_id=3, text="What email address should I send it to?")
        check = PromiseCheck(llm, waiting=lambda: [question])
        check.alfred_said("Very good. I'll have it sent there.")
        await asyncio.sleep(0.05)
        assert "job 3" in llm.notes[0] and "What email address" in llm.notes[0]

    asyncio.run(main())


def test_a_house_tool_call_counts_as_a_hand_off(monkeypatch):
    """GPT-Live calls the house's tools itself: "it's playing now" right after
    play_music is no empty promise, even when the router was asked long before."""
    monkeypatch.setattr(promises_module, "GRACE_SECONDS", 0.02)

    async def main():
        llm = FakeLLM()
        check = PromiseCheck(llm)
        check.handed_off()  # what Voice._used_tool does after play_music
        check.alfred_said("The lights are dimmed, and it's playing now.")
        await asyncio.sleep(0.05)
        assert llm.notes == []

    asyncio.run(main())
