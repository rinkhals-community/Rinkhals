# The free space check reads the Available column, check_compatibility rejects an unknown model
. tests/kobra3/lib.sh
. files/3-rinkhals/tools.sh 2> /dev/null

WORK=$(mktemp -d)

# free_space_kb with a fake df
mkdir $WORK/bin
cat > $WORK/bin/df <<'DF'
#!/bin/sh
echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
echo "/dev/x 1000000 900000 100000 90% /useremain"
DF
chmod +x $WORK/bin/df
OLD_PATH=$PATH
PATH=$WORK/bin:$PATH
assert_eq 100000 "$(free_space_kb /useremain)" "free_space_kb: prints the Available column"
PATH=$OLD_PATH

# check_compatibility with quit() counting its calls instead of exiting
QUIT_CALLS=0
quit() {
    QUIT_CALLS=$((QUIT_CALLS + 1))
}

KOBRA_MODEL_CODE=K3
check_compatibility > /dev/null
assert_eq 0 $QUIT_CALLS "check_compatibility (K3): does not quit"

QUIT_CALLS=0
KOBRA_MODEL_CODE=
check_compatibility > /dev/null
assert_eq 1 $QUIT_CALLS "check_compatibility (unknown model): quits once"

rm -rf $WORK
finish
