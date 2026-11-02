# Alfred v2: Full-duplex benchmark 3 (final), compared with benchmarks 1 and 2

**Date:** 2 November 2026 · **Run:** `runs/201511198/2026-11-02_17-47-55` · **Student:** 201511198

Earlier reports: `../2026-11-02/report.md` (benchmark 1), `../2026-11-02-benchmark-2/report.md` (benchmark 2).

## The three runs

| | What changed in Alfred | Commit | Seed (clips) |
|---|---|---|---|
| Benchmark 1 | baseline | `40abd40` | 874034 |
| Benchmark 2 | voice prompt: ignore speech meant for others; answer general questions directly; drop late look-up results; answer a finished turn properly | `2221a0c` | 593236 (different clips) |
| **Benchmark 3** | follow-up: direct answers at most three sentences, offering more; wait a moment longer after a mid-sentence pause | `5e0579c` | **874034, the same clips as benchmark 1** |

All three ran the same way: Alfred on a Raspberry Pi 5, fd-benchmark 0.1.0 (`106ac8e`) on a MacBook, both on Wi-Fi,
direct feed, 5 rounds (50 trials, all completed), faster-whisper small, judge GPT-4o. Only `prompts/voice.md` changed
between runs.

| | Benchmark 1 | Benchmark 2 | Benchmark 3 |
|---|---|---|---|
| Link round trip | 5.5 ms | 5.2 ms | 8.8 ms |
| Pi temperature before → after | 34.5 → 49.4 °C (fan for about 1 min) | 37.3 → 48.3 °C | 47.7 → 48.8 °C |
| Throttling | none (`0x0`) | none | none |

Benchmarks 1 and 3 played identical clips, so the difference between them comes from Alfred alone. Benchmark 2 drew
other clips, so its differences mix the prompt change with the clip choice.

## Summary

Comparing benchmark 3 with benchmark 1 (same clips):

- **Better:**
  - false turn-taking 90% → 50% (side talk 100% → 0%);
  - turn-taking 60% → 80%;
  - missed turns 40% → 20%;
  - interruption reply quality 3.2 → 4.8 out of 5;
  - latency after an interruption 1.83 s → 1.44 s;
  - user backchannels handled 80% → 100%;
  - "talking to others" handled 0% → 60%.
- **Same:**
  - natural pauses (0% took the turn in both);
  - yielding to every interruption (100%);
  - turn-taking latency (about 1.9–2.0 s);
  - background speech Resume (40% in both).
- **Worse:**
  - synthetic pauses 40% → 80% (three of the four failures are answers still running from the previous clip);
  - stop time when interrupted (about 1.0 s → 1.6 s);
  - v1.5 interruption judged Respond 60% → 40% (more Resume).
- **Unchanged weakness:** TV/radio and background lines that don't name anyone are still answered (5/5 in all three
  runs).

## Results

Brackets are 95% intervals for benchmark 3.

### Full-Duplex-Bench v1 and turn-taking rates

| Metric | B1 | B2 | **B3** | Better |
|---|---|---|---|---|
| TOR, pause handling (synthetic) | 40% (2/5) | 0% (0/5) | **80%** (4/5) [38–96] | lower |
| TOR, pause handling (Candor) | 0% (0/5) | 60% (3/5) | **0%** (0/5) [0–43] | lower |
| TOR, turn-taking (Candor) | 60% (3/5) | 100% (5/5) | **80%** (4/5) [38–96] | higher |
| Missed turn-taking rate | 40% (2/5) | 0% (0/5) | **20%** (1/5) [4–62] | lower |
| False turn-taking rate | 90% (9/10) | 50% (5/10) | **50%** (5/10) [24–76] | lower |
| · side talk | 100% (3/3) | 0% (0/3) | **0%** (0/3) | lower |
| · TV / radio | 100% (3/3) | 100% (3/3) | **100%** (3/3) | lower |
| · background speech | 100% (2/2) | 100% (2/2) | **100%** (2/2) | lower |
| · noise | 50% (1/2) | 0% (0/2) | **0%** (0/2) | lower |
| Latency, turn-taking (median) | 1.98 s | 1.94 s | **1.92 s** (n=4; 1.57–2.30 s) | lower, < 1 s |
| TOR, interruption | 100% | 100% | **100%** (5/5) | higher |
| Judge score, interruption (0–5) | 3.2 | 5.0 | **4.8** | higher |
| Latency, interruption (median) | 1.83 s | 1.63 s | **1.44 s** (1.39–1.51 s) | lower |
| Stop time after an interruption (median) | 1.01 s | 1.64 s | **1.56 s** (n=3) | lower |

### Full-Duplex-Bench v1.5 (judge: GPT-4o)

