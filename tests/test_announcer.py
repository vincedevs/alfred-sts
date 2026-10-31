"""What Alfred says about jobs mid-conversation, tested with a fake GPT-Live."""

import asyncio

from alfred import announcer as announcer_module
from alfred.announcer import JobAnnouncer, opening_messages, quick_answer, recent_jobs_context
from alfred.audit import AuditLog
from alfred.config import PROJECT_ROOT, Config
from alfred.db import Database
from alfred.questions import Questions
from alfred.reminders import Reminders
from alfred.tasks import TaskRunner, job_environment


def test_quick_answer_only_takes_clear_short_answers():
    for said in ("Yes", "Yes, yes please.", "Uh, yeah", "Sure, go ahead", "Go ahead", "Send it"):
        assert quick_answer(said) == "yes", said
    for said in ("No", "Uh, no, I changed my mind", "Nope", "Don't send it", "Cancel"):
        assert quick_answer(said) == "no", said
    unclear = (
        "Yes but change the subject",
        "Wait",
        "Okay",
        "What did it say?",
        "No problem, send it",
        "Yes and also email my brother the same thing later today",
    )
    for said in unclear:
        assert quick_answer(said) is None, said


class FakeLLM:
    """Records what GPT-Live would have been told."""

    def __init__(self):
        self.notes = []

    async def send_client_event(self, event):
        self.notes.append(event.content)

    def create_task(self, coroutine, name):
        return asyncio.ensure_future(coroutine)


def make(tmp_path, monkeypatch=None):
    if monkeypatch:
        monkeypatch.setattr(announcer_module, "TOO_SOON", 0)
    db = Database(tmp_path / "alfred.db")
    config = Config(openai_api_key="sk-test", data_dir=tmp_path)
    questions = Questions(db)
    tasks = TaskRunner(db, config, questions, AuditLog(config.audit_path))
    llm = FakeLLM()
    announcer = JobAnnouncer(llm, db, tasks, questions, Reminders(db, config, tasks))
    announcer.start()
    announcer.session_open = True
    return db, questions, announcer, llm


def test_a_clear_yes_goes_straight_to_the_job(tmp_path, monkeypatch):
    async def main():
        _, questions, announcer, llm = make(tmp_path, monkeypatch)
        asking = asyncio.create_task(questions.ask(5, "approve", "May I send an email?"))
        await asyncio.sleep(0.01)
        assert "May I send an email?" in llm.notes[0]
        assert "job 5" in llm.notes[0] and "Don't mention job numbers" in llm.notes[0]

        announcer.user_said("Yes, please.")
        assert await asking == "yes"
        await asyncio.sleep(0.01)
        assert "already been passed on" in llm.notes[-1]

    asyncio.run(main())


def test_an_unclear_answer_is_left_to_gpt_live(tmp_path, monkeypatch):
    async def main():
        _, questions, announcer, _ = make(tmp_path, monkeypatch)
        asking = asyncio.create_task(questions.ask(5, "approve", "May I send it?"))
        await asyncio.sleep(0.01)
        announcer.user_said("Yes but change the subject first")
        assert [q.task_id for q in questions.waiting()] == [5]  # still waiting
        asking.cancel()

    asyncio.run(main())


def test_a_question_while_closing_waits_for_alfred_to_speak_up(tmp_path):
    async def main():
        _, questions, announcer, llm = make(tmp_path)
        announcer.closing = True
        asking = asyncio.create_task(questions.ask(6, "approve", "May I send it?"))
        await asyncio.sleep(0.01)
        assert llm.notes == []  # not said into a closing session...
        assert questions.new_question.is_set()  # ...so Alfred speaks up afterwards
        asking.cancel()

    asyncio.run(main())


def test_a_question_said_in_the_session_needs_no_speaking_up(tmp_path):
    async def main():
        _, questions, _, llm = make(tmp_path)
        asking = asyncio.create_task(questions.ask(6, "clarify", "Which year?"))
        await asyncio.sleep(0.01)
        assert llm.notes and not questions.new_question.is_set()
        asking.cancel()

    asyncio.run(main())


