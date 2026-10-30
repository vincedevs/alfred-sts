"""Background jobs: Alfred hands a request to Claude and keeps talking.

Each job runs Claude through the Claude Agent SDK as its own asyncio task. Claude
works on its own: it searches, reads pages and writes notes until it has an answer.
Every job is recorded in the database, so after a restart unfinished jobs carry on
from where they were (the SDK can resume a Claude session by its ID).

For now Claude may only search the web, read web pages, and read and write files in
Alfred's workspace folder. Shell commands wait for Day 3's sandbox and approvals.
"""

import asyncio
from collections.abc import Awaitable, Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    ToolUseBlock,
    query,
)
from loguru import logger

from alfred.config import Config, load_prompt
from alfred.db import Database, Task

AGENT_TOOLS = ["WebSearch", "WebFetch", "Read", "Write", "Edit", "Glob", "Grep"]
MAX_TURNS = 40  # a safety stop for a job that goes round in circles
RESUME_PROMPT = (
    "Alfred restarted while you were working on this. Carry on from where you were "
    "and give your final answer."
)

# run_agent(task_id, request, session_id) -> the answer. Tests pass a fake one.
AgentRunner = Callable[[int, str, str | None], Awaitable[str]]


class TaskRunner:
    def __init__(
        self,
        db: Database,
        config: Config,
        on_finished: Callable[[Task], None] | None = None,
        run_agent: AgentRunner | None = None,
    ):
        self._db = db
        self._config = config
        # Called with each job that finishes: the chime, and the live announcement while
        # a conversation is open (voice.py adds and removes that one).
        self.on_finished: list[Callable[[Task], None]] = [on_finished] if on_finished else []
        self._run_agent = run_agent or self._run_claude
        self._jobs: dict[int, asyncio.Task] = {}
        self._waiting: set[int] = set()  # jobs someone is waiting on (see wait)
        self._closing = False

    def start(self, request: str) -> int:
        task_id = self._db.add_task(request)
        logger.info(f"Task {task_id} started: {request}")
        self._launch(task_id, request, session_id=None)
        return task_id

    def resume_unfinished(self) -> int:
        """Restart jobs that were still running when Alfred last stopped."""
        unfinished = self._db.running_tasks()
        for task in unfinished:
            logger.info(f"Task {task.id} resumed after restart: {task.request}")
            self._launch(task.id, task.request, task.session_id)
        return len(unfinished)

    async def wait(self, task_id: int, timeout: float) -> Task | None:
        """Wait up to `timeout` seconds for a job, then return its record either way.
        A job that finishes while someone waits for it skips the "finished" callback:
        its result is being handed over directly."""
        job = self._jobs.get(task_id)
        if job:
            self._waiting.add(task_id)
            try:
                await asyncio.wait([job], timeout=timeout)
            finally:
                self._waiting.discard(task_id)
        return self._db.get_task(task_id)

    async def stop(self, task_id: int) -> bool:
        job = self._jobs.get(task_id)
        if not job:
            return False
        job.cancel()
        await asyncio.wait([job])
        return True

    def begin_shutdown(self) -> None:
        """Call the moment shutdown starts. Ctrl+C also reaches Claude's own process, so a
        job may end with an error before close() runs; from now on that isn't a failure."""
        self._closing = True

    async def close(self) -> None:
        """Shutting down: interrupt jobs but leave them 'running' so they resume next time."""
        self._closing = True
        for job in self._jobs.values():
            job.cancel()
        if self._jobs:
            await asyncio.wait(self._jobs.values())

    def _launch(self, task_id: int, request: str, session_id: str | None) -> None:
        self._jobs[task_id] = asyncio.create_task(
            self._run(task_id, request, session_id), name=f"task-{task_id}"
        )

    async def _run(self, task_id: int, request: str, session_id: str | None) -> None:
        try:
            status, result = "done", await self._run_agent(task_id, request, session_id)
        except asyncio.CancelledError:
            if self._closing:
                raise  # not stopped by you: leave it to resume
            status, result = "stopped", "Stopped at your request."
        except Exception as error:
            if self._closing:
                logger.info(f"Task {task_id} interrupted by shutdown; it resumes next start")
                return
            logger.exception(f"Task {task_id} failed")
            status, result = "failed", f"{type(error).__name__}: {error}"
        finally:
            self._jobs.pop(task_id, None)

        self._db.finish_task(task_id, status, result)
        logger.info(f"Task {task_id} {status}: {result[:200]}")
        if task_id not in self._waiting:
            task = self._db.get_task(task_id)
            for listener in list(self.on_finished):
                listener(task)

    async def _run_claude(self, task_id: int, request: str, session_id: str | None) -> str:
        options = ClaudeAgentOptions(
            model=self._config.agent_model,
            system_prompt=load_prompt("agent"),
            tools=AGENT_TOOLS,  # the only tools Claude can see
            allowed_tools=AGENT_TOOLS,  # ...and they run without asking
            permission_mode="dontAsk",  # anything else is refused, never prompted
            cwd=self._config.workspace_dir,
            max_budget_usd=self._config.task_budget_usd,
            max_turns=MAX_TURNS,
            setting_sources=[],  # ignore your personal Claude Code settings
            resume=session_id,
        )
        prompt = RESUME_PROMPT if session_id else request
        outcome: ResultMessage | None = None

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, SystemMessage) and message.subtype == "init":
                self._db.set_session(task_id, message.data["session_id"])
            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        logger.debug(f"Task {task_id} uses {block.name}: {str(block.input)[:200]}")
            elif isinstance(message, ResultMessage):
                outcome = message

        if outcome is None:
            raise RuntimeError("Claude stopped without a result")
        logger.info(
            f"Task {task_id}: {outcome.num_turns} turns, {outcome.duration_ms / 1000:.0f} s, "
            f"about ${outcome.total_cost_usd or 0:.3f}"
        )
        if outcome.is_error:
            raise RuntimeError(f"{outcome.subtype}: {outcome.errors or outcome.result}")
        return outcome.result or "Done, but Claude gave no answer."
