# Minimal assertion helpers for the kobra3 shell tests (POSIX sh / BusyBox ash).
# Source this file, call the asserts, then end the test with `finish`.

KOBRA3_TEST_FAILURES=0

assert_eq() {
    if [ "$1" = "$2" ]; then
        echo "ok   - $3"
    else
        echo "FAIL - $3 (expected '$1', got '$2')"
        KOBRA3_TEST_FAILURES=$((KOBRA3_TEST_FAILURES + 1))
    fi
}

assert_file_md5() {
    if [ -f "$1" ]; then
        actual=$(md5sum "$1" | awk '{print $1}')
    else
        actual="<missing>"
    fi
    assert_eq "$2" "$actual" "$3"
}

finish() {
    if [ "$KOBRA3_TEST_FAILURES" -ne 0 ]; then
        echo "$KOBRA3_TEST_FAILURES failure(s)"
        exit 1
    fi
    exit 0
}