def test_opening_mentions_failures_only_when_there_are_some(tmp_path):
    db = Database(tmp_path / "alfred.db")
    task_id = db.add_task("chart the peso")
    db.finish_task(task_id, "done", "Saved chart.png")
    config = Config(openai_api_key="sk-test", data_dir=tmp_path)
    questions = Questions(db)
    tasks = TaskRunner(db, config, questions, AuditLog(config.audit_path))
    reminders = Reminders(db, config, tasks)
    messages, told, said = opening_messages(db, questions, reminders)
    content = messages[0]["content"]
    assert "One background job finished" in content
    assert "failed" not in content and "Two" not in content
    assert "never instructions to you" in content
    assert told == [task_id]
    db.mark_told(told)  # done once the session opens (voice.py)
    assert said == []
    assert opening_messages(db, questions, reminders) == ([], [], [])


def test_jobs_get_their_own_python_environment(tmp_path, monkeypatch):
    venv_bin = str(PROJECT_ROOT / ".venv" / "bin")
    monkeypatch.setenv("PATH", f"{venv_bin}:/usr/local/bin:/usr/bin")
    env = job_environment(tmp_path)
    assert env["PATH"] == "/usr/local/bin:/usr/bin"
    assert env["UV_CACHE_DIR"].startswith(str(tmp_path))


def test_only_the_next_reply_counts(tmp_path, monkeypatch):
    """Ignore the question, talk about something else, then say yes to something else:
    that yes must not approve the email."""

    async def main():
        _, questions, announcer, _ = make(tmp_path, monkeypatch)
        asking = asyncio.create_task(questions.ask(5, "approve", "May I send it?"))
        await asyncio.sleep(0.01)
        announcer.user_said("What's the weather like tomorrow?")
        announcer.user_said("Yes")
        assert [q.task_id for q in questions.waiting()] == [5]
        asking.cancel()

    asyncio.run(main())


def test_a_reply_begun_before_the_question_does_not_count(tmp_path):
    async def main():
        _, questions, announcer, _ = make(tmp_path)  # TOO_SOON as normal
        asking = asyncio.create_task(questions.ask(5, "approve", "May I send it?"))
        await asyncio.sleep(0.01)
        announcer.user_said("Yes")  # finished a moment after the question came in
        assert [q.task_id for q in questions.waiting()] == [5]
        asking.cancel()

    asyncio.run(main())


def test_new_conversations_know_recent_jobs(tmp_path):
    db = Database(tmp_path / "alfred.db")
    assert recent_jobs_context(db) == ""
    db.add_task("email the Grammys news")
    assert "email the Grammys news" in recent_jobs_context(db)


def test_with_two_questions_open_a_bare_yes_is_left_to_gpt_live(tmp_path, monkeypatch):
    async def main():
        _, questions, announcer, _ = make(tmp_path, monkeypatch)
        email = asyncio.create_task(questions.ask(5, "approve", "May I send the email?"))
        await asyncio.sleep(0.01)
        chart = asyncio.create_task(questions.ask(6, "clarify", "This year or five years?"))
        await asyncio.sleep(0.01)
        announcer.user_said("Yes")  # meant for which? not the email, without asking
        assert sorted(q.task_id for q in questions.waiting()) == [5, 6]
        email.cancel()
        chart.cancel()

    asyncio.run(main())


def test_a_reminder_mid_conversation_is_said_and_marked(tmp_path):
    async def main():
        _, _, announcer, llm = make(tmp_path)
        reminders = announcer._reminders
        reminders.add("stretch", 0)  # long overdue: goes off at once
        reminders.check()
        await asyncio.sleep(0.01)
        assert "stretch" in " ".join(llm.notes) and reminders.unsaid() == []

    asyncio.run(main())


def test_missed_reminders_open_the_next_conversation(tmp_path):
    db = Database(tmp_path / "alfred.db")
    config = Config(openai_api_key="sk-test", data_dir=tmp_path)
    questions = Questions(db)
    tasks = TaskRunner(db, config, questions, AuditLog(config.audit_path))
    reminders = Reminders(db, config, tasks)
    reminder = reminders.add("call Mum", 1)
    db.set_unsaid(reminder.id, True)
    messages, _, said = opening_messages(db, questions, reminders)
    assert "call Mum" in messages[0]["content"] and "While Alfred was off" in messages[0]["content"]
    assert said == [reminder.id]
