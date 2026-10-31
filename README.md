# Alfred

A voice-only assistant with the manner of an English butler. Say **"Hey Alfred"**, hear a
chime, then just talk. You can interrupt him at any time.

- **Questions and conversation:** Alfred answers straight away, and looks up anything
  current (weather, news, prices) on the web.
- **Bigger jobs:** research, comparisons, notes, drafts, charts and small programs run in
  the background while you carry on talking. A chime tells you when one is done, and Alfred
  tells you the result.
- **Email:** Alfred can send email from your Gmail account, but only after you say yes.

## What it sounds like

| Sound | Meaning |
| --- | --- |
| Wake chime | Alfred heard "Hey Alfred" and is listening |
| Soft two-note chime | A background job finished, or a job needs your answer |
| Single soft tick | Alfred will stop listening in 5 seconds unless you speak |
| Low two-note sound | Alfred has stopped listening: say "Hey Alfred" next time |

Alfred stops listening after about 25 seconds of quiet. While a job is still working or
waiting for your answer, he stays with you for up to 2 minutes.

## Things to try

- "Hey Alfred, what's the weather in Manila today?"
- "Compare three robot vacuums under 15,000 pesos and save notes."
- "How's my job going?", "What did you find?", "Stop that job."
- "Make me a chart of the peso against the US dollar over the last year."
- "Research the latest Grammys news and email it to me."

Notes, charts and anything else Alfred makes are saved in `~/.alfred/workspace`.

## Staying in control

- **You approve anything that leaves the house.** Before sending an email, Alfred reads out
  the recipient, the subject and how the email begins, and waits for your "yes". Anything
  but a clear yes is a no, and no answer within 5 minutes is a no.
- **Alfred asks rather than guesses** when a request is unclear.
- **Background jobs work in their own folder.** They can't read your personal folders,
  your passwords or Alfred's settings, can't make payments or unlock anything, and can't
  install software on your computer without asking.
- **Every action is recorded.** `~/.alfred/audit.jsonl` lists everything a job did or
  tried to do, and what happened.
- **Stopping:** say "stop that job" at any time. Ctrl+C stops Alfred; unfinished jobs carry
  on when you start him again.

## Setup (macOS)

You need:

- [uv](https://docs.astral.sh/uv/);
- an OpenAI API key with access to `gpt-live-1` and `gpt-6-luna`;
- a Claude sign-in for background jobs: your Claude plan (`claude setup-token`) or a
  Claude API key;
- optional, for email: a Gmail address and a
  [Gmail app password](https://myaccount.google.com/apppasswords) (never your real password).

```bash
cd alfred-v2
uv sync
cp .env.example .env    # then fill in your keys
```

The first time you run Alfred, macOS asks for microphone access for your terminal app.
Allow it (System Settings → Privacy & Security → Microphone).

## Run

```bash
uv run alfred
```

Wait for `Waiting for "Hey Alfred"...`, then speak. Press Ctrl+C to stop.

## Settings

All settings live in `.env`; `.env.example` lists them with explanations. The ones you are
most likely to change:

| Setting | What it does |
| --- | --- |
| `ALFRED_VOICE` | Alfred's voice. `vesper` is British; others include `marin`, `cedar`, `stone`, `willow` (Irish) and `quartz` (Australian) |
| `ALFRED_WAKE_THRESHOLD` | Raise it if Alfred wakes by mistake; lower it if he misses you |
| `ALFRED_IDLE_SECONDS` | How long Alfred waits in silence before he stops listening |
| `ALFRED_INPUT_DEVICE`, `ALFRED_OUTPUT_DEVICE` | Which microphone and speaker to use (list them with `uv run python -m sounddevice`) |
| `ALFRED_TASK_BUDGET_USD` | The most one background job may cost |

## Costs

Talking to Alfred costs about $0.05 a minute (OpenAI). A background job typically costs a
few cents and never more than `ALFRED_TASK_BUDGET_USD`. Check your usage in your OpenAI
and Claude account dashboards.

## Privacy

Your voice goes to OpenAI while Alfred is listening, and background jobs run on Claude.
Nothing is sent before you say "Hey Alfred", except when Alfred speaks up himself to ask
you something. Everything Alfred keeps (jobs, questions, the action record and saved files)
stays in `~/.alfred` on your computer.

## Troubleshooting

Every run writes a detailed log to `logs/alfred-<date>-<time>.log`. If something goes
wrong, that file shows what happened.

- **Alfred hears himself or interrupts himself:** use headphones, or lower the speaker volume.
- **Alfred wakes by mistake, or doesn't hear "Hey Alfred":** adjust `ALFRED_WAKE_THRESHOLD`.
- **Background jobs fail at once:** check the Claude sign-in in `.env`.
- **Email fails:** check `ALFRED_EMAIL` and the app password in `.env`.
