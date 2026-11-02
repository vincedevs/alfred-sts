"""Greeting after "Hey Alfred" alone, and the go_to_sleep tool."""

import asyncio
from types import SimpleNamespace

from alfred import greeting
from alfred.greeting import GREETING, greet_unless_asked, kept_talking, sleep_tools


def quick(monkeypatch):
    monkeypatch.setattr(greeting, "SKIP_SECONDS", 0.01)
    monkeypatch.setattr(greeting, "LISTEN_SECONDS", 0.1)
    monkeypatch.setattr(greeting, "LISTEN_EVERY", 0.005)


def sound(mic=False, speaker=False):
    return SimpleNamespace(mic=SimpleNamespace(on=mic), speaker=SimpleNamespace(on=speaker))


def test_silence_after_the_wake_word_means_no_request(monkeypatch):
    quick(monkeypatch)
    assert asyncio.run(kept_talking(sound())) is False


def test_speech_after_the_wake_word_is_a_request(monkeypatch):
    quick(monkeypatch)
    activity = sound()

    async def main():
        check = asyncio.create_task(kept_talking(activity))
        await asyncio.sleep(0.03)
        activity.mic.on = True  # "...what time is it?"
        return await check

    assert asyncio.run(main()) is True


def test_the_wake_chime_is_not_the_user(monkeypatch):
    quick(monkeypatch)
    assert asyncio.run(kept_talking(sound(mic=True, speaker=True))) is False


def test_greets_only_when_nothing_followed(monkeypatch):
    said = []

    async def main(followed):
        async def check():
            return followed

        await greet_unless_asked(asyncio.create_task(check()), said.append)

    asyncio.run(main(followed=True))
    assert said == []
    asyncio.run(main(followed=False))
    assert said == [GREETING]


class Params:
    async def result_callback(self, result):
        self.result = result


def test_go_to_sleep_closes_after_goodbye_and_mentions_waiting_questions():
    calls = []
    questions = SimpleNamespace(waiting=lambda: ["send the email?"])
    (go_to_sleep,) = sleep_tools(lambda: calls.append("sleep"), questions)
    params = Params()
    asyncio.run(go_to_sleep(params))
    assert calls == ["sleep"]
    assert params.result["status"] == "going to sleep"
    assert "1 question(s)" in params.result["note"]

    questions.waiting = lambda: []
    asyncio.run(go_to_sleep(params))
    assert "question" not in params.result["note"]
    assert "goodnight" in params.result["note"]
