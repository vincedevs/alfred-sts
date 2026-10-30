# Alfred v2

A voice-only assistant, built laptop-first and moving to a Raspberry Pi 5.
Say **"Hey Alfred"**, hear a chime, then just talk. You can interrupt Alfred at
any time. Questions that need current facts (weather, news, prices) are looked
up on the web.

**Status:** Day 1 of 5, "Talk to Alfred". Plan and tracker:
<https://claude.ai/artifact/DZTBL6AZixmsbfRg5aHsQW>

## How it works

```
microphone ─► echo canceller ─► wake word ("Hey Alfred")
                    │                    │ heard
                    ▼                    ▼
                 GPT-Live  ◄──────── session opens
            (listens and talks)
                    │ needs fresh facts
                    ▼
          router: GPT-6 Luna + web search   (run by OpenAI)
                    │
speaker  ◄──────────┘   session closes after 25 s of silence
```

| File | Job |
| --- | --- |
| `alfred/__main__.py` | The main loop: wait for the wake word, talk, repeat |
| `alfred/audio.py` | Microphone and speaker, with WebRTC echo cancellation so Alfred doesn't hear itself |
| `alfred/audio_log.py` | Debug log of mic and speaker activity (who is talking, levels, device problems) |
| `alfred/wakeword.py` | Runs the three openWakeWord models in `models/` on the microphone audio |
| `alfred/voice.py` | One GPT-Live conversation through Pipecat, and the bridge between Pipecat and the audio engine |
| `alfred/config.py` | Reads settings from `.env` |
| `sounds/listening_start.wav` | Played when Alfred hears the wake word (16 kHz mono) |
| `prompts/voice.md`, `prompts/router.md` | What GPT-Live and the router are told. Edit these to change Alfred's behaviour |

## Setup (macOS)

You need [uv](https://docs.astral.sh/uv/) and an OpenAI API key with access to
`gpt-live-1` and `gpt-6-luna`.

```bash
cd alfred-v2
uv sync                 # creates .venv and uv.lock (installs Python 3.12 if needed)
cp .env.example .env    # then put your OPENAI_API_KEY in .env
```

The first time you run Alfred, macOS asks for microphone access for your
terminal app. Allow it (System Settings → Privacy & Security → Microphone).

## Run

```bash
uv run alfred
```

Wait for `Waiting for "Hey Alfred"...`, then say "Hey Alfred, what's the
weather today?". Stop with Ctrl+C.

To pick a different microphone or speaker, list the devices and put the
index or part of a name in `.env` (`ALFRED_INPUT_DEVICE`, `ALFRED_OUTPUT_DEVICE`):

```bash
uv run python -m sounddevice
```

## Test

```bash
uv run pytest
```

The wake-word tests run the real models. To also test that your own voice
wakes Alfred, record a clip first. It is git-ignored.

```bash
# Option 1: record yourself (3 s; requires `brew install sox`)
rec -r 16000 -c 1 -b 16 tests/hey_alfred.wav trim 0 3
# Option 2: a synthetic voice
say -o tests/hey_alfred.wav --file-format=WAVE --data-format=LEI16@16000 "Hey Alfred"
```

### Day 1 manual checks

Record the results in the tracker's "Measured results" table.

1. **Wake word:** say "Hey Alfred" 20 times from where you normally sit. Count the misses.
2. **False wakes:** leave Alfred running for 30 minutes with a video or music playing. Count the wakes.
3. **Echo:** use the laptop speakers, not headphones, and ask a long question
   ("Tell me about the history of Manila"). Alfred should not stop or interrupt itself.
4. **Barge-in:** interrupt Alfred mid-answer. It should stop within about a third of a second.
5. **Look-ups:** ask "What's the weather in Manila right now?". The log shows
   `Router is looking something up`.
6. **Idle close:** stay silent. After 25 s the log shows the session closing, and
   "Hey Alfred" works again.

If Alfred keeps hearing itself on the laptop speakers, use headphones for now
and note it in the tracker. The Pi's speaker setup will be tuned on Day 5.

## Logs

Every run writes a full debug log to `logs/alfred-<date>-<time>.log`, while the
terminal shows only the conversation. The log has:

- startup details: Python and package versions, settings (never the API key),
  audio devices and latency, and whether echo cancellation is on;
- a timeline of who is talking: `mic: voice`, `speaker: Alfred talking`,
  `speaker: quiet`. Barge-in time is the gap between `mic: voice [while Alfred
  talks]` and the next `speaker: quiet`;
- Pipecat's turn, transcript, tool and error events, plus GPT-Live usage metrics;
- wake-word near misses (scores above 0.2), to help tune the threshold;
- audio stats every 10 s: levels, device over/underflows, callback errors;
- session length and approximate GPT-Live cost, and a full traceback if Alfred crashes.

When something goes wrong, share the log file.

## Echo cancellation on/off

Set `ALFRED_ECHO_CANCELLATION=off` in `.env` to pass the raw microphone on, with no
echo cancellation, noise suppression or gain control. Set it to `on` to turn them back on.
Compare the two with headphones and with the laptop speakers.

## Settings

All settings live in `.env`; see `.env.example` for the full list. The ones you
are most likely to change are `ALFRED_WAKE_THRESHOLD` (raise it if Alfred wakes
by mistake) and `ALFRED_IDLE_SECONDS`.

## Simplicity rules

1. One clear job per file, easy to name and explain. File length is not a rule; a long file is a hint it may be doing two jobs.
2. Keep functions short: past about 40 lines, consider splitting it.
3. Functions first; a class only when it holds state.
4. Prompts are files in `prompts/`, not strings in code.
5. Every new dependency gets a line in the tracker's decision log.
6. Each day ends with something that works.
