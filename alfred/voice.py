"""One spoken conversation with GPT-Live, from wake word to idle timeout.

    microphone -> GPT-Live -> speaker

GPT-Live listens and talks at the same time, so you can interrupt it. When a
question needs fresh facts, GPT-Live hands it to a cheaper text model (the
"router", GPT-6 Luna) with OpenAI's hosted web search and Alfred's job tools
(tools.py). OpenAI runs the hand-off itself ("Responses delegation"); Pipecat
runs the job tools here when the router calls them.

Alfred also tells you about background jobs without being asked (announcer.py).

The session closes after about `idle_seconds` with nobody speaking, with a warning tone
first; it stays open longer while a job is busy (idle.py).
"""

import time

from loguru import logger
from pipecat.adapters.llm.schemas.tools_schema import AdapterType, ToolsSchema
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
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
from pipecat.services.openai.live.llm import OpenAILiveLLMService
from pipecat.services.openai.responses.llm import OpenAIResponsesLLMService
from pipecat.workers.runner import WorkerRunner

from alfred.announcer import JobAnnouncer, opening_messages, recent_jobs_context
from alfred.audio import SAMPLE_RATE, AudioEngine, load_sound
from alfred.config import PROJECT_ROOT, Config, load_prompt
from alfred.db import Database
from alfred.idle import QuietTimer, check_every
from alfred.questions import Questions
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
    engine: AudioEngine, config: Config, tasks: TaskRunner, db: Database, questions: Questions
) -> None:
    """Talk until nobody has spoken for a while, then return."""
    transport = EngineTransport(engine)
    llm = create_gpt_live(config, recent_jobs_context(db))
    # The router's tools: OpenAI's web search plus Alfred's job tools (run here).
    tools = ToolsSchema(
        standard_tools=job_tools(tasks, db, questions),
        custom_tools={AdapterType.OPENAI: [WEB_SEARCH]},
    )
    opening, told = opening_messages(db, questions)
    context = LLMContext(messages=opening, tools=tools)
    user_turns, alfred_turns = LLMContextAggregatorPair(context)
    pipeline = Pipeline([transport.input(), user_turns, llm, transport.output(), alfred_turns])
    worker = create_worker(pipeline, config)
    announcer = JobAnnouncer(llm, db, tasks, questions)

    @llm.event_handler("on_session_started")
    async def on_session_started(_llm, _session):
        announcer.session_open = True
        db.mark_told(told)  # only now: if the session failed to open, you'd not hear them
        logger.info("Listening (GPT-Live session open)")
        transport.mic_input.start_forwarding()

    warning_sound = load_sound(PROJECT_ROOT / "sounds" / "session_warning.wav")
    timer = QuietTimer(worker, engine, warning_sound, config, tasks, questions, announcer)
    timer.listen(worker, user_turns)

    def on_activity(said: str | None = None) -> None:
        timer.activity()
        if said:
            announcer.user_said(str(said))

    log_conversation(llm, user_turns, alfred_turns, on_activity)
    questions.new_question.clear()  # waiting questions are in the opening message
    announcer.start()
    await worker.queue_frame(LLMRunFrame())  # opens the GPT-Live session
    pipeline_runner = WorkerRunner(handle_sigint=False)  # Ctrl+C is handled in __main__.py
    await pipeline_runner.add_workers(worker)
    started = time.monotonic()
    try:
        await pipeline_runner.run()  # returns when the session has closed
    finally:
        announcer.stop()
        timer.stop()
        minutes = (time.monotonic() - started) / 60
        logger.info(
            f"Session closed after {minutes:.1f} min (about ${minutes * 0.05:.2f} of GPT-Live)"
        )


def create_gpt_live(config: Config, context: str = "") -> OpenAILiveLLMService:
    """GPT-Live, handing look-ups to the router model (OpenAI runs the hand-off).
    `context` is added to its instructions (recent jobs, so it isn't starting blank)."""
    logger.debug(
        f"Opening GPT-Live session: live model {config.live_model}, "
        f"router {config.router_model}, voice {config.voice or 'default'}"
    )
    return OpenAILiveLLMService(
        api_key=config.openai_api_key,
        settings=OpenAILiveLLMService.Settings(
            model=config.live_model,
            system_instruction=load_prompt("voice") + context,
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
        idle_timeout_secs=check_every(config.idle_seconds),  # see idle.py
        cancel_on_idle_timeout=False,  # idle.py warns, then closes politely
        # If GPT-Live's connection fails, end at once and go back to the wake word
        # instead of sitting silent until the idle timeout.
        processor_unusable_policy=ProcessorUnusablePolicy.END,
        observers=[DebugLogObserver(frame_types=LOGGED_FRAMES), MetricsLogObserver()],
    )


def log_conversation(llm, user_turns, alfred_turns, on_activity) -> None:
    """Show what was said, and when the router looks something up. on_activity is called
    whenever someone speaks, with what you said."""

    @llm.event_handler("on_delegation_created")
    async def on_delegation_created(_llm, delegation):
        logger.info(f"Router is looking something up ({delegation.id})")

    @user_turns.event_handler("on_user_turn_message_added")
    async def on_user_turn(_aggregator, message):
        logger.info(f"You: {message.content}")
        on_activity(message.content)

    @alfred_turns.event_handler("on_assistant_turn_stopped")
    async def on_alfred_turn(_aggregator, message):
        if message.content:
            logger.info(f"Alfred: {message.content}")
        on_activity()
