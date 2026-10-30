"""One spoken conversation with GPT-Live, from wake word to idle timeout.

    microphone -> GPT-Live -> speaker

GPT-Live listens and talks at the same time, so you can interrupt it. When a
question needs fresh facts, GPT-Live hands it to a cheaper text model (the
"router", GPT-6 Luna) with OpenAI's hosted web search and Alfred's job tools
(tools.py). OpenAI runs the hand-off itself ("Responses delegation"); Pipecat
runs the job tools here when the router calls them.

When a background job finishes mid-conversation, Alfred tells you straight away; if it
finished between conversations, Alfred opens the next one by telling you.

The session closes after `idle_seconds` with nobody speaking; GPT-Live bills
for every open second, including silence.
"""

import time

from loguru import logger
from pipecat.adapters.llm.schemas.tools_schema import AdapterType, ToolsSchema
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    EndFrame,
    ErrorFrame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    LLMRunFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.observers.loggers.debug_log_observer import DebugLogObserver
from pipecat.observers.loggers.metrics_log_observer import MetricsLogObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.services.openai.live import events as live_events
from pipecat.services.openai.live.llm import OpenAILiveLLMService
from pipecat.services.openai.responses.llm import OpenAIResponsesLLMService
from pipecat.workers.runner import WorkerRunner

from alfred.audio import SAMPLE_RATE, AudioEngine
from alfred.config import Config, load_prompt
from alfred.db import Database, Task
from alfred.tasks import TaskRunner
from alfred.tools import job_tools
from alfred.transport import EngineTransport

# Pipecat frames worth a line in the debug log: who is talking, transcripts, tools, errors.
LOGGED_FRAMES = (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    TranscriptionFrame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    ErrorFrame,
)

WEB_SEARCH = {"type": "web_search"}  # hosted by OpenAI, runs on their side


async def run_conversation(
    engine: AudioEngine, config: Config, tasks: TaskRunner, db: Database
) -> None:
    """Talk until nobody has spoken for `config.idle_seconds`, then return."""
    transport = EngineTransport(engine)
    llm = create_gpt_live(config)
    # The router's tools: OpenAI's web search plus Alfred's job tools (run here).
    tools = ToolsSchema(
        standard_tools=job_tools(tasks, db), custom_tools={AdapterType.OPENAI: [WEB_SEARCH]}
    )
    context = LLMContext(messages=opening_messages(db), tools=tools)
    user_turns, alfred_turns = LLMContextAggregatorPair(context)
    pipeline = Pipeline([transport.input(), user_turns, llm, transport.output(), alfred_turns])
    worker = create_worker(pipeline, config)

    session_open = False

    @llm.event_handler("on_session_started")
    async def on_session_started(_llm, _session):
        nonlocal session_open
        session_open = True
        logger.info("Listening (GPT-Live session open)")
        transport.mic_input.start_forwarding()

    @worker.event_handler("on_idle_timeout")
    async def on_idle(_worker):
        logger.info(f"No speech for {config.idle_seconds:.0f} s, closing the session")
        await worker.queue_frame(EndFrame())  # lets GPT-Live finish and close cleanly

    def announce_finished_job(task: Task) -> None:
        """A job finished mid-conversation: GPT-Live tells you without being asked."""
        if session_open and task.status != "stopped":
            db.mark_told([task.id])
            note = live_events.SessionCommentaryAppendEvent(
                delegation_id=None, content=finished_job_note(task)
            )
            llm.create_task(llm.send_client_event(note), "announce_job")

    log_conversation(llm, user_turns, alfred_turns)
    tasks.on_finished.append(announce_finished_job)
    await worker.queue_frame(LLMRunFrame())  # opens the GPT-Live session
    pipeline_runner = WorkerRunner(handle_sigint=False)  # Ctrl+C is handled in __main__.py
    await pipeline_runner.add_workers(worker)
    started = time.monotonic()
    try:
        await pipeline_runner.run()  # returns when the session has closed
    finally:
        tasks.on_finished.remove(announce_finished_job)
        minutes = (time.monotonic() - started) / 60
        logger.info(
            f"Session closed after {minutes:.1f} min (about ${minutes * 0.05:.2f} of GPT-Live)"
        )


def finished_job_note(task: Task) -> str:
    # Kept short: GPT-Live takes at most 500 tokens per message.
    return (
        f"Background job {task.id} ({task.request[:150]}) just finished: {task.status}. "
        f"{(task.result or '')[:1200]} "
        "Tell the user now, briefly, using only this; never add details."
    )


def opening_messages(db: Database) -> list[dict]:
    """If jobs finished since the last conversation, Alfred opens by telling you.
    A trailing developer message is how GPT-Live is asked to speak first."""
    untold = db.untold_results()
    db.mark_told([task.id for task in untold])
    finished = [task for task in untold if task.status in ("done", "failed")]  # not "stopped"
    if not finished:
        return []
    lines = "\n".join(f"- Job {t.id} ({t.request}): {t.status}. {t.result}" for t in finished)
    logger.info(f"Opening with {len(finished)} finished job(s)")
    return [
        {
            "role": "developer",
            "content": "Before anything else, briefly tell the user about these finished "
            "background jobs. Report only what is written here, never add details; "
            f"if a job failed, say so plainly:\n{lines}",
        }
    ]


def create_gpt_live(config: Config) -> OpenAILiveLLMService:
    """GPT-Live, handing look-ups to the router model (OpenAI runs the hand-off)."""
    logger.debug(
        f"Opening GPT-Live session: live model {config.live_model}, "
        f"router {config.router_model}, voice {config.voice or 'default'}"
    )
    return OpenAILiveLLMService(
        api_key=config.openai_api_key,
        settings=OpenAILiveLLMService.Settings(
            model=config.live_model,
            system_instruction=load_prompt("voice"),
            voice=config.voice,
        ),
        delegation=OpenAILiveLLMService.ResponsesDelegation(
            settings=OpenAIResponsesLLMService.Settings(
                model=config.router_model,
                system_instruction=load_prompt("router"),
                reasoning=OpenAIResponsesLLMService.ReasoningConfig(effort="low"),
            ),
        ),
    )


def create_worker(pipeline: Pipeline, config: Config) -> PipelineWorker:
    return PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=SAMPLE_RATE,
            audio_out_sample_rate=SAMPLE_RATE,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=config.idle_seconds,
        cancel_on_idle_timeout=False,  # run_conversation closes politely instead
        # If GPT-Live's connection fails, end at once and go back to the wake word
        # instead of sitting silent until the idle timeout.
        processor_unusable_policy=ProcessorUnusablePolicy.END,
        observers=[DebugLogObserver(frame_types=LOGGED_FRAMES), MetricsLogObserver()],
    )


def log_conversation(llm, user_turns, alfred_turns) -> None:
    """Show what was said, and when the router looks something up."""

    @llm.event_handler("on_delegation_created")
    async def on_delegation_created(_llm, delegation):
        logger.info(f"Router is looking something up ({delegation.id})")

    @user_turns.event_handler("on_user_turn_message_added")
    async def on_user_turn(_aggregator, message):
        logger.info(f"You: {message.content}")

    @alfred_turns.event_handler("on_assistant_turn_stopped")
    async def on_alfred_turn(_aggregator, message):
        if message.content:
            logger.info(f"Alfred: {message.content}")
