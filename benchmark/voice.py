"""The benchmark version of alfred/voice.py: one conversation, built for fd-benchmark.

Alfred's own building blocks are imported, not copied, so the benchmark runs the same
pipeline, models, voice and settings as Alfred:

    transport -> your turns -> GPT-Live (+ router with web search) -> output -> Alfred's turns

What differs, and why:
- The transport is fd-benchmark's (clips in, Alfred's voice out), not the microphone.
- No wake word and no idle close: one continuous session for the whole round, which the
  benchmark ends.
- One extra step, FirstAudioMark, tells fd-benchmark when GPT-Live's first audio of each
  reply comes out (its "TTS first audio" stage); it changes nothing else.
- No background jobs, memory or reminders: no tools besides web search, no database, and
  nothing written to ~/.alfred. Their prompt sections are left out (benchmark/prompts.py).
"""

from dataclasses import replace

from loguru import logger
from pipecat.adapters.llm.schemas.tools_schema import AdapterType, ToolsSchema
from pipecat.frames.frames import LLMRunFrame, SpeechOutputAudioRawFrame, TTSStartedFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.workers.runner import WorkerRunner

import alfred.voice as alfred_voice
from alfred.config import Config
from benchmark.prompts import benchmark_prompt

ONE_HOUR = 3600.0  # "idle" time for Pipecat: longer than any round, so it never fires


async def build_benchmark_conversation(transport, config: Config):
    """Returns (a coroutine that runs the conversation, an async function that stops it)."""
    llm = create_gpt_live(config)
    tools = ToolsSchema(
        standard_tools=[], custom_tools={AdapterType.OPENAI: [alfred_voice.WEB_SEARCH]}
    )
    context = LLMContext(messages=[], tools=tools)
    user_turns, alfred_turns = LLMContextAggregatorPair(context)
    pipeline = Pipeline(
        [transport.input(), user_turns, llm, FirstAudioMark(), transport.output(), alfred_turns]
    )
    worker = alfred_voice.create_worker(pipeline, replace(config, idle_seconds=ONE_HOUR))

    @llm.event_handler("on_session_started")
    async def on_session_started(_llm, _session):
        logger.info("Listening (GPT-Live session open, benchmark mode)")

    alfred_voice.log_conversation(llm, user_turns, alfred_turns, on_line=lambda _who, _text: None)
    await worker.queue_frame(LLMRunFrame())  # opens the GPT-Live session
    runner = WorkerRunner(handle_sigint=False)  # the launcher handles Ctrl+C

    async def run() -> None:
        await runner.add_workers(worker)
        await runner.run()

    async def cancel() -> None:
        await worker.cancel()

    return run(), cancel


class FirstAudioMark(FrameProcessor):
    """Tells fd-benchmark when each reply's first audio comes out of GPT-Live, for its "TTS
    first audio" stage. Its stage marks (adapters/pipecat_marks.py) look for a TTS
    service's audio frames, and GPT-Live's are a different kind, so without this the stage
    shows as "not reported". Does nothing outside fd-benchmark's launcher."""

    def __init__(self):
        super().__init__()
        self._reply_started = False
        try:
            from fdbench_marks import mark  # on the path only when fd-benchmark runs Alfred

            self._mark = mark
        except ImportError:
            self._mark = None

    async def process_frame(self, frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSStartedFrame):
            self._reply_started = True
        elif isinstance(frame, SpeechOutputAudioRawFrame) and self._reply_started:
            self._reply_started = False
            if self._mark:
                self._mark("tts_first_audio")
        await self.push_frame(frame, direction)


def create_gpt_live(config: Config):
    """Alfred's own create_gpt_live(), unchanged, reading the benchmark's prompts instead
    of the full ones. (It reads them while it runs, so swapping the reader for that one
    call is enough; it is put back straight after.)"""
    extra = f"\n\n## Now\n{config.now():%A %d %B %Y, %I:%M %p} (the user's local time)."
    extra += config.home_text()
    real_reader = alfred_voice.load_prompt
    alfred_voice.load_prompt = benchmark_prompt
    try:
        return alfred_voice.create_gpt_live(config, extra, extra)
    finally:
        alfred_voice.load_prompt = real_reader
