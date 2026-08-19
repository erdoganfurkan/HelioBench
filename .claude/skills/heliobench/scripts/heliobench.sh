#!/usr/bin/env bash
# Forward to the heliobench CLI.
#
# Two resolutions matter here, and they pull in opposite directions.
#
# The *code and the questions* come from this script's own location, never from the working
# directory: Claude moves the shell around, and a benchmark that scores whatever happens to
# sit in ./tasks silently changes its own question set. When this ships as an installed
# plugin, that location is a snapshot of one commit, which is exactly what you want a score
# attributed to.
#
# The *results* go where the user invoked it. A plugin's snapshot lives under the plugin
# cache and is erased on reinstall, so a report written beside the tasks would be a report
# the user loses the first time they update.
set -euo pipefail

orig_pwd="$PWD"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../../../.." && pwd)"
cd "$repo"

if [ -x "$repo/.venv/bin/heliobench" ]; then
    cli=("$repo/.venv/bin/heliobench")
elif command -v heliobench >/dev/null 2>&1; then
    cli=(heliobench)
else
    echo "heliobench is not installed. From $repo run:  pip install -e '.[dev]'" >&2
    exit 127
fi

# Only for `run`, and only when the caller did not choose for themselves.
if [ "${1:-}" = "run" ] && [[ " $* " != *" --out "* ]]; then
    set -- "$@" --out "$orig_pwd/heliobench-results"
fi

exec "${cli[@]}" "$@"
