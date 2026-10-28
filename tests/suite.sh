#!/usr/bin/env bash
# Every flake check at once, in about the time of the longest one. The checks' own derivations build in the Nix
# daemon; the VM tests' drivers then run side by side in a slice of the user's systemd, where one memory cap bounds
# them all. Same tests, same verdicts as `nix flake check` (tests/judge.nix). tests/lint.sh, all that CI runs, runs
# beside the builds.
#
#   tests/suite.sh            # every check, and lint
#   tests/suite.sh vm-kitter  # only these
#
# A VM check is any check that keeps its run as `.run` (tests/judge.nix), found by evaluating the flake, so a new one
# needs no change here. Each VM check's evidence stays in $KRUSTA_SUITE_DIR/<check> (default
# $XDG_RUNTIME_DIR/krusta-suite): out/ holds what the flake check's run would, log is its console. Keep that path
# short: under a scratchpad the VMs' network socket path passes Unix's 108 characters and the run hangs. Exits 1
# when any check failed.
set -euo pipefail
# One run at a time on the machine, kubicle's tests/suite.sh included, whose lock this is: each run sets its slice's
# memory cap to all that is free, so two at once would each count the same memory. A second run waits here.
exec 9>/tmp/kubicle-suite.lock
flock -n 9 || { echo "waiting for another tests/suite.sh (krusta's or kubicle's) to finish"; flock 9; }
K=$(cd "$(dirname "$0")/.." && pwd)
DIR=${KRUSTA_SUITE_DIR:-$XDG_RUNTIME_DIR/krusta-suite}
SYS=x86_64-linux
SLICE=krusta-suite.slice
# shellcheck disable=SC2016 # Nix's ${...}, not the shell's
checks=$(nix eval --raw "$K#checks.$SYS" --apply 'cs: toString (map (c: if cs.${c} ? run then "vm:${c}" else c) (builtins.attrNames cs))')
ALL_VMS=() ALL_BUILDS=() VMS=() BUILDS=()
for c in $checks; do [[ $c == vm:* ]] && ALL_VMS+=("${c#vm:}") || ALL_BUILDS+=("$c"); done
for c in "${ALL_VMS[@]}"; do [ $# -eq 0 ] || [[ " $* " == *" $c "* ]] && VMS+=("$c"); done
for c in "${ALL_BUILDS[@]}"; do [ $# -eq 0 ] || [[ " $* " == *" $c "* ]] && BUILDS+=("$c"); done
LINT= && { [ $# -eq 0 ] || [[ " $* " == *" lint "* ]]; } && LINT=1
for c in "$@"; do
  [[ " ${ALL_VMS[*]} ${ALL_BUILDS[*]} lint " == *" $c "* ]] || { echo "no check named $c"; exit 1; }
done
now() { date +%s%N; }
secs() { echo "$(( ($(now) - $1) / 1000000000 ))s"; }
start=$(now)

# The drivers first: the VMs start as soon as they exist, while lint and the builds run beside them.
declare -A driver
if [ ${#VMS[@]} -gt 0 ]; then
  installables=()
  for c in "${VMS[@]}"; do installables+=("$K#checks.$SYS.$c.run.driver"); done
  json=$(nix build --no-link --json "${installables[@]}") # stops here on a failed build, which <(...) would hide
  mapfile -t built < <(jq -r '.[].outputs.out' <<<"$json")
  for i in "${!VMS[@]}"; do driver[${VMS[$i]}]=${built[$i]}; done
  echo "drivers built in $(secs "$start")"
fi

builds_log=$DIR/builds.log
# This user's own, closed to others: the verdicts are read back from it, and another user who made it first (in a
# shared /tmp) could plant a link for a log to overwrite, or a passing verdict.
mkdir -m 700 "$DIR" 2>/dev/null || { [ -O "$DIR" ] && [ ! -L "$DIR" ] && chmod 700 "$DIR"; } ||
  { echo "$DIR is not this user's own directory"; exit 1; }
if [ ${#BUILDS[@]} -gt 0 ]; then
  nix build --no-link --keep-going "${BUILDS[@]/#/$K#checks.$SYS.}" >"$builds_log" 2>&1 &
  builds_pid=$!
fi
if [ -n "$LINT" ]; then
  nix develop "$K#lint" -c "$K/tests/lint.sh" >"$DIR/lint.log" 2>&1 &
  lint_pid=$!
fi

# One cap for every VM: what is free now, less 2 GB for the desktop. Past it the kernel kills inside the slice.
avail=$(awk '/MemAvailable/ {print int($2 / 1024)}' /proc/meminfo)
budget=$((avail - 2048))
systemctl --user set-property --runtime "$SLICE" MemoryMax="${budget}M" MemorySwapMax=0 2>/dev/null || true
# Each check's memory peak in MB, as systemd logs it when its scope stops: the VMs' memory plus the store pages they
# read, which count against the slice. A check not listed counts as DEFAULT_PEAK until it is measured.
declare -A peak=([vm-kitter]=1600) # systemd's "memory peak" for the scope, Oct 27, 2026: 1.5G
DEFAULT_PEAK=3000 # a VM check not yet measured
peak() { echo "${peak[$1]:-$DEFAULT_PEAK}"; }
declare -A pid began
used=0
launch() {
  local c=$1
  rm -rf "${DIR:?}/$c" && mkdir -p "$DIR/$c/out" "$DIR/$c/tmp"
  began[$c]=$(now)
  used=$((used + $(peak "$c")))
  # The driver keeps VM state and the switch's socket in XDG_RUNTIME_DIR, under the node's name: runs sharing it
  # delete each other's state and hang at "start all VLans".
  systemd-run --user --scope -q --unit="krusta-suite-$c-$$" --slice="$SLICE" \
    env out="$DIR/$c/out" TMPDIR="$DIR/$c/tmp" XDG_RUNTIME_DIR="$DIR/$c/tmp" \
    "${driver[$c]}/bin/nixos-test-driver" -o "$DIR/$c/out" </dev/null >"$DIR/$c/log" 2>&1 &
  pid[$c]=$!
}
verdict() {
  local c=$1 took
  took=$(secs "${began[$c]}")
  if [ ! -e "$DIR/$c/out/failed" ]; then
    echo "FAIL $c ($took): the run ended before recording a verdict; its console: $DIR/$c/log" && failed=1
  elif [ -s "$DIR/$c/out/failed" ]; then
    echo "FAIL $c ($took):" && sed 's/^/  /' "$DIR/$c/out/failed" && failed=1
  else
    echo "ok   $c ($took)"
  fi
}
failed=0
queue=("${VMS[@]}")
running=()
while [ ${#queue[@]} -gt 0 ] || [ ${#running[@]} -gt 0 ]; do
  while [ ${#queue[@]} -gt 0 ] && { [ ${#running[@]} -eq 0 ] || [ $((used + $(peak "${queue[0]}"))) -le "$budget" ]; }; do
    launch "${queue[0]}" && running+=("${queue[0]}") && queue=("${queue[@]:1}")
  done
  pids=() && for c in "${running[@]}"; do pids+=("${pid[$c]}"); done
  ended= && wait -n -p ended "${pids[@]}" || true
  still=()
  for c in "${running[@]}"; do
    if [ "${pid[$c]}" = "$ended" ]; then
      used=$((used - $(peak "$c")))
      verdict "$c"
    else
      still+=("$c")
    fi
  done
  running=("${still[@]}")
done
if [ ${#BUILDS[@]} -gt 0 ]; then
  if wait "$builds_pid"; then echo "ok   ${BUILDS[*]}"; else echo "FAIL a build check: $builds_log" && failed=1; fi
fi
if [ -n "$LINT" ]; then
  if wait "$lint_pid"; then echo "ok   lint"; else echo "FAIL tests/lint.sh: $DIR/lint.log" && failed=1; fi
fi
echo "all in $(secs "$start")"
exit "$failed"
