"""Reminders: Alfred speaks up when one is due, without waiting for "Hey Alfred".

A reminder either says something ("stretch") or starts a background job ("brief me on the
weather"), once or on repeat (daily, weekdays, weekly). They're stored in the database,
so they survive restarts.

- Reminders you set go off on time, even during quiet hours: you chose the time.
- A reminder that starts a job runs it quietly at night; you hear the result next time.
- Missed while Alfred was off: one-off reminders from the last MISSED_WINDOW are said
  when he starts; older ones are kept as "missed". Repeating ones just move on.
"""

import asyncio
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from loguru import logger

from alfred.config import Config
from alfred.db import Database, Reminder, Task
from alfred.tasks import TaskRunner

CHECK_EVERY = 5  # seconds between looks at the clock
MISSED_WINDOW = 12 * 60 * 60  # missed one-off reminders newer than this are still said
REPEATS = ("none", "daily", "weekdays", "weekly")


def next_time(due: datetime, repeat: str) -> datetime:
    if repeat == "weekly":
        return due + timedelta(days=7)
    due += timedelta(days=1)
    while repeat == "weekdays" and due.weekday() >= 5:  # skip Saturday and Sunday
        due += timedelta(days=1)
    return due


def spoken_time(when: float) -> str:
    """'3:05 PM today', '7:00 AM tomorrow' or '9:00 AM on Monday 2 November'."""
    moment, today = datetime.fromtimestamp(when), datetime.now().date()
    clock = moment.strftime("%I:%M %p").lstrip("0")
    if moment.date() == today:
        return f"{clock} today"
    if moment.date() == today + timedelta(days=1):
        return f"{clock} tomorrow"
    return f"{clock} on {moment:%A} {moment.day} {moment:%B}"


class Reminders:
    def __init__(self, db: Database, config: Config, tasks: TaskRunner, now=time.time):
        self._db, self._config, self._tasks, self._now = db, config, tasks, now
        self._briefings: set[int] = set()  # jobs started by reminders: speak up when done
        self.on_due: list[Callable[[Reminder], None]] = []  # Alfred says it mid-conversation
        self.wake = asyncio.Event()  # __main__.py wakes Alfred up with this
        tasks.on_finished.append(self._job_finished)

    def add(self, text: str, due_at: float, repeat: str = "none", run_job: bool = False):
        if repeat not in REPEATS:
            raise ValueError(f"repeat must be one of {', '.join(REPEATS)}")
        reminder = self._db.add_reminder(text, due_at, repeat, run_job)
        logger.info(f"Reminder {reminder.id} set for {spoken_time(due_at)}: {text} ({repeat})")
        return reminder

    def upcoming(self) -> list[Reminder]:
        return self._db.reminders_with_status("waiting")

    def cancel(self, reminder_id: int) -> bool:
        reminder = self._db.get_reminder(reminder_id)
        if not reminder or reminder.status != "waiting":
            return False
        self._db.update_reminder(reminder_id, "cancelled")
        return True

    def unsaid(self) -> list[Reminder]:
        """Reminders that went off but haven't been said yet (for the next conversation)."""
        return self._db.unsaid_reminders()

    def mark_said(self, reminder_ids: list[int]) -> None:
        for reminder_id in reminder_ids:
            self._db.set_unsaid(reminder_id, False)

    def catch_up(self) -> None:
        """At startup: deal with reminders that came due while Alfred was off."""
        now = self._now()
        for reminder in self.upcoming():
            if reminder.due_at > now:
                continue
            if reminder.repeat != "none":
                self._move_on(reminder, now)  # repeating ones aren't replayed
            elif reminder.run_job or now - reminder.due_at > MISSED_WINDOW:
                self._db.update_reminder(reminder.id, "missed")  # kept, not said
            else:
                self._db.update_reminder(reminder.id, "done")
                self._db.set_unsaid(reminder.id, True)  # "while I was off, ..."
                self.wake.set()
        if missed := self.unsaid():
            logger.info(f"{len(missed)} reminder(s) came due while Alfred was off")

    async def run(self) -> None:
        """Runs for as long as Alfred does, setting off reminders as they come due."""
        while True:
            try:
                self.check()
            except Exception:  # keep reminders running whatever happens to one of them
                logger.exception("Checking reminders failed")
            await asyncio.sleep(CHECK_EVERY)

    def check(self) -> None:
        now = self._now()
        for reminder in self.upcoming():
            if reminder.due_at <= now:
                self._go_off(reminder, now)

    def _go_off(self, reminder: Reminder, now: float) -> None:
        logger.info(f"Reminder {reminder.id} is due: {reminder.text}")
        if reminder.run_job:
            task_id = self._tasks.start(reminder.text)
            self._briefings.add(task_id)
        else:
            self._db.set_unsaid(reminder.id, True)
            self.wake.set()
        if reminder.repeat != "none":
            self._move_on(reminder, now)
        else:
            self._db.update_reminder(reminder.id, "done")
        if not reminder.run_job:
            for listener in list(self.on_due):
                listener(self._db.get_reminder(reminder.id))

    def _move_on(self, reminder: Reminder, now: float) -> None:
        """A repeating reminder: on to its next time in the future (missed ones skipped)."""
        due = datetime.fromtimestamp(reminder.due_at)
        while due.timestamp() <= now:
            due = next_time(due, reminder.repeat)
        self._db.update_reminder(reminder.id, "waiting", due.timestamp())

    def _job_finished(self, task: Task) -> None:
        if task.id in self._briefings:
            self._briefings.discard(task.id)
            if not self._config.is_quiet():
                self.wake.set()  # say the result now (at night: next conversation)
