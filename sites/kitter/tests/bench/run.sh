#!/usr/bin/env bash
# DEVELOPMENT ONLY: kitter against x.com's own app (docs/design.md, Against x.com) in the Zen of tests/zen.sh,
# signed in with a copy of Andrew's x.com cookies, never his own browser. About six minutes; run it alone on a
# quiet machine. Prints both reports and keeps them in ~/.local/state/krusta-dev/bench-results/.
#
#   sites/kitter/tests/bench/run.sh                 # the staged .#extension
#   sites/kitter/tests/bench/run.sh <extension dir> # another build
set -euo pipefail
K=$(cd "$(dirname "$0")/../../../.." && pwd)
OUT=~/.local/state/krusta-dev/bench-results
# shellcheck source=tests/zen.sh
. "$K/tests/zen.sh"
trap zen_stop EXIT
zen_start "$@"
python3 -I "$K/sites/kitter/tests/bench/memory.py" "$ZEN_DIR/downloads" "$(zen_pid)" &
addon "$K/sites/kitter/tests/bench" >/dev/null # starts the bench at once
for _ in $(seq 900); do
  report=$(find "$ZEN_DIR/downloads" -name 'kitter-bench-[0-9]*.json')
  [[ -z $report ]] || break
  sleep 1
done
[[ -n $report ]] || { echo "no bench report within 15 minutes" >&2 && exit 1; }
sleep 5 && kill %1 2>/dev/null || true # memory.py ends after its last round, unless the bench failed before
mkdir -p "$OUT" && cp "$ZEN_DIR"/downloads/kitter-bench-*.json "$OUT/"
jq '{error, summary}' "$report" && jq .medians "$ZEN_DIR"/downloads/kitter-bench-memory-*.json 2>/dev/null
