#!/usr/bin/env bash
# Render an asciinema cast to a ~20s mp4: validate -> agg -> ffmpeg.
# Replay speed is auto-computed from the cast's idle-capped duration so the
# output always lands near TARGET_SECONDS (default 20), however long the
# session was. SPEED=<n> overrides the auto speed.
# Usage: render.sh <cast> <out.mp4>   [TARGET_SECONDS=20] [SPEED=<n>] [IDLE_LIMIT=5]
set -euo pipefail

cast=$1
out=$2
target=${TARGET_SECONDS:-20}
idle=${IDLE_LIMIT:-5}

# Fix raw ESC bytes (a common authoring slip) into literal \u001b, strict-validate,
# and measure the idle-capped duration (what agg will actually play back).
capped=$(python3 - "$cast" "$idle" <<'EOF'
import json, sys
path, idle = sys.argv[1], float(sys.argv[2])
raw = open(path, 'rb').read()
if b'\x1b' in raw:
    open(path, 'wb').write(raw.replace(b'\x1b', b'\\u001b'))
    print('fixed raw ESC bytes -> literal \\u001b', file=sys.stderr)
total = capped = 0.0
with open(path) as f:
    for i, line in enumerate(f.read().splitlines(), 1):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            sys.exit(f'line {i}: invalid JSON: {e}\n{line[:80]!r}')
        if i > 1:
            total += obj[0]
            capped += min(obj[0], idle)
print(f'cast valid | duration {total:.1f}s | idle-capped {capped:.1f}s', file=sys.stderr)
print(f'{capped:.3f}')
EOF
)

# speed = capped duration / target, clamped to >= 1 (never slow a short cast down).
speed=${SPEED:-$(awk -v c="$capped" -v t="$target" 'BEGIN{s=c/t; if(s<1)s=1; printf "%.2f", s}')}
echo "replay speed ${speed}x (idle-capped ${capped}s -> target ~${target}s)"

gif="${cast%.cast}.gif"
agg --speed "$speed" --idle-time-limit "$idle" "$cast" "$gif"

mkdir -p "$(dirname "$out")"
# Crop to even dimensions: agg output can be odd-sized, which libx264 rejects.
ffmpeg -y -v error -i "$gif" -vf "crop=trunc(iw/2)*2:trunc(ih/2)*2" \
  -pix_fmt yuv420p -movflags +faststart "$out"

ffprobe -v quiet -show_entries stream=width,height -show_entries format=duration \
  -of csv=p=0 "$out" | paste -sd, - | awk -v f="$out" -F, '{printf "%s: %sx%s, %.1fs\n", f, $1, $2, $3}'
