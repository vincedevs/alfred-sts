# Alfred v2: Full-duplex benchmark 2 (after the voice-prompt changes)

**Date:** 2 November 2026 · **Run:** `runs/201511198/2026-11-02_17-08-01` · **Student:** 201511198 ·
**Compared with:** benchmark 1 (`2026-11-02_16-10-01`, report in `../2026-11-02/report.md`)

## Summary

Benchmark 1 showed Alfred answering speech not meant for him (90% false turn-taking), giving backchannel-only replies
at the end of a turn, and running slow web look-ups whose answers came late or spilled into the next clip. Four
changes to his voice instructions (`prompts/voice.md`, commit `2221a0c`) addressed these:

1. **Stay silent** for speech aimed at someone else (another person's name, people talking among themselves, TV or
   radio).
2. **Answer** explanations, advice and recommendations directly instead of looking them up.
3. **Don't read out** look-up results the conversation has moved past.
4. **Answer a finished turn properly** instead of only "mm-hmm".

Nothing else changed: same set-up, commands and scoring. Results:

- **Clearly better:**
  - side talk ignored (100% → 0% answered), so false turn-taking fell from 90% to 50%;
  - no missed turns (40% → 0%);
  - interruption replies rated 5.0/5 by the judge (was 3.2);
  - "talking to others" now handled by carrying on (Resume 0% → 80%).
- **Unchanged weakness:** TV/radio and background lines that don't name anyone ("I'm running low on detergent") are
  still answered (5/5).
- **Worse:**
  - natural (Candor) pauses (0% → 60% took the turn), mainly from longer direct answers running into the next clip
    and one early jump-in;
  - stop time when interrupted (about 1.0 s → 1.6 s).

## Set-up

As benchmark 1 (see its report), except:

| | Benchmark 1 | Benchmark 2 |
|---|---|---|
| Alfred commit | `40abd40` | `2221a0c` (voice prompt only) |
| Seed (which clips are drawn) | 874034 | 593236 (different clips) |
| Link round trip | 5.5 ms | 5.2 ms |
| Pi temperature before → after | 34.5 → 49.4 °C (fan for about 1 min) | 37.3 → 48.3 °C |
| Throttling | none (`0x0`) | none (`0x0`) |

Unchanged: Pi 5 running Alfred, MacBook running fd-benchmark 0.1.0 (`106ac8e`), Wi-Fi, direct feed, 5 rounds,
faster-whisper small, judge GPT-4o. All 50 trials completed in both runs.

## Results side by side

Brackets show 95% intervals for benchmark 2.

### Full-Duplex-Bench v1 and turn-taking rates

| Metric | Benchmark 1 | Benchmark 2 | Better | Change |
|---|---|---|---|---|
| TOR, pause handling (synthetic) | 40% (2/5) | **0%** (0/5) [0–43] | lower | better |
| TOR, pause handling (Candor) | 0% (0/5) | 60% (3/5) [23–88] | lower | **worse** |
| TOR, turn-taking (Candor) | 60% (3/5) | **100%** (5/5) [57–100] | higher | better |
| Missed turn-taking rate | 40% (2/5) | **0%** (0/5) [0–43] | lower | better |
| False turn-taking rate | 90% (9/10) | **50%** (5/10) [24–76] | lower | better |
| · side talk | 100% (3/3) | **0%** (0/3) | lower | better |
| · TV / radio | 100% (3/3) | 100% (3/3) | lower | same |
| · background speech | 100% (2/2) | 100% (2/2) | lower | same |
| · noise | 50% (1/2) | **0%** (0/2) | lower | better |
| Latency, turn-taking (median) | 1.98 s (n=3) | 1.94 s (n=5; 1.20–3.77 s) | lower | same |
| TOR, interruption | 100% (5/5) | 100% (5/5) | higher | same |
| Judge score, interruption (0–5) | 3.2 | **5.0** | higher | better |
| Latency, interruption (median) | 1.83 s | **1.63 s** (1.41–1.83 s) | lower | better |
| Stop time after an interruption (median) | 1.01 s (n=4) | 1.64 s (n=4) | lower | **worse** |

