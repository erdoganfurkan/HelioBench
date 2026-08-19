#!/usr/bin/env bash
# Forward to the heliobench CLI.
#
# Three resolutions, and each one is a trap that was hit before it was written down.
#
# The *code and the questions* come from this script's own location, never from the working
# directory: Claude moves the shell around, and a benchmark that scores whatever happens to
# sit in ./tasks silently changes its own question set. Installed as a plugin, that location
# is one pinned commit, which is exactly what a score should be attributed to.
#
# The *results* go where the user invoked it. A plugin's copy lives under the plugin cache and
# is erased on reinstall, so a report written beside the tasks is one the user loses.
#
# The *interpreter* is taken from a virtualenv only when that virtualenv really is here.
# Installing from a local path copies the whole tree, `.venv` included, and the copied console
# scripts keep an absolute shebang pointing back at the original repo — so trusting
# `.venv/bin/heliobench` would run the live repo's code against the snapshot's tasks and
# report the result as belonging to the snapshot's commit. Testing for the interpreter itself
# is what tells a real virtualenv from a copied one: the copy's symlink does not resolve.
set -euo pipefail

orig_pwd="$PWD"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../../../.." && pwd)"
cd "$repo"

if [ -n "${HELIOBENCH_PYTHON:-}" ]; then
    cli=("$HELIOBENCH_PYTHON" -m heliobench.cli)
elif [ -x "$repo/.venv/bin/python" ]; then
    cli=("$repo/.venv/bin/python" -m heliobench.cli)
elif command -v heliobench >/dev/null 2>&1; then
    cli=(heliobench)
else
    cat >&2 <<MSG
heliobench is not importable from $repo.

This is the installed-plugin copy, which ships the tasks but not a working virtualenv.
Either install the package where this shell can see it:

    pip install heliobench

or point at an existing environment:

    export HELIOBENCH_PYTHON=/path/to/venv/bin/python
MSG
    exit 127
fi

# Only for `run`, and only when the caller did not choose for themselves.
if [ "${1:-}" = "run" ] && [[ " $* " != *" --out "* ]]; then
    set -- "$@" --out "$orig_pwd/heliobench-results"
fi

exec "${cli[@]}" "$@"
