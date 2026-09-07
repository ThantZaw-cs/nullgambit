#!/usr/bin/env bash
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
output="${1:-$root/artifacts/nullgambit-numba-review.zip}"
mkdir -p "$(dirname "$output")"
git -C "$root" archive --format=zip --output="$output" HEAD
sha256sum "$output" >"$output.sha256"
printf 'review archive: %s\n' "$output"
