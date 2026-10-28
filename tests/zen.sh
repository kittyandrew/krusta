# shellcheck shell=bash
# Sourced, not run: a headless Zen of krusta's own, apart from Andrew's, signed in to krusta's sites with a copy of
# his cookies for them and driven over WebDriver with curl. .claude/rules/004-zen.md says how to use it.
K=$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd) # $0 when zsh sources it
ZEN_DIR=${ZEN_DIR:-$XDG_RUNTIME_DIR/krusta-zen} # tmpfs only this user reads: it holds a live session
ZEN_SHOTS=${ZEN_SHOTS:-$ZEN_DIR/shots} # pictures of the signed-in feed: gone with the profile at zen_stop
WD=http://127.0.0.1:4445 # geckodriver; Zen's own Marionette listens on 2829
PKGS="(builtins.getFlake \"git+file://$K\").inputs.nixpkgs.legacyPackages.\${builtins.currentSystem}"
PATH=$(nix build --impure --no-link --print-out-paths --expr "with $PKGS; buildEnv {
  name = \"krusta-zen-tools\"; paths = [geckodriver sqlite];
}")/bin:$PATH

# Starts Zen and its driver as user units, opens the WebDriver session and installs krusta: the staged .#extension,
# or the unpacked add-on named. A fresh profile each time, so no cache or service worker carries over between runs.
zen_start() {
  local own hosts session='' extension=${1:-$(nix build "$K#extension" --no-link --print-out-paths)}
  hosts=$(jq -rn '[inputs.hosts[] | ., "." + .] | map(@sh) | join(", ")' "$K"/sites/*/site.json) # 'x.com', '.x.com'
  # The profile Andrew uses, whose cookies changed last: profiles.ini's [Install] default names a stale one.
  own=$(find ~/.zen -maxdepth 2 -name cookies.sqlite -printf '%T@ %h\n' | sort -n | tail -1 | cut -d' ' -f2-)
  zen_stop 2>/dev/null
  mkdir -m 700 "$ZEN_DIR" && mkdir "$ZEN_DIR"/{profile,tmp,downloads} && mkdir -m 700 "$ZEN_SHOTS"
  cp "$own/cookies.sqlite" "$own/cookies.sqlite-wal" "$ZEN_DIR/tmp/" # the WAL holds Zen's newest writes
  # Exclusive, as Zen opens it: its WAL has no shared-memory file, and a normal open reports "database is locked".
  sqlite3 "$ZEN_DIR/tmp/cookies.sqlite" >/dev/null \
    "PRAGMA locking_mode = EXCLUSIVE; DELETE FROM moz_cookies WHERE host NOT IN ($hosts); VACUUM;"
  mv "$ZEN_DIR/tmp/cookies.sqlite" "$ZEN_DIR/profile/" && rm -f "$ZEN_DIR"/tmp/cookies.sqlite{-wal,-shm}
  cat >"$ZEN_DIR/profile/user.js" <<EOF
user_pref("marionette.port", 2829);
user_pref("browser.download.dir", "$ZEN_DIR/downloads");
user_pref("browser.download.folderList", 2);
user_pref("browser.download.useDownloadDir", true);
EOF
  # TMPDIR is where Zen writes memory reports (sites/kitter/tests/bench/memory.py).
  systemd-run --user -q --unit=krusta-zen --collect -p MemoryMax=6G -p MemorySwapMax=0 --setenv=TMPDIR="$ZEN_DIR/tmp" \
    --setenv=MOZ_HEADLESS_WIDTH=1920 --setenv=MOZ_HEADLESS_HEIGHT=1080 \
    "$(command -v zen-twilight)" --headless --no-remote --marionette --remote-allow-system-access --profile "$ZEN_DIR/profile"
  # geckodriver rejects Zen's binary, so it attaches to the running Zen instead of starting one.
  systemd-run --user -q --unit=krusta-zen-driver --collect "$(command -v geckodriver)" --connect-existing \
    --marionette-port 2829 --port "${WD##*:}"
  for _ in $(seq 60); do
    session=$(curl -sS -m 10 -H 'content-type: application/json' -d '{"capabilities": {"alwaysMatch": {"pageLoadStrategy": "none"}}}' \
      "$WD/session" 2>/dev/null | jq -r '.value.sessionId // empty') && [[ -n $session ]] && break
    sleep 1
  done
  [[ -n $session ]] || { echo "no WebDriver session within 60 s" >&2 && return 1; }
  echo "$session" >"$ZEN_DIR/session"
  addon "$extension" >/dev/null
}
zen_stop() { systemctl --user stop krusta-zen-driver krusta-zen 2>/dev/null || true; rm -rf "$ZEN_DIR"; } # under set -e too
zen_pid() { systemctl --user show -p MainPID --value krusta-zen; } # the wrapper execs Zen, keeping its pid

# One WebDriver call in the session (w3c.github.io/webdriver): `wd GET /url`. Prints the answer's value.
wd() {
  local body=()
  [[ -z ${3-} ]] || body=(-H 'content-type: application/json' -d "$3")
  curl -sS -m 120 -X "$1" "$WD/session/$(<"$ZEN_DIR/session")$2" "${body[@]}" | jq .value # a hung tab fails, not waits
}
# A function body run in the current tab, its value as JSON; a returned promise is awaited: `js 'return 1 + 1'`.
js() { wd POST /execute/sync "$(jq -nc --arg s "$1" '{script: $s, args: []}')"; }
# A URL in the current tab, then a wait for it to draw: WebDriver never sees a krusta page finish loading.
go() { wd POST /url "$(jq -nc --arg u "$1" '{url: $u}')" >/dev/null && sleep "${2:-4}"; }
shot() { (umask 077 && wd GET /screenshot | jq -r . | base64 -d >"$ZEN_SHOTS/$1.png") && echo "$ZEN_SHOTS/$1.png"; }
# krusta's toolbar button, clicked in the browser's own window (WebDriver's chrome context, which
# --remote-allow-system-access opens), then back to the page.
button() {
  wd POST /window "{\"handle\": $(wd GET /window)}" >/dev/null # selects the session's tab: the button acts on the selected one
  wd POST /moz/context '{"context": "chrome"}' >/dev/null
  js 'document.getElementById("krusta_kittyandrew-BAP").click()' >/dev/null # the button inside the toolbar item
  wd POST /moz/context '{"context": "content"}' >/dev/null
}
# A temporary add-on, from an unpacked folder or an .xpi; it is gone with the profile at zen_stop.
addon() { wd POST /moz/addon/install "$(jq -nc --arg p "$1" '{path: $p, temporary: true}')"; }
