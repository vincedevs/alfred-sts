"""Alfred's long-lived parts, built once at startup (Services.start) and shared by every
conversation: settings, the database, background jobs, their questions, memory and
reminders."""

from dataclasses import dataclass

from loguru import logger

from alfred.audit import AuditLog
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

    @classmethod
    def start(cls, config: Config, on_job_finished) -> "Services":
        """Open the database, resume unfinished jobs and catch up on missed reminders."""
        config.workspace_dir.mkdir(parents=True, exist_ok=True)
        db = Database(config.database_path)
        questions = Questions(db)
        memory = Memory(db, config)
        tasks = TaskRunner(
            db,
            config,
            questions,
            AuditLog(config.audit_path),
            on_finished=on_job_finished,
            # jobs know where you are and what Alfred knows about you
            about_user=lambda: config.home_text() + memory.profile_text(),
        )
        if resumed := tasks.resume_unfinished():
            logger.info(f"Resumed {resumed} unfinished job(s)")
        reminders = Reminders(db, config, tasks)
        reminders.catch_up()
        return cls(config, db, tasks, questions, memory, reminders)

    def has_news(self) -> bool:
        """Is there anything Alfred should speak up about?"""
        return bool(self.db.untold_results() or self.questions.waiting() or self.reminders.unsaid())