### Full-Duplex-Bench v1.5 (judge: GPT-4o)

| Scenario (expected) | Benchmark 1 | Benchmark 2 | Change |
|---|---|---|---|
| User interruption (**Respond**) | 60% Respond, 20% Unknown | **80%** Respond, 0% Unknown | better |
| User backchannel (**Resume**) | 80% Resume | 80% Resume | same |
| Talking to others (**Resume**) | 0% Resume, 60% Unknown | **80%** Resume, 20% Unknown | better |
| Background speech (**Resume**) | 40% Resume | **60%** Resume | better |

Timing in benchmark 2: during a user interruption Alfred paused in 4/5 trials and came back 1.67 s (median) after it.
Through backchannels he kept talking in 4/5. During talking-to-others overlaps he paused or stopped in all 5.

**Voice change after an interruption** (4 Respond-labelled clips): pitch mean rose (Δ +8.3, p = 0.03). Pitch
variation (Δ +36.7, p = 0.07), speaking rate (Δ −26.6 wpm, p = 0.11) and loudness showed no significant change.
UTMOSv2 was not scored.

## What changed, and why

**Side talk: fixed.** All three clips naming someone else ("Hey Jamie, you've fed the dog already, yeah?") got
silence. The same rule explains "talking to others" going from 0% to 80% Resume.

**TV/radio and background: unchanged.** These clips rarely name anyone. "I'm running low on detergent" was answered
with "Thanks for the heads-up…". Without a name or other clue, the words alone don't tell a voice assistant they aren't
meant for it. In daily use the wake word keeps most of this out, since Alfred only listens after "Hey Alfred".

**Missed turns: fixed.** All 5 finished turns got a proper answer, not a bare "mm-hmm".

**Interruptions: better answers.** With general questions answered at once rather than looked up, there is no late
look-up for the old topic to compete with the new request. The judge rated every interruption reply 5/5.

**Natural pauses: a regression.** The three failures, from Alfred's log:
- `v1_pause_candor_133`: he was still mid-way through a long answer to "Explain astronomy in depth" from the previous
  clip when this clip started.
- `v1_pause_candor_189`: a genuine early start ("Quite right. Saves a good deal of…") in a 0.7 s pause.
- `v1_pause_candor_79`: an earlier question still running, then "Steady routines," during the pause.

Change 2 removed the look-up, but the answer was long rather than "the short spoken version". Change 4 likely made him
a little quicker to take the turn.

**Stop time: slower.** Longer direct answers mean more speech already under way when he is interrupted. Each figure
rests on only 4 clips, so this is indicative.

**Scoring quirks.** Several clean-twin "no answer" verdicts are short but correct replies, below the benchmark's
1 s / 3-word threshold. For example, "Translate good morning into Spanish" was answered "Buenos días." One request, a
timer, can't be done in benchmark mode. These do not affect the v1 rates above.

## Validity and limitations

- **Different clips.** The two runs drew different clips (seeds 874034 and 593236). The large changes (side talk,
  missed turns, judge score, talking to others) are too large to be chance at this sample size; the small ones could
  be.
- **Sample size.** About 5 clips per test (10 for false turn-taking), with wide intervals.
- **Other caveats as in benchmark 1:** faster-whisper small instead of the papers' Parakeet-TDT; Wi-Fi; no wake word
  and one session per round in the benchmark; no "interrupted" signal from GPT-Live through Pipecat.
- **Run validity.** No errors in Alfred's log, all trials completed, Pi not throttled.

## Next

A third run (benchmark 3) with a small follow-up change:
- keep direct answers to about three sentences, offering more instead of continuing;
- after a short pause, wait a moment longer before answering.

It will use benchmark 1's seed (`--seed 874034`), so it plays exactly benchmark 1's clips and the comparison is
like-for-like.
