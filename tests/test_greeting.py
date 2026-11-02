"""Greeting after "Hey Alfred" alone, and the go_to_sleep tool."""

import asyncio
from types import SimpleNamespace

from alfred import greeting
from alfred.greeting import GREETING, SleepCommand, asks_to_sleep, greet_unless_asked, kept_talking


def quick(monkeypatch):
    monkeypatch.setattr(greeting, "SKIP_SECONDS", 0.01)
    monkeypatch.setattr(greeting, "LISTEN_SECONDS", 0.15)
    monkeypatch.setattr(greeting, "CHIME_SETTLE", 0.05)
    monkeypatch.setattr(greeting, "LISTEN_EVERY", 0.005)


def sound(mic=False, speaker=False, level=-35.0):
    return SimpleNamespace(
        mic=SimpleNamespace(on=mic, level=level), speaker=SimpleNamespace(on=speaker)
    )


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


def test_the_chimes_echo_just_after_it_ends_is_not_the_user(monkeypatch):
    """Seen on the Mac: the mic still showed the chime's echo for a moment after it ended."""
    quick(monkeypatch)
    activity = sound(mic=True, speaker=True)

    async def main():
        check = asyncio.create_task(kept_talking(activity))
        await asyncio.sleep(0.03)
        activity.speaker.on = False  # chime over; its echo lingers briefly
        await asyncio.sleep(0.02)
        activity.mic.on = False
        return await check

    assert asyncio.run(main()) is False


def test_a_faint_echo_after_the_chime_is_not_the_user(monkeypatch):
    """Seen on the Mac: -58 dBFS on the mic for 0.5 s after the chime."""
    quick(monkeypatch)
    activity = sound(mic=True, speaker=True, level=-58.0)

    async def main():
        check = asyncio.create_task(kept_talking(activity))
        await asyncio.sleep(0.03)
        activity.speaker.on = False
        return await check

    assert asyncio.run(main()) is False


def test_still_talking_after_the_chime_is_a_request(monkeypatch):
    quick(monkeypatch)
    activity = sound(mic=True, speaker=True)

    async def main():
        check = asyncio.create_task(kept_talking(activity))
        await asyncio.sleep(0.03)
        activity.speaker.on = False  # "Hey Alfred, what time is it?" goes on past it
        return await check

    assert asyncio.run(main()) is True


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


def test_explicit_requests_to_sleep():
    for said in (
        "Go to sleep, please",
        "Alfred, sleep.",
        "You can sleep now",
        "Time to sleep, Alfred",
        "Go back to sleep",
        "I told you to sleep",
        "Sleep right now",  # seen in testing: GPT-Live said goodnight, Alfred stayed awake
        "I said go to sleep",
        "Okay Alfred, you can go to sleep now, sir",
    ):
        assert asks_to_sleep(said), said


def test_not_requests_to_sleep():
    for said in (
        "Thanks",
        "That's all",
        "Goodnight",
        "Bye",
        "Never mind",
        "Don't go to sleep yet",
        "Are you going to sleep?",
        "I couldn't sleep last night",
        "Remind me to go to sleep at 11",  # seen in testing: Alfred went to sleep
        "What time should I go to sleep?",
        "Set an alarm so I go to sleep on time",
    ):
        assert not asks_to_sleep(said), said


def test_sleep_command_and_a_yes_to_the_offer():
    calls = []
    sleep = SleepCommand(lambda: calls.append("sleep"))
    sleep.user_said("I think I'm done for today")
    assert calls == []
    sleep.alfred_said("Certainly. Shall I go to sleep?")
    sleep.user_said("Yes, please")
    assert calls == ["sleep"]
    sleep.user_said("Yes")  # only the reply right after the offer counts
    assert calls == ["sleep"]
    sleep.user_said("Go to sleep")
    assert calls == ["sleep", "sleep"]
