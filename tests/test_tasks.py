"""Background jobs, tested with a fake agent: no Claude, no cost."""

import asyncio

from alfred.config import Config
from alfred.db import Database
from alfred.tasks import TaskRunner
from alfred.tools import job_tools


def make(tmp_path, agent, finished=None):
    db = Database(tmp_path / "alfred.db")
    config = Config(openai_api_key="sk-test", data_dir=tmp_path)
    on_finished = finished.append if finished is not None else None
    return db, TaskRunner(db, config, on_finished=on_finished, run_agent=agent)


async def quick_agent(task_id, request, session_id):
    return f"answer to: {request}"


async def slow_agent(task_id, request, session_id):
    await asyncio.sleep(60)
    return "too late"


async def broken_agent(task_id, request, session_id):
    raise RuntimeError("no network")


def test_job_finishes_and_calls_back(tmp_path):
    async def main():
        finished = []
        db, runner = make(tmp_path, quick_agent, finished)
        task_id = runner.start("find a keyboard")
        await asyncio.sleep(0.05)
        task = db.get_task(task_id)
        assert (task.status, task.result) == ("done", "answer to: find a keyboard")
        assert [t.id for t in finished] == [task_id]  # the chime would play
        assert [t.id for t in db.untold_results()] == [task_id]  # and Alfred tells you next time

    asyncio.run(main())


def test_waiting_for_a_quick_job_skips_the_chime(tmp_path):
    async def main():
        finished = []
        db, runner = make(tmp_path, quick_agent, finished)
        task = await runner.wait(runner.start("quick one"), timeout=5)
        assert task.status == "done"
        assert finished == []  # answered directly, so no chime

    asyncio.run(main())


def test_stop_marks_job_stopped(tmp_path):
    async def main():
        db, runner = make(tmp_path, slow_agent)
        task_id = runner.start("long research")
        await asyncio.sleep(0.05)
        assert await runner.stop(task_id)
        assert db.get_task(task_id).status == "stopped"
        assert not await runner.stop(task_id)  # nothing left to stop

    asyncio.run(main())


def test_failure_is_recorded(tmp_path):
    async def main():
        db, runner = make(tmp_path, broken_agent)
        task = await runner.wait(runner.start("anything"), timeout=5)
        assert task.status == "failed"
        assert "no network" in task.result

    asyncio.run(main())


def test_shutdown_leaves_jobs_to_resume(tmp_path):
    async def main():
        db, runner = make(tmp_path, slow_agent)
        task_id = runner.start("long research")
        await asyncio.sleep(0.05)
        db.set_session(task_id, "session-123")
        await runner.close()
        assert db.get_task(task_id).status == "running"  # not "stopped": you didn't ask

        resumed_with = []

        async def resuming_agent(task_id, request, session_id):
            resumed_with.append(session_id)
            return "finished after restart"

        _, new_runner = make(tmp_path, resuming_agent)
        assert new_runner.resume_unfinished() == 1
        await asyncio.sleep(0.05)
        assert resumed_with == ["session-123"]
        assert db.get_task(task_id).result == "finished after restart"

    asyncio.run(main())


class FakeParams:
    """Stands in for Pipecat's FunctionCallParams: just records the result."""

    def __init__(self):
        self.result = None

    async def result_callback(self, result):
        self.result = result


def test_tools_start_check_and_stop(tmp_path):
    async def main():
        db, runner = make(tmp_path, quick_agent)
        do_task, task_status, stop_task = job_tools(runner, db)

        params = FakeParams()
        await do_task(params, request="weather tomorrow")
        assert params.result["status"] == "done"
        assert db.untold_results() == []  # answered now, so not repeated later

        await task_status(params, task_id=0)
        assert params.result["jobs"][0]["request"] == "weather tomorrow"

        await stop_task(params, task_id=99)
        assert params.result == {"task_id": 99, "stopped": False}

    asyncio.run(main())


def test_error_during_shutdown_is_not_a_failure(tmp_path):
    """Ctrl+C also hits Claude's process, which then ends with an error. The job must resume."""

    async def main():
        interrupted = asyncio.Event()

        async def interrupted_agent(task_id, request, session_id):
            await interrupted.wait()
            raise RuntimeError("error_during_execution")  # what Claude reports after Ctrl+C

        db, runner = make(tmp_path, interrupted_agent)
        task_id = runner.start("long research")
        runner.begin_shutdown()
        interrupted.set()
        await asyncio.sleep(0.05)
        assert db.get_task(task_id).status == "running"

    asyncio.run(main())


def test_stopped_job_is_not_reported_again(tmp_path):
    async def main():
        db, runner = make(tmp_path, slow_agent)
        _, _, stop_task = job_tools(runner, db)
        task_id = runner.start("long research")
        await asyncio.sleep(0.05)
        await stop_task(FakeParams(), task_id=task_id)
        assert db.untold_results() == []

    asyncio.run(main())


def test_every_listener_hears_about_a_finished_job(tmp_path):
    async def main():
        chimes, announcements = [], []
        db, runner = make(tmp_path, quick_agent, chimes)
        runner.on_finished.append(announcements.append)  # what voice.py adds mid-conversation
        task_id = runner.start("anything")
        await asyncio.sleep(0.05)
        assert [t.id for t in chimes] == [task_id]
        assert [t.id for t in announcements] == [task_id]

    asyncio.run(main())
