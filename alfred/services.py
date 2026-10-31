"""Alfred's long-lived parts, created once at startup (__main__.py) and shared by every
conversation: settings, the database, background jobs, their questions, memory and
reminders."""

from dataclasses import dataclass

from alfred.config import Config
from alfred.db import Database
from alfred.memory import Memory
from alfred.questions import Questions
from alfred.reminders import Reminders
from alfred.tasks import TaskRunner


@dataclass
class Services:
    config: Config
    db: Database
    tasks: TaskRunner
    questions: Questions
    memory: Memory
    reminders: Reminders

    def has_news(self) -> bool:
        """Is there anything Alfred should speak up about?"""
        return bool(self.db.untold_results() or self.questions.waiting() or self.reminders.unsaid())
