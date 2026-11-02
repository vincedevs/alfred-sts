# Alfred v2: Full-duplex benchmark results

**Date:** 2 November 2026 · **Run:** `runs/201511198/2026-11-02_16-10-01` · **Student:** 201511198

Alfred was benchmarked with [fd-benchmark](https://github.com/trueshotjames/ai231-me3-full-duplex-benchmarking),
which adapts Full-Duplex-Bench v1 (Lin et al., 2025) and v1.5 (Lin et al., 2026) and adds a missed and a false
turn-taking rate. The run followed the repository's guide for a Raspberry Pi (steps 8–11) and its default scoring.

## Summary

- **Handles being interrupted well:** yielded to every interruption (5/5), stopped speaking about 1 s after being
  talked over, and replied about 1.8 s after the interruption ended.
- **Handles pauses and backchannels well:** stayed silent through natural pauses (0/5 took the turn) and kept talking
  through the user's "mm-hmm" (4/5 judged Resume).
- **Main weakness: speech not meant for him.** Alfred answered 9 of 10 clips of side talk, TV/radio and background
  speech (false turn-taking 90%). In the benchmark there is no wake word, and GPT-Live treats everything it hears as
  addressed to Alfred.
- **Secondary weaknesses:** two answers too short to count as taking the turn (missed turn-taking 40%), and several
  failures caused by slow web look-ups and late answers spilling into the next test clip.
- With 5 rounds, each test has 5 clips (10 for false turn-taking), so the 95% intervals are wide. The results show
  clear strengths and one clear weakness, but small differences between metrics are not meaningful.

## Set-up

| | |
|---|---|
| Assistant | Alfred v2 in benchmark mode (`benchmark/`): Alfred's own pipeline, GPT-Live (`gpt-live-1`, voice vesper) with router `gpt-6-luna` and web search; no wake word, background jobs, memory, reminders or house |
| Assistant hardware | Raspberry Pi 5, Raspberry Pi OS 64-bit, Python 3.12 |
| Benchmark host | MacBook (macOS 25.6, Apple silicon, 16 GB), Python 3.12.12 |
| Connection | Direct feed (`--connect direct --where remote`), both on Wi-Fi; link round trip **5.5 ms** |
| Versions | fd-benchmark 0.1.0, commit `106ac8e`; Alfred commit `40abd40` |
| Rounds | 5 (seed 874034): 50 trials, all completed, plus 20 clean reference twins for v1.5 |
| Speech-to-text | faster-whisper small, int8 (repository default) |
| Judge | OpenAI GPT-4o, temperature 0 (marked paper-comparable) |
| Pi health | 34.5 °C before, 49.4 °C after (a fan was pointed at the Pi for about 1 minute); `throttled=0x0`, no throttling |

Commands, from `fd-benchmark` on the Mac, with the Pi running `launch_assistant.py`:

```bash
.venv/bin/python -m fdbench run --student 201511198 --rounds 5 --connect direct --where remote --judge-provider none --yes --recordings k
.venv/bin/python -m fdbench score runs/201511198/2026-11-02_16-10-01 --judge-provider openai --judge-model gpt-4o
```

## Results: Full-Duplex-Bench v1 and turn-taking rates

A trial counts as "took the turn" if Alfred spoke for at least 1 s, or for less but with more than 3 words.
Brackets are 95% intervals.

| Metric | Result | 95% interval | Better |
|---|---|---|---|
| TOR, pause handling (synthetic) | 40% (2/5) | 12–77% | lower |
| TOR, pause handling (Candor) | **0%** (0/5) | 0–43% | lower |
| TOR, turn-taking (Candor) | 60% (3/5) | 23–88% | higher |
| Missed turn-taking rate | 40% (2/5) | 12–77% | lower |
| **False turn-taking rate** | **90%** (9/10) | 60–98% | lower |
| · side talk | 100% (3/3) | 44–100% | lower |
| · TV / radio | 100% (3/3) | 44–100% | lower |
| · background speech | 100% (2/2) | 34–100% | lower |
| · noise | 50% (1/2) | 9–91% | lower |
| Latency, turn-taking | median 1.98 s, mean 1.54 s (n=3; 0.35–2.30 s) | | lower, < 1 s |
| **TOR, interruption** | **100%** (5/5) | 57–100% | higher |
| Judge score, interruption (0–5) | 3.2 (n=5) | | higher |
| Latency, interruption | median 1.83 s, mean 2.02 s (n=5; 1.71–2.96 s) | | lower |
| Stop time after being interrupted (t_stop) | median 1.01 s (n=4; 0.71–1.15 s) | | lower |

## Results: Full-Duplex-Bench v1.5 (overlap handling)

The judge (GPT-4o) labels what Alfred said after the overlap. The timing row shows what he did, whatever he said.

| Scenario (expected) | Respond | Resume | Unknown | Timing: kept talking / paused, came back / stopped | t_stop (median) | t_resp (median) |
|---|---|---|---|---|---|---|
| User interruption (**Respond**) | **60%** (3/5) | 20% | 20% | 0 / 5 / 0 of 5 | 0.96 s | 2.18 s |
| User backchannel (**Resume**) | 0% | **80%** (4/5) | 20% | 1 / 3 / 1 of 5 | 0.30 s (n=2) | 1.74 s |
| Talking to others (**Resume**) | 40% | **0%** (0/5) | 60% | 0 / 3 / 1 of 4 | 1.76 s (n=1) | 1.50 s |
| Background speech (**Resume**) | 60% | **40%** (2/5) | 0% | 1 / 4 / 0 of 5 | 1.28 s | 1.78 s |

No Uncertain labels were given. "Unknown" includes trials where Alfred had not answered the first turn, so the
overlap was never played.

**Voice change after an interruption** (v1.5; 3 Respond-labelled clips): pitch variation rose clearly (Δ pitch SD
+32.5, p = 0.011). Speaking rate (Δ −4.8 wpm, p = 0.91), pitch mean (Δ −2.1, p = 0.65), loudness mean (Δ −2.1,
p = 0.06) and loudness variation (Δ +0.4, p = 0.44) showed no significant change. UTMOSv2 was not scored (optional,
not installed).

## What the results mean

**1. Interruptions: the strongest result.** Alfred yielded in every v1 interruption trial and paused in all five v1.5
interruption trials. He stopped about 1 s into the overlap and came back about 2 s after it ended. The judge's 3.2/5 and
60% Respond show his replies did not always address the new request. In some trials he finished or returned to the
earlier topic.

**2. Pauses: good with natural pauses, mixed with synthetic ones.** He waited through every natural (Candor) pause.
Both synthetic-pause failures had other causes:
- `v1_pause_synth_105`: he was still finishing his previous answer ("A moral dilemma is when…") when the clip began,
  so he "spoke at 0.0 s".
- `v1_pause_synth_40`: he spoke 1.0 s into the clip, again just after a previous reply.

**3. Speech not meant for him: the main weakness (90% false turn-taking).** Examples from Alfred's log:

| Clip | What Alfred said |
|---|---|
| "Your coffee's getting cold" | "Best not to let it turn from a treat into a disappointment." |
| "Kayla, your song was on the radio" | "I- I can't hear what's around you, I'm afraid." |
| "Laura, lights flickered again. Storm maybe" | "Sounds like it could be. Stay safe, and keep a torch handy just in case." |

GPT-Live takes every voice as the user's. In daily use the wake word keeps most such speech out, because Alfred only
listens after "Hey Alfred". **During** an open conversation, however, the same thing would happen, for example if
someone else in the room speaks.

**4. Missed turns: short replies.** In both misses Alfred's speech in the 8-second window was about half a second:
- `v1_turntaking_110`: the user was telling a long story with pauses. Alfred answered "Mm-hmm." and "Oh dear." and
  let them continue. That is natural in conversation, but the benchmark expected him to take the turn.
- `v1_turntaking_49`: he began with "Mm-hmm." and the real answer ("I don't, no. But many people do.") came only
  after a gap.

Turn-taking latency (median 1.98 s, n=3) is above the papers' 1 s target. Partly this is GPT-Live's own timing, and
partly the direct feed through Pipecat, which the repository measures at about 0.1–0.25 s round trip.

**5. Slow look-ups and late answers.** Anything that needs the router's web search (traffic, restaurants, sunrise,
"in-depth" explanations) takes about 5–10 s. This caused two kinds of failure:
- **The answer arrives after the 8-second window.** `v15_talking_to_other_100` (clean twin): Alfred said "Checking."
  and the sunrise time came about 10 s later, so it was scored as "no answer".
