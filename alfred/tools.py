"""What the router (GPT-6 Luna) can do besides web search: start, check, answer and
stop background jobs.

Each tool is a plain async function. Pipecat reads its name, docstring and arguments
to describe it to the model, and runs it here when the model calls it.
"""

from pipecat.services.llm_service import FunctionCallParams

from alfred.db import Database, Task
from alfred.questions import Questions
from alfred.tasks import TaskRunner

QUICK_ANSWER_SECONDS = 12  # a job done within this is answered straight away


def job_tools(runner: TaskRunner, db: Database, questions: Questions) -> list:
    async def do_task(params: FunctionCallParams, request: str):
        """Hand a job to Alfred's background worker, which can research the web, read pages,
        write notes, write and run code, and send email (after the user approves). Use it for
        anything that needs several steps or more than a quick search. Quick jobs return the
        answer; longer ones keep running, and Alfred announces the result when they finish.

        Args:
            request: The job in full, with every detail and preference the user gave.
        """
        task_id = runner.start(request)
        task = await runner.wait(task_id, QUICK_ANSWER_SECONDS)
        if task.status == "running":
            await params.result_callback(
                {
                    "task_id": task_id,
                    "status": "running",
                    "note": "Still working. Tell the user in a few words that you're on "
                    "it; the result is announced when it's ready.",
                }
            )
        else:
            db.mark_told([task_id])
            await params.result_callback(_describe(task))

    async def task_status(params: FunctionCallParams, task_id: int = 0):
        """Check on background jobs: whether they are still running, and their results.

        Args:
            task_id: The job to check, or 0 for the most recent jobs.
        """
        tasks = [db.get_task(task_id)] if task_id else db.recent_tasks(3)
        tasks = [task for task in tasks if task]
        db.mark_told([task.id for task in tasks if task.status != "running"])
        waiting = [{"task_id": q.task_id, "question": q.text} for q in questions.waiting()]
        await params.result_callback(
            {"jobs": [_describe(task) for task in tasks], "questions_for_user": waiting}
        )

    async def answer_job(params: FunctionCallParams, task_id: int, answer: str):
        """Pass the user's answer to a question a background job asked them.

        Args:
            task_id: The job that asked.
            answer: For a yes-or-no question, exactly "yes" (only if the user clearly said
                yes) or "no". Otherwise the user's answer in their own words.
        """
        question = questions.answer(task_id, answer)
        if question is None:
            if questions.answered_recently(task_id):  # Alfred passed it on (announcer.py)
                note = "Already passed on. Say nothing more about it unless asked."
            else:
                note = (
                    "This job has no question waiting, so nothing was passed on. Check "
                    "task_status and tell the user exactly what it says."
                )
            await params.result_callback({"task_id": task_id, "note": note})
        else:
            note = "Passed on. Acknowledge in a word or two; the outcome is announced later."
            await params.result_callback({"task_id": task_id, "passed_on": answer, "note": note})

    async def stop_task(params: FunctionCallParams, task_id: int):
        """Stop a background job that is still running.

        Args:
            task_id: The job to stop.
        """
        stopped = await runner.stop(task_id)
        db.mark_told([task_id])  # the user knows: no need to report it later
        await params.result_callback({"task_id": task_id, "stopped": stopped})

    return [do_task, task_status, answer_job, stop_task]


def _describe(task: Task) -> dict:
    return {
        "task_id": task.id,
        "request": task.request,
        "status": task.status,
        "result": task.result,
    }
