# Full-Duplex Voice Agent on a Raspberry Pi

Student 201511198 · run 2026-11-06_20-26-59 · 2026-11-06

## 5 · Evaluation & Benchmark

| Metric | Definition | Target | Mean | p95 | n |
|---|---|---|---|---|---|
| E2E latency | end of speech → audio out | < 4.00 s | 0.40 s | 1.00 s | 12 |
| ASR final | end of speech → transcript | < 0.80 s | 0.00 s | 0.00 s | 12 |
| LLM TTFT | transcript → first token | < 1.50 s | 0.82 s | 2.29 s | 10 |
| TTS TTFB | text → first audio chunk | < 0.60 s | 0.06 s | 0.09 s | 24 |
| Barge-in | speech → playback stopped | < 0.80 s | 1.27 s | 1.98 s | 9 |
| WER | ASR accuracy on test set | < 15 % | 7.8 % | — | 12 |

- One clock: the assistant machine's monotonic clock; every stage timestamped (VAD end → ASR final → LLM 1st token → TTS 1st audio → speaker)
- E2E = speaker − VAD end; barge-in = stop − speech start
- 10 phrases × 3 runs; mean + p95; JSON log per run: stage_latency.json (per turn: trials/<id>/stages.jsonl)

## Results (deck 2)

Latency chart: latency_chart.svg

- RPi model / RAM: Raspberry Pi 5 Model B Rev 1.1 · 8 GB
- Cooling: official Raspberry Pi 5 case (built-in fan) · peak 52 °C · throttled never
- Network: cloud: Wi-Fi · benchmark link: Wi-Fi, 6 ms round trip
- Date: 2026-11-06
- Model versions: harness pipecat 1.15.0, ASR gpt-live-1 (speech to speech: hears and speaks itself), LLM gpt-live-1 (speech to speech: hears and speaks itself); router gpt-6-luna for look-ups, TTS gpt-live-1 (speech to speech: hears and speaks itself), VAD gpt-live-1 turn detection

## 3 · Context engineering: context size per run

| Context size | Median | Max | First → last call |
|---|---|---|---|
| Prompt tokens per LLM call (estimate, usage) | 2356 | 62037 | 11 → 4603 |
| Messages in context | 210 | 410 | 1 → 410 |
