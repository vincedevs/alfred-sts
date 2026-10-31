"""When a conversation closes: warning tone first, and staying open while a job is busy."""

import asyncio
from types import SimpleNamespace

from alfred import idle
from alfred.idle import QuietTimer, check_every


class Fake:
    def __init__(self, busy=False, waiting=()):
        self.played, self.frames, self.busy, self._waiting = [], [], busy, list(waiting)
        self.closing = False
        # stands in for the engine's microphone check (audio_log.py)
        self.activity = SimpleNamespace(
            mic=SimpleNamespace(on=False), speaker=SimpleNamespace(on=False)
        )

    def play(self, sound):
        self.played.append(sound)

    async def queue_frame(self, frame):
        self.frames.append(type(frame).__name__)

    def waiting(self):
        return self._waiting


def make(monkeypatch, **kwargs):
    monkeypatch.setattr(idle, "WARNING_SECONDS", 0.05)
    monkeypatch.setattr(idle, "TONE_SECONDS", 0.0)
    monkeypatch.setattr(idle, "LISTEN_EVERY", 0.005)
    fake = Fake(**kwargs)

    def on_closing():
        fake.closing = True

    def is_busy():
        return fake.busy or bool(fake.waiting())

    return fake, QuietTimer(fake, fake, "warning", 25.0, is_busy, on_closing)


def test_warns_then_closes(monkeypatch):
    async def main():
        fake, timer = make(monkeypatch)
        await timer.on_idle()
        assert fake.played == ["warning"] and fake.frames == []
        await asyncio.sleep(0.1)
        assert fake.frames == ["EndFrame"] and fake.closing

    asyncio.run(main())


def test_speaking_after_the_warning_keeps_it_open(monkeypatch):
    async def main():
        fake, timer = make(monkeypatch)
        await timer.on_idle()
        timer.activity()
        await asyncio.sleep(0.1)
        assert fake.frames == []

    asyncio.run(main())


def test_stays_open_while_a_job_is_busy(monkeypatch):
    async def main():
        fake, timer = make(monkeypatch, busy=True)
        await timer.on_idle()
        assert fake.played == [] and fake.frames == []

    asyncio.run(main())


def test_warning_comes_before_the_idle_time():
    assert check_every(25.0) == 20.0


def test_a_voice_on_the_microphone_saves_it_once(monkeypatch):
    """You start speaking right at the deadline, before GPT-Live notices: stay open.
    But only once per quiet stretch, so a TV can't keep Alfred open forever."""

    async def main():
        fake, timer = make(monkeypatch)
        await timer.on_idle()
        await asyncio.sleep(0.01)
        fake.activity.mic.on = True  # you start speaking after the tone
        await asyncio.sleep(0.1)
        assert fake.frames == []  # saved by the microphone check
        await timer.on_idle()
        await asyncio.sleep(0.1)
        assert fake.frames == ["EndFrame"]  # still "speaking", but it doesn't count twice

    asyncio.run(main())


def test_the_tone_echoing_on_the_microphone_does_not_count(monkeypatch):
    async def main():
        fake, timer = make(monkeypatch)
        fake.activity.mic.on = True  # already "on" when the warning starts: the tone's echo
        await timer.on_idle()
        await asyncio.sleep(0.1)
        assert fake.frames == ["EndFrame"]

    asyncio.run(main())
