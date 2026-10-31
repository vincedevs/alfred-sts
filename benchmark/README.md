# Benchmarking Alfred with fd-benchmark

[fd-benchmark](https://github.com/trueshotjames/ai231-me3-full-duplex-benchmarking) plays test
clips straight into Alfred and scores turn-taking, pauses, interruptions, false turn-taking and
latency. No microphone or speaker is used.

## What benchmark mode is

The files here run Alfred's own pipeline, models, voice and settings (imported from `alfred/`,
not copied), adapted for the benchmark:

| | Alfred | Benchmark mode |
|---|---|---|
| GPT-Live, voice, router, web search, settings from `.env` | ✓ | same |
| Voice and router prompts | full | same text, minus the jobs, memory and reminders sections |
| Wake word, sounds, closing after 25 s of quiet | ✓ | off: one session per round |
| Background jobs, email, memory, reminders | ✓ | off: nothing is written to `~/.alfred` |
| Microphone, speaker, echo cancellation | ✓ | bypassed: the benchmark sends audio directly |

- `voice.py`: builds the conversation with the benchmark's transport.
- `prompts.py`: Alfred's prompts, trimmed as they load, so later edits carry over.
- `assistant_entry.py`: the file fd-benchmark's launcher loads.
- `tests/test_benchmark.py` checks the prompts differ only by the trimmed sections.

## Set up (once)

From the `alfred-v2` folder:

```bash
git clone https://github.com/trueshotjames/ai231-me3-full-duplex-benchmarking.git fd-benchmark
cd fd-benchmark
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt -r requirements-score.txt
.venv/bin/python tools/fetch_datasets.py      # prints "datasets ready: 430 audio files in 9 groups"
cp .env.example .env
```

Then add this line to `fd-benchmark/.env`, with your own path:

```
FDBENCH_ENTRY=/Users/you/path/to/alfred-v2/benchmark/assistant_entry.py
```

The same file takes an optional key for the benchmark's judge model (see its `.env.example`).
Alfred's own keys stay in `alfred-v2/.env`.

Check (from `fd-benchmark`); the last line must say `READY`:

```bash
../.venv/bin/python launch_assistant.py --check
```

## Run

From `fd-benchmark`, one round (about 7 minutes, roughly $0.35 of GPT-Live):

```bash
.venv/bin/python -m fdbench run --student YOUR_ID --rounds 1 --connect direct --where local \
  --judge-provider none --yes --recordings k
```

Or interactively: `.venv/bin/python -m fdbench`. Results land in `fd-benchmark/runs/<student>/<date-time>/`
(`results.html` opens in a browser). Alfred's own log for the run is
`fd-benchmark/runs/_assistant/alfred-bench-<date-time>.log`.

## Good to know

- **Interruptions:** GPT-Live handles being interrupted on OpenAI's side, and Pipecat doesn't send
  its usual "interrupted" signal, which the benchmark uses to stop counting audio already sent.
  Check the interruption results of the first round with that in mind.
- **Idle noise:** in normal use the wake word filters background noise; here every clip reaches
  Alfred, so "false turn-taking" scores are stricter than real life.
