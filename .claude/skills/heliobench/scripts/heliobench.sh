#!/usr/bin/env bash
# Forward to the heliobench CLI, preferring the repo's own virtualenv.
#
# Resolves the repo from this script's location rather than the working directory: Claude
# moves the shell around, and a benchmark that scores whatever happens to be in `cwd/tasks`
# is a benchmark that silently changes its own question set.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../../../.." && pwd)"
cd "$repo"

if [ -x "$repo/.venv/bin/heliobench" ]; then
    exec "$repo/.venv/bin/heliobench" "$@"
elif command -v heliobench >/dev/null 2>&1; then
    exec heliobench "$@"
else
    echo "heliobench is not installed. From $repo run:  pip install -e '.[dev]'" >&2
    exit 127
fi
