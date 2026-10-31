"""One spoken conversation with GPT-Live, from wake word to idle timeout.

    microphone -> GPT-Live -> speaker

GPT-Live listens and talks at the same time, so you can interrupt it. When a
question needs fresh facts, GPT-Live hands it to a cheaper text model (the
"router", GPT-6 Luna) with OpenAI's hosted web search and Alfred's own tools for jobs,
memory and reminders (tools.py). OpenAI runs the hand-off itself ("Responses
delegation"); Pipecat runs Alfred's tools here when the router calls them.

Alfred also speaks up without being asked, about jobs and reminders (announcer.py).

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

from alfred.announcer import Announcer, opening_messages, recent_jobs_context
from alfred.audio import SAMPLE_RATE, AudioEngine, load_sound
from alfred.config import PROJECT_ROOT, Config, load_prompt
from alfred.idle import QuietTimer, check_every
from alfred.services import Services
from alfred.tools import job_tools, memory_tools, reminder_tools
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


async def run_conversation(engine: AudioEngine, services: Services) -> list[str] | None:
    """Talk until nobody has spoken for a while. Returns what was said, line by line, or
    None if the session never opened (no internet, or OpenAI unreachable)."""
    s, transcript = services, []
    transport = EngineTransport(engine)
    llm = create_gpt_live(s.config, *background(s))
    opening, told_jobs, said_reminders = opening_messages(s.db, s.questions, s.reminders)
    context = LLMContext(messages=opening, tools=router_tools(s))
    user_turns, alfred_turns = LLMContextAggregatorPair(context)
    pipeline = Pipeline([transport.input(), user_turns, llm, transport.output(), alfred_turns])
    worker = create_worker(pipeline, s.config)
    announcer = Announcer(llm, s.db, s.tasks, s.questions, s.reminders)

    @llm.event_handler("on_session_started")
    async def on_session_started(_llm, _session):
        announcer.session_open = True
        # only now: if the session failed to open, you'd not have heard them
        s.db.mark_told(told_jobs)
        s.reminders.mark_said(said_reminders)
        logger.info("Listening (GPT-Live session open)")
        transport.mic_input.start_forwarding()

    timer = quiet_timer(worker, engine, s, announcer)
    timer.listen(worker, user_turns)

    def on_line(who: str, text: str) -> None:
        timer.activity()
        transcript.append(f"{who}: {text}")
        if who == "You":
            announcer.user_said(text)

    log_conversation(llm, user_turns, alfred_turns, on_line)
    s.questions.new_question.clear()  # what's waiting is in the opening message
    s.reminders.wake.clear()
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
    if not announcer.session_open:
        logger.warning("Couldn't open a GPT-Live session: check the internet connection")
        return None
    return transcript


def quiet_timer(worker, engine: AudioEngine, services: Services, announcer) -> QuietTimer:
    """Closes the session when it goes quiet; stays open while a job is busy (idle.py)."""
    s = services
    return QuietTimer(
        worker,
        engine,
        load_sound(PROJECT_ROOT / "sounds" / "session_warning.wav"),
        s.config.idle_seconds,
        is_busy=lambda: s.tasks.busy or bool(s.questions.waiting()),
        on_closing=announcer.closing_now,
    )


def background(services: Services) -> tuple[str, str]:
    """Added to the instructions (GPT-Live's, then the router's): the time, where you are,
    what Alfred knows about you, and recent jobs, so a conversation doesn't start blank."""
    now = f"\n\n## Now\n{services.config.now():%A %d %B %Y, %I:%M %p} (the user's local time)."
    about = services.config.home_text() + services.memory.profile_text()
    return now + about + recent_jobs_context(services.db), now + about


def router_tools(services: Services) -> ToolsSchema:
    """The router's tools: OpenAI's web search, plus Alfred's own (run here)."""
    s = services
    own = job_tools(s.tasks, s.db, s.questions) + memory_tools(s.memory)
    return ToolsSchema(
        standard_tools=own + reminder_tools(s.reminders),
        custom_tools={AdapterType.OPENAI: [WEB_SEARCH]},
    )


def create_gpt_live(
    config: Config, voice_extra: str = "", router_extra: str = ""
) -> OpenAILiveLLMService:
    """GPT-Live, handing look-ups to the router model (OpenAI runs the hand-off). The
    extras are added to each one's instructions (see background())."""
    logger.debug(
        f"Opening GPT-Live session: live model {config.live_model}, "
        f"router {config.router_model}, voice {config.voice or 'default'}"
    )
    return OpenAILiveLLMService(
        api_key=config.openai_api_key,
        settings=OpenAILiveLLMService.Settings(
            model=config.live_model,
            system_instruction=load_prompt("voice") + voice_extra,
            voice=config.voice,
        ),
        delegation=OpenAILiveLLMService.ResponsesDelegation(
            settings=OpenAIResponsesLLMService.Settings(
                model=config.router_model,
                system_instruction=load_prompt("router") + router_extra,
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


def log_conversation(llm, user_turns, alfred_turns, on_line) -> None:
    """Show what was said, and when the router looks something up. on_line(who, text) is
    called with each thing said ("You" or "Alfred")."""

    @llm.event_handler("on_delegation_created")
    async def on_delegation_created(_llm, delegation):
        logger.info(f"Router is looking something up ({delegation.id})")

    @user_turns.event_handler("on_user_turn_message_added")
    async def on_user_turn(_aggregator, message):
        logger.info(f"You: {message.content}")
        on_line("You", str(message.content))

    @alfred_turns.event_handler("on_assistant_turn_stopped")
    async def on_alfred_turn(_aggregator, message):
        if message.content:
            logger.info(f"Alfred: {message.content}")
        on_line("Alfred", str(message.content or ""))
