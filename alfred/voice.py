"""One spoken conversation with GPT-Live, from wake word to idle timeout.

    microphone -> GPT-Live -> speaker

GPT-Live listens and talks at the same time, so you can interrupt it. When a
question needs fresh facts, GPT-Live hands it to a cheaper text model (the
"router", GPT-6 Luna) that has OpenAI's hosted web search. OpenAI runs that
hand-off itself ("Responses delegation"), so this file has no router code.

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
from pipecat.services.openai.live.llm import OpenAILiveLLMService
from pipecat.services.openai.responses.llm import OpenAIResponsesLLMService
from pipecat.workers.runner import WorkerRunner

from alfred.audio import SAMPLE_RATE, AudioEngine
from alfred.config import PROJECT_ROOT, Config
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

WEB_SEARCH = ToolsSchema(
    standard_tools=[], custom_tools={AdapterType.OPENAI: [{"type": "web_search"}]}
)


async def run_conversation(engine: AudioEngine, config: Config) -> None:
    """Talk until nobody has spoken for `config.idle_seconds`, then return."""
    transport = EngineTransport(engine)
    llm = create_gpt_live(config)
    context = LLMContext(tools=WEB_SEARCH)  # the router's tools; Day 2 adds Alfred's own
    user_turns, alfred_turns = LLMContextAggregatorPair(context)
    pipeline = Pipeline([transport.input(), user_turns, llm, transport.output(), alfred_turns])
    worker = create_worker(pipeline, config)

    @llm.event_handler("on_session_started")
    async def on_session_started(_llm, _session):
        logger.info("Listening (GPT-Live session open)")
        transport.mic_input.start_forwarding()

    @worker.event_handler("on_idle_timeout")
    async def on_idle(_worker):
        logger.info(f"No speech for {config.idle_seconds:.0f} s, closing the session")
        await worker.queue_frame(EndFrame())  # lets GPT-Live finish and close cleanly

    log_conversation(llm, user_turns, alfred_turns)
    await worker.queue_frame(LLMRunFrame())  # opens the GPT-Live session
    runner = WorkerRunner(handle_sigint=False)  # Ctrl+C is handled in __main__.py
    await runner.add_workers(worker)
    started = time.monotonic()
    try:
        await runner.run()  # returns when the session has closed
    finally:
        minutes = (time.monotonic() - started) / 60
        logger.info(
            f"Session closed after {minutes:.1f} min (about ${minutes * 0.05:.2f} of GPT-Live)"
        )


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


def load_prompt(name: str) -> str:
    return (PROJECT_ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8").strip()
