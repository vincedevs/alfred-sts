"""When a conversation closes: warning tone first, and staying open while a job is busy."""

import asyncio
from types import SimpleNamespace

from alfred import idle
from alfred.idle import QuietTimer, check_every


class Fake:
    def __init__(self, busy=False, waiting=()):
        self.played, self.frames, self.busy, self._waiting = [], [], busy, list(waiting)
        self.closing = False

    def play(self, sound):
        self.played.append(sound)

    async def queue_frame(self, frame):
        self.frames.append(type(frame).__name__)

    def waiting(self):
        return self._waiting


def make(monkeypatch, **kwargs):
    monkeypatch.setattr(idle, "WARNING_SECONDS", 0.05)
    fake = Fake(**kwargs)
    config = SimpleNamespace(idle_seconds=25.0)
    return fake, QuietTimer(fake, fake, "warning", config, fake, fake, fake)


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
