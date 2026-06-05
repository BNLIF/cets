---
name: ce-video
description: Turn a completed /ce-diagnose session into a ~20-second terminal demo video (authored asciinema cast → agg → ffmpeg mp4) saved to analysis/video/. Replay speed is auto-scaled from the session length so the output always lands near 20 s. Use when the user asks for a demo video of a diagnosis, or invokes /ce-video. Takes the same argument as /ce-diagnose (run dir, report path, or FEMB serial) to identify which diagnosis to replay.
---

# Make a ~20 s demo video of a /ce-diagnose session

Input (`$ARGUMENTS`): same as `/ce-diagnose` — a run directory, report path, or FEMB serial. It identifies **which diagnosis to replay**:

- Diagnosis already done in this session (the usual flow: `/ce-diagnose` then `/ce-video`) → transcribe it from context. If `$ARGUMENTS` is empty, use the most recent one.
- Done in a **past** session (e.g. the user points at a saved `analysis/*.md` report) → mine that session's transcript (below) for the terminal output.
- Never diagnosed, no transcript found → **run the `/ce-diagnose` skill on `$ARGUMENTS` first** (full procedure, including saving its report), then transcribe.

The video is a **faithful reconstruction** of the session transcript — real tool calls, real result excerpts, real narration, real cost/time — not a screen recording. Say so when delivering.

## 0. Past session: mine the transcript

Claude Code logs every session to `~/.claude/projects/-Users-chaozhang-Code-cets/<session>.jsonl`. Find the session that **wrote** the report — grep for its Write call, not just the filename (any session that merely listed `analysis/` also mentions it):

```bash
T=$(grep -l '"file_path":"/Users/chaozhang/Code/cets/analysis/<report>.md"' \
      ~/.claude/projects/-Users-chaozhang-Code-cets/*.jsonl | head -1)
# tool calls (name + args + timestamp):
jq -r 'select(.message.content[0].type? == "tool_use") | .timestamp + " " + .message.content[0].name + " " + (.message.content[0].input | tostring | .[0:110])' "$T"
# narration (assistant text between tool batches):
jq -r '.message.content[]? | select(.type == "text") | .text' "$T"
# tool results (for the "->" excerpts):
jq -r '.message.content[]? | select(.type == "tool_result") | (.content | tostring | .[0:100])' "$T"
```

Timestamp deltas give the cast timings; elapsed/cost come from the report's footer. Bound the extraction to the diagnosis turn (from the `/ce-diagnose` user message to the final summary) — the session may contain unrelated work.

## 1. Author the cast

Write an asciinema **v3** cast to `/tmp/<name>.cast`. Header (one line), then one JSON array per event with **relative** timestamps:

```
{"version":3,"term":{"cols":120,"rows":32},"timestamp":<diagnosis start epoch>,"command":"bash /tmp/demo-cmd.sh","env":{"SHELL":"/opt/homebrew/bin/bash"}}
[0.025, "o", "\u001b[1m$ claude\u001b[0m\r\n"]
[1.016, "o", "\u001b[1;33m> /ce-diagnose <args>\u001b[0m\r\n\r\n"]
[2.121, "o", "\u001b[1;36m* Claude Code session — model: <model-id>\u001b[0m\r\n\r\n"]
[2.500, "o", "\u001b[1;32m> Bash\u001b[0m\u001b[90m {\"command\":\"date -u +%Y-%m-%dT%H:%M:%SZ\",\"description\":\"Record start timestamp\"}\u001b[0m\r\n"]
[1.000, "o", "\u001b[90m    -> 2026-06-04T23:37:35Z\u001b[0m\r\n\r\n"]
[18.402, "o", "\u001b[37m<narration line from the session>\u001b[0m\r\n\r\n"]
[19.724, "o", "\u001b[37m<final diagnosis summary block, \r\n-separated>\u001b[0m\r\n\r\n"]
[0.053, "o", "\r\n\u001b[1;36m* Done in <elapsed>s — <N> turns, cost $<total>\u001b[0m\r\n"]
[0.299, "x", "0"]
```

Style conventions:

- Tool call: `\u001b[1;32m> <ToolName>\u001b[0m` + `\u001b[90m {<args JSON truncated to ~110 chars>}\u001b[0m`. Parallel calls = consecutive events ~0.1 s apart.
- Tool result: `\u001b[90m    -> <excerpt ≤ ~100 chars>\u001b[0m`, then a blank line (`\r\n\r\n`) after each result group. PNG reads: `    -> (image) <one-line description of what the plot shows>`.
- Narration (white `\u001b[37m`): the actual prose between tool batches. Precede with a 10–30 s think-gap.
- Final summary: the diagnosis sections condensed, split across 2–3 events (`[0.001, ...]` continuations).
- Done line: elapsed/turns/cost from the diagnosis report's footer — keep them honest.

Rules:

- Strict JSON: literal 6-char `\u001b` sequences, never raw ESC bytes (the render script auto-fixes raw ESC, but check). Escape embedded quotes/backslashes.
- Timing deltas mirror the real session; total ≈ real elapsed seconds. Author the **real** timeline — don't pre-compress. All compression happens at render: idle gaps are capped at 5 s, then the replay speed is computed so the output lands near 20 s regardless of session length.

## 2. Render

```bash
.claude/skills/ce-video/scripts/render.sh /tmp/<name>.cast analysis/video/<name>.mp4
```

Validates the cast (fixing raw ESC bytes), measures its idle-capped duration, computes `speed = capped / 20 s` (clamped ≥ 1), then agg → gif → ffmpeg mp4 (even-dimension crop — agg output can be odd-sized, which libx264 rejects). Overrides: `TARGET_SECONDS=<s>` for a different length, `SPEED=<n>` to force a fixed speed.

Name the output `ce-diagnose_FEMB-<serial>_<env>-<QC|CHK>_<model-slug>_<n>x.mp4`, where `<n>` = **real session elapsed ÷ video duration**, rounded to the nearest integer (e.g. 3 m 06 s → 20 s ≈ `9x`) — take elapsed from the diagnosis report footer and the video duration from render.sh's ffprobe line. This keeps the filename honest about the actual timeline compression, since the 5 s idle caps mean it differs from the agg speed.

## 3. Verify

Extract a mid and final frame and Read them as images — check colors render, lines don't wrap badly, and the final summary + Done line are visible:

```bash
ffmpeg -y -v quiet -i <out>.mp4 -ss <mid> -frames:v 1 /tmp/f1.png -ss <end-0.2> -frames:v 1 /tmp/f2.png
```

Prerequisites: `agg`, `ffmpeg` (both via Homebrew). Stay in the conversation; don't delete the `/tmp` cast/gif — they're useful for re-renders.
