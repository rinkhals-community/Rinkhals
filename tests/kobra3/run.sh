#!/bin/sh
# Runs every tests/kobra3/test_*.sh inside an alpine container (BusyBox ash).
# Usage (from the repo root): sh tests/kobra3/run.sh
# Exit 0 means all tests passed.

cd "$(dirname "$0")/../.." || exit 1

rc=0
for test in tests/kobra3/test_*.sh; do
    [ -f "$test" ] || continue
    echo "== $test"
    docker run --rm -v "$PWD":/src -w /src alpine sh "$test" || rc=1
done

[ "$rc" -eq 0 ] && echo "ALL PASSED" || echo "SOME TESTS FAILED"
exit "$rc"