- **A late answer lands in the next clip.** The benchmark keeps one conversation for the whole round and leaves 6 s of
  silence between clips (METHOD.md lists this as a deviation from the papers). In `false_noise_006`, Alfred was still
  reading cinema listings from an earlier film request when the noise clip played. In `v15_background_83` (clean twin),
  he was still reading out restaurant results.

## Validity and limitations

- **Sample size.** 5 clips per test (10 for false turn-taking). The 95% intervals span 30–60 points for most rates.
  The interruption and false turn-taking results are clear; the pause, missed-turn and v1.5 percentages are
  indicative only.
- **Speech-to-text.** faster-whisper small (repository default) instead of the papers' Parakeet-TDT, so word timings
  and counts differ slightly.
- **Wi-Fi.** The round trip was low (5.5 ms), but Wi-Fi jitter can widen latencies; the guide recommends Ethernet.
- **No wake word, one session per round.** Both are by design of the benchmark. Together they make false turn-taking
  stricter than real use and allow answers to spill between clips.
- **No interruption signal.** GPT-Live handles being interrupted on OpenAI's side and Pipecat sends no "interrupted"
  signal, so audio already queued may play on briefly. This may add a little to the measured stop times.
- **Run validity.** No errors in Alfred's log. All 50 trials completed with no skips or failures. One reconnection was
  logged, from the switch between the preceding 1-round test run and this run. The Pi was not throttled.

## Recommended improvements (to retest with the same settings)

1. **Ignore speech not addressed to Alfred.** One instruction for GPT-Live: stay silent when speech is clearly aimed
   at someone else (another name, "pizza's here") or comes from a TV. This targets the 90% false turn-taking and helps
   in real conversations too.
2. **Answer general questions without a look-up.** Suggestions, definitions and explanations need no web search.
   This cuts those replies from about 7 s to about 1–2 s, which affects latency, "no answer" and spill-over.
3. **Drop late look-up results** once the conversation has moved on, instead of starting to read them.
4. **Take the turn when it is clearly the user's end of turn,** rather than replying with only a backchannel.

Re-run 5 rounds with the same commands, seed policy and scoring after each change, and compare with
`fdbench compare`. Ethernet for both machines would remove the Wi-Fi caveat.
