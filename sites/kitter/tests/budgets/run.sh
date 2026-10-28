#!/usr/bin/env bash
# DEVELOPMENT ONLY: the speed budgets of docs/design.md (Speed), measured on this machine in a headless Firefox with
# the staged build, or the unpacked add-on named. Not a flake check and never run in a VM, which kubicle measured
# two to five times slower. Run it alone on a quiet machine; it exits 1 when a budget is missed.
#
#   sites/kitter/tests/budgets/run.sh                 # the staged .#extension
#   sites/kitter/tests/budgets/run.sh <extension dir> # another build, to compare or to plant a slowdown
#
# The fake x.com it measures against listens on port 443, so budgets.py runs in a user and network namespace of
# its own (unshare), where it is root and nothing reaches the real x.com.
set -euo pipefail
K=$(cd "$(dirname "$0")/../../../.." && pwd)
EXTENSION=${1:-$(nix build "$K#extension" --no-link --print-out-paths)}
# The flake's own nixpkgs, read from git's index as every build here is, for Firefox, its driver and the fixture.
PKGS="(builtins.getFlake \"git+file://$K\").inputs.nixpkgs.legacyPackages.\${builtins.currentSystem}"
# From vm-kitter's fixture: twscrape's recorded list timeline (MIT), the same entries and tweet shape as HomeTimeline
# with about 90 posts a page, and the certificate for X's names that its fake X serves.
TIMELINE=$(nix build --no-link --print-out-paths "$K#checks.x86_64-linux.vm-kitter.fixture.recorded")
TLS=$(nix build --no-link --print-out-paths "$K#checks.x86_64-linux.vm-kitter.fixture.tls")
nix shell --impure --expr "with $PKGS; [firefox geckodriver (python3.withPackages (p: [p.selenium])) iproute2]" -c \
  unshare --map-root-user --net sh -c 'ip link set lo up && exec python3 -I "$@"' - \
  "$K/sites/kitter/tests/budgets/budgets.py" "$EXTENSION" "$TIMELINE" "$TLS"
