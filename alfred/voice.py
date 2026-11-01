"""One spoken conversation with GPT-Live, from wake word to idle timeout.

    microphone -> GPT-Live -> speaker

GPT-Live listens and talks at the same time, so you can interrupt it. When a
question needs fresh facts, GPT-Live hands it to a cheaper text model (the
"router", GPT-6 Luna) with OpenAI's hosted web search, Alfred's own tools for jobs,
memory and reminders (tools.py), and Wayne Manor's for the house (house.py). OpenAI
runs the hand-off itself ("Responses delegation"); Pipecat runs those tools here when the
router calls them.

Alfred also speaks up without being asked, about jobs and reminders (announcer.py).

The session closes after about `idle_seconds` with nobody speaking, with a warning tone
first; it stays open longer while a job is busy (idle.py).
"""

import asyncio
import time

from loguru import logger
from pipecat.adapters.llm.schemas.tools_schema import AdapterType, ToolsSchema
from pipecat.frames.frames import (
    BotSpeakingFrame,
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
from alfred.chat import chat_tools
from alfred.config import PROJECT_ROOT, Config, load_prompt
from alfred.house import wayne_manor_tools
from alfred.idle import QuietTimer, check_every
from alfred.promises import PromiseCheck
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
VOICE_PER_MINUTE = 0.05  # GPT-Live's price in dollars, billed per second
LOOKUP_SECONDS = 30  # a look-up gets this long to come back before quiet counts
# How OpenAI says the account has no credits left (then nothing works until you add some)
NO_CREDITS = ("no credits remaining", "insufficient_quota", "exceeded your current quota")


async def run_conversation(engine: AudioEngine, services: Services) -> list[str] | None:
    """Talk until nobody has spoken for a while. Returns what was said, line by line, or
    None if the session never opened (no internet, OpenAI unreachable, no credits)."""
    house_tools = await wayne_manor_tools(services.config)
    return await Conversation(engine, services, house_tools).run()


class Conversation:
    """One conversation: GPT-Live's pipeline, and what listens to it: announcer.py (news
    and quick answers), idle.py (when to close) and promises.py (hand-offs)."""

    def __init__(self, engine: AudioEngine, services: Services, house_tools: list):
        s = self.services = services
        self.transcript: list[str] = []
        self.lookups = 0  # hand-offs to the router, billed separately from the voice
        self._looked_up_at = -1e9
        self.llm = create_gpt_live(s.config, *background(s))
        opening, self._told_jobs, self._said_reminders = opening_messages(
            s.db, s.questions, s.reminders
        )
        context = LLMContext(messages=opening, tools=router_tools(s, house_tools))
        self.transport = EngineTransport(engine)
        user_turns, alfred_turns = LLMContextAggregatorPair(context)
        self.worker = create_worker(
            Pipeline(
                [
                    self.transport.input(),
                    user_turns,
                    self.llm,
                    self.transport.output(),
                    alfred_turns,
                ]
            ),
            s.config,
        )
        self.announcer = Announcer(
            self.llm, s.db, s.tasks, s.questions, s.reminders, s.ringer, s.chat
        )
        self.promises = PromiseCheck(self.llm)  # "I'll put that on" must be followed by a hand-off
        self.timer = quiet_timer(self.worker, engine, s, self.announcer, self._looking_up)
        self.out_of_credits = end_if_out_of_credits(self.worker)
        # who listens to what
        self.announcer.on_tell.append(self.promises.handed_off)
        self.timer.listen(self.worker, user_turns)
        self.llm.add_event_handler("on_session_started", self._session_started)
        log_conversation(self.llm, user_turns, alfred_turns, self._line, self._looked_up)

    async def run(self) -> list[str] | None:
        s = self.services
        s.questions.new_question.clear()  # what's waiting is in the opening message
        s.reminders.wake.clear()
        self.announcer.start()
        await self.worker.queue_frame(LLMRunFrame())  # opens the GPT-Live session
        runner = WorkerRunner(handle_sigint=False)  # Ctrl+C is handled in __main__.py
        await runner.add_workers(self.worker)
        started = time.monotonic()
        try:
            await runner.run()  # returns when the session has closed
        finally:
            self.announcer.stop()
            self.timer.stop()
            minutes = (time.monotonic() - started) / 60
            logger.info(
                f"Session closed after {minutes:.1f} min: ${minutes * VOICE_PER_MINUTE:.2f} "
                f"of GPT-Live voice, plus {self.lookups} router look-up(s) billed separately"
            )
        if self.out_of_credits.is_set():
            return None  # __main__.py plays the "couldn't connect" beeps
        if not self.announcer.session_open:
            logger.warning("Couldn't open a GPT-Live session: check the internet connection")
            return None
        return self.transcript

    async def _session_started(self, _llm, _session) -> None:
        self.announcer.session_open = True
        self.promises.handed_off()  # the opening news (if any) was given to say
        # only now: if the session failed to open, you'd not have heard them
        self.services.db.mark_told(self._told_jobs)
        self.services.reminders.mark_said(self._said_reminders)
        logger.info("Listening (GPT-Live session open)")
        self.transport.mic_input.start_forwarding()

    def _line(self, who: str, text: str) -> None:
        """Each thing said. Only Alfred answering keeps him awake (idle.py)."""
        self.transcript.append(f"{who}: {text}")
        if who == "You":
            self.timer.you_said()
            self.announcer.user_said(text)
        else:
            self.timer.activity()
            self.promises.alfred_said(text)

    def _looked_up(self) -> None:
        """GPT-Live handed something to its backend."""
        self.lookups += 1
        self._looked_up_at = time.monotonic()
        self.timer.activity()
        self.promises.handed_off()

    def _looking_up(self) -> bool:
        """Is the router probably still at it? (A slow web search sends nothing meanwhile.)"""
        return time.monotonic() - self._looked_up_at < LOOKUP_SECONDS


def end_if_out_of_credits(worker) -> asyncio.Event:
    """OpenAI refuses everything once the API credits run out: say so in the log and end
    the conversation at once, instead of sitting there silent. The event is set if so."""
    out = asyncio.Event()

    @worker.event_handler("on_pipeline_error")
    async def on_error(_worker, frame):
        if out.is_set() or not any(words in str(frame.error).lower() for words in NO_CREDITS):
            return
        out.set()
        logger.error(
            "OpenAI credits used up: add credits at "
            "https://platform.openai.com/settings/organization/billing"
        )
        # not awaited here: this handler runs inside the pipeline that's being cancelled
        out.cancelling = asyncio.create_task(worker.cancel(reason="no OpenAI credits"))

    return out


def quiet_timer(
    worker, engine: AudioEngine, services: Services, announcer, looking_up
) -> QuietTimer:
    """Closes the session when it goes quiet; stays open while a job is busy or something
    rings, so you can still say "stop" (idle.py)."""
    s = services
    return QuietTimer(
        worker,
        engine,
        load_sound(PROJECT_ROOT / "sounds" / "session_warning.wav"),
        s.config.idle_seconds,
        # a job working or waiting for an answer, a look-up, or a timer or alarm ringing
        is_busy=lambda: (
            s.tasks.busy
            or bool(s.questions.waiting())
            or looking_up()
            or bool(s.ringer and s.ringer.ringing)
        ),
        on_closing=announcer.closing_now,
    )


def background(services: Services) -> tuple[str, str]:
    """Added to the instructions (GPT-Live's, then the router's): the time, where you are,
    what Alfred knows about you, and recent jobs, so a conversation doesn't start blank."""
    now = f"\n\n## Now\n{services.config.now():%A %d %B %Y, %I:%M %p} (the user's local time)."
    about = services.config.home_text() + services.memory.profile_text()
    return now + about + recent_jobs_context(services.db), now + about


def router_tools(services: Services, house_tools: list) -> ToolsSchema:
    """The router's tools: OpenAI's web search, plus Alfred's own and the house's (run
    here)."""
    s = services
    own = job_tools(s.tasks, s.db, s.questions) + memory_tools(s.memory)
    return ToolsSchema(
        standard_tools=own
        + reminder_tools(s.reminders, s.ringer)
        + chat_tools(s.chat)
        + house_tools,
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
        # Quiet means "Alfred hasn't spoken or used a tool": background voices don't count.
        idle_timeout_frames=(BotSpeakingFrame, FunctionCallInProgressFrame),
        cancel_on_idle_timeout=False,  # idle.py warns, then closes politely
        # If GPT-Live's connection fails, end at once and go back to the wake word
        # instead of sitting silent until the idle timeout.
        processor_unusable_policy=ProcessorUnusablePolicy.END,
        observers=[DebugLogObserver(frame_types=LOGGED_FRAMES), MetricsLogObserver()],
    )


def log_conversation(llm, user_turns, alfred_turns, on_line, on_lookup=None) -> None:
    """Show what was said, and when the router looks something up. on_line(who, text) is
    called with each thing said ("You" or "Alfred"); on_lookup() with each look-up."""

    @llm.event_handler("on_delegation_created")
    async def on_delegation_created(_llm, delegation):
        logger.info(f"Router is looking something up ({delegation.id})")
        if on_lookup:
            on_lookup()

    @user_turns.event_handler("on_user_turn_message_added")
    async def on_user_turn(_aggregator, message):
        logger.info(f"You: {message.content}")
        on_line("You", str(message.content))

    @alfred_turns.event_handler("on_assistant_turn_stopped")
    async def on_alfred_turn(_aggregator, message):
        if message.content:
            logger.info(f"Alfred: {message.content}")
        on_line("Alfred", str(message.content or ""))
