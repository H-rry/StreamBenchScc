#!/bin/bash
# STREAM tuning campaign. Every run is queued through Slurm (--exclusive),
# so nothing overlaps other jobs. Each phase is its own ReFrame session under
# runs/<timestamp>_<phase>/ so no run ever overwrites another.
#
# usage: run_campaign.sh [--quick] [phase ...]
#   default phases (priority order): baseline gnu_pinned icx_pinned threads
#                                    numa os_tuned sizes flags ht
#   headline: needs HEADLINE_ARGS, e.g.
#     HEADLINE_ARGS="-p intel -S stream_bench.os_tuned=true" run_campaign.sh headline
set -uo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
RFM="$REPO/rfm-venv/bin/reframe"
TUNE="$REPO/reframe/scripts/os_tune.sh"
mkdir -p "$REPO/runs"
LOG="$REPO/runs/campaign.log"

QUICK=0
if [ "${1:-}" = "--quick" ]; then QUICK=1; shift; fi
PHASES=("$@")
[ ${#PHASES[@]} -eq 0 ] && PHASES=(baseline gnu_pinned icx_pinned threads numa os_tuned sizes flags ht)

# Make sure OS settings are always put back, however the campaign ends
trap 'sudo -n "$TUNE" restore >> "$LOG" 2>&1' EXIT

reps() { [ $QUICK -eq 1 ] && echo "$2" || echo "$1"; }   # reps <full> <quick>

session() {  # session <name> <reframe args...>
    local name=$1; shift
    local dir="$REPO/runs/$(date +%Y%m%d-%H%M%S)_$name"
    echo "[$(date -Is)] START $name: $*" >> "$LOG"
    "$RFM" -C "$REPO/reframe/config.py" -c "$REPO/reframe/stream_test.py" \
        --system=scc-node:slurm -r --exec-policy=serial \
        --prefix "$dir" --report-file "$dir/report.json" \
        -S stream_bench.phase="$name" "$@" > "$dir.log" 2>&1
    local rc=$?
    echo "[$(date -Is)] END   $name (exit $rc) -> $(grep -E 'PASSED|FAILED' "$dir.log" | tail -1)" >> "$LOG"
}

for phase in "${PHASES[@]}"; do
    case $phase in
    baseline)    # the original setup (unpinned, all 128 hyperthreads) at 1e9
        session baseline -p gnu -S stream_bench.proc_bind=unset \
            -S stream_bench.num_threads=128 --repeat "$(reps 5 3)" ;;
    gnu_pinned)
        session gnu_pinned -p gnu --repeat "$(reps 10 5)" ;;
    icx_pinned)
        session icx_pinned -p intel --repeat "$(reps 10 5)" ;;
    threads)
        if [ $QUICK -eq 1 ]; then
            session threads -p intel -P stream_bench.num_threads=1,4,16,32,64
        else
            session threads -p intel -P stream_bench.num_threads=1,2,4,8,16,24,32,48,64 \
                -P stream_bench.proc_bind=spread,close --repeat 3
            session threads_gnu -p gnu -P stream_bench.num_threads=1,2,4,8,16,24,32,48,64 \
                --repeat 3
        fi ;;
    numa)        # one socket alone (vs 332.8 GB/s) and the cross-socket penalty
        session numa -p intel -S stream_bench.num_threads=32 \
            -P stream_bench.numa=node0,node1,cross --repeat "$(reps 5 2)" ;;
    os_tuned)
        session os_tuned -S stream_bench.os_tuned=true --repeat "$(reps 10 5)" ;;
    sizes)       # exploratory: cache-resident sizes break the STREAM run rules
        if [ $QUICK -eq 1 ]; then sizes="1000000 10000000 100000000 1000000000"
        else sizes="1000000 3000000 10000000 30000000 100000000 300000000 1000000000 2000000000"; fi
        for n in $sizes; do
            nt=10; [ "$n" -le 10000000 ] && nt=200
            session "sizes_$n" -p intel -S stream_bench.stream_bin.array_size="$n" \
                -S stream_bench.stream_bin.ntimes=$nt --repeat "$(reps 3 1)"
        done ;;
    flags)
        [ $QUICK -eq 1 ] && continue
        session flags_ntimes100 -p intel -S stream_bench.stream_bin.ntimes=100 --repeat 5
        session flags_offset -p intel -S stream_bench.stream_bin.offset=1032 --repeat 5
        session flags_gnu_nomemcpy -p gnu \
            -S stream_bench.stream_bin.extra_cflags=-fno-tree-loop-distribute-patterns --repeat 5 ;;
    ht)
        [ $QUICK -eq 1 ] && continue
        session ht -p intel -S stream_bench.num_threads=128 \
            -S stream_bench.places=threads --repeat 5 ;;
    headline)
        # shellcheck disable=SC2086
        session headline ${HEADLINE_ARGS:?set HEADLINE_ARGS to the best config} --repeat 20 ;;
    *) echo "unknown phase: $phase" >> "$LOG" ;;
    esac
done
echo "[$(date -Is)] campaign done" >> "$LOG"