| Scenario (expected) | B1 | B2 | **B3** |
|---|---|---|---|
| User interruption (**Respond**) | 60% | 80% | **40%** (Resume 60%) |
| User backchannel (**Resume**) | 80% | 80% | **100%** |
| Talking to others (**Resume**) | 0% | 80% | **60%** (Unknown 20%) |
| Background speech (**Resume**) | 40% | 60% | **40%** (Unknown 20%) |

Timing in benchmark 3:
- **During a user interruption,** Alfred paused in 5/5 trials and came back 1.86 s (median) after it.
- **Through user backchannels,** he kept talking in 4/5.

**Voice change after an interruption** (2 Respond-labelled clips, too few to interpret): pitch mean Δ −4.2 (p = 0.04),
loudness mean Δ −2.5 (p = 0.02), others not significant. UTMOSv2 was not scored.

## What the logs show

**Side talk stays fixed.** All three clips naming someone else got silence, as in benchmark 2.

**TV/radio and background speech are still answered.** These lines rarely name anyone ("I'm running low on
detergent"), so their words give no sign they aren't meant for Alfred. In daily use the wake word filters most of them,
since Alfred only listens after "Hey Alfred".

**Natural pauses are back to 0%.** Benchmark 2's long direct answers, which ran into the next clip, are gone: answers
now take a few sentences.

**Synthetic pauses: mostly spill-over.** Of the four failures, three began at 0.0 s, while Alfred was still speaking
from the clip before:
- `synth_64`: a follow-up question about an earlier traffic look-up ("…which city or stretch are you thinking of?").
- `synth_40`: reading vegetarian restaurants from a look-up that finished late.
- `synth_110`: a late cinema look-up ("One comedy playing is Pee Mak…"), read out despite the instruction not to.

These look-ups depend on current information, so they can't be answered directly. The benchmark keeps one conversation
for each round with 6 s of silence between clips (a documented deviation from the papers), so a late answer lands on
the next clip.

The fourth failure (`synth_11`) is genuine. During a 3.7 s "let me think" pause, Alfred said "Mm-hmm. Go on." and
"No rush." Encouragements that last over a second count as taking the turn. The new "wait a moment longer" wording
seems to have invited them.

**Missed turn:** `turntaking_49` got "Right." and the full answer began only after the 8-second window.

**Interruptions:** replies stay highly relevant (4.8/5), and the response after an interruption is the fastest of the
three runs (1.44 s). The judge more often labelled his reply Resume, meaning a return to the earlier topic. Short
answers that offer "Shall I go on?" may make him more inclined to finish his previous thought.

## Assessment

On the same clips, benchmark 3 beats benchmark 1 on seven measures and loses on three:
- **Largest gains:** false turn-taking (side talk), interruption quality and response time, and backchannel handling.
- **Losses:** synthetic-pause handling, which comes mostly from late look-up answers spilling between clips, and the
  v1.5 interruption label.

Between benchmarks 2 and 3, the differences are within what 5 clips per test can resolve, apart from the natural-pause
fix. Most differences on single tests are one or two clips.

Benchmark 3 is taken as the final version for these reasons:
- its gains over the baseline are measured on identical clips;
- it fixes benchmark 2's long answers, which matter for a voice assistant in real use;
- its remaining failures have clear, documented causes: no wake word in the benchmark, look-up spill-over between clips,
  and pause-filling encouragements.

## Validity and limitations

- **Sample size.** About 5 clips per test (10 for false turn-taking); intervals span 40–60 points for most rates.
  Only large differences are meaningful.
- **Speech-to-text.** faster-whisper small (repository default) instead of the papers' Parakeet-TDT.
- **Wi-Fi.** Round trips stayed low (5–9 ms), but Wi-Fi jitter can widen latencies; Ethernet is recommended.
- **Benchmark design.**
  - No wake word, so false turn-taking is stricter than real use.
  - One session per round, so answers can spill into the next clip. fd-benchmark's `--reset-cmd` would give a fresh
    session per clip as in the papers, but needs a reset hook in Alfred's benchmark mode.
- **No interruption signal.** GPT-Live handles being interrupted on OpenAI's side and Pipecat sends no "interrupted"
  signal, so audio already queued may play briefly. This may add to the measured stop times.
- **Run validity.** No errors in Alfred's log, all 50 trials completed, the Pi was never throttled.

## Possible future work

1. Tell Alfred to stay fully silent while the user pauses or thinks: no "go on" or "no rush".
2. Add a reset hook so the benchmark can use `--reset-cmd`, removing spill-over between clips.
3. Run 10 or more rounds, on Ethernet, for narrower intervals.
4. Investigate the stop time after an interruption, which may be partly audio already queued without an
   "interrupted" signal.
