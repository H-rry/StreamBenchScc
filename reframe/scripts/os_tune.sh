#!/bin/bash
# OS tuning for STREAM: show | apply | restore. Run with sudo.
# apply saves the current values first; restore writes them back.
set -euo pipefail
STATE=/home/nvidia/stream-bench/runs/.os_tune_state
cpu=/sys/devices/system/cpu
unc=$cpu/intel_uncore_frequency
THP=/sys/kernel/mm/transparent_hugepage/enabled

show() {
    echo "governor=$(cat $cpu/cpu0/cpufreq/scaling_governor)"
    for d in $unc/package_*; do
        echo "uncore_$(basename $d)=$(cat $d/min_freq_khz):$(cat $d/max_freq_khz)"
    done
    echo "thp=$(sed 's/.*\[\(.*\)\].*/\1/' $THP)"
    echo "numa_balancing=$(cat /proc/sys/kernel/numa_balancing)"
    echo "c6_disabled=$(cat $cpu/cpu0/cpuidle/state3/disable)"
}

set_cstate() {  # $1 = 0 (enable) or 1 (disable) for C6 (state3)
    for f in $cpu/cpu*/cpuidle/state3/disable; do echo "$1" > "$f"; done
}

case "${1:-show}" in
show) show ;;
apply)
    mkdir -p "$(dirname $STATE)"
    [ -f "$STATE" ] || show > "$STATE"   # never overwrite the original values
    for g in $cpu/cpu*/cpufreq/scaling_governor; do echo performance > "$g"; done
    for d in $unc/package_*; do
        echo 2500000 > $d/max_freq_khz
        echo 2500000 > $d/min_freq_khz
    done
    echo always > $THP
    echo 0 > /proc/sys/kernel/numa_balancing
    set_cstate 1
    echo "os_tune: applied"; show ;;
restore)
    [ -f "$STATE" ] || { echo "os_tune: nothing to restore"; exit 0; }
    gov=$(grep '^governor=' $STATE | cut -d= -f2)
    for g in $cpu/cpu*/cpufreq/scaling_governor; do echo "$gov" > "$g"; done
    for d in $unc/package_*; do
        v=$(grep "^uncore_$(basename $d)=" $STATE | cut -d= -f2)
        echo "${v%%:*}" > $d/min_freq_khz
        echo "${v##*:}" > $d/max_freq_khz
    done
    grep '^thp=' $STATE | cut -d= -f2 > $THP
    grep '^numa_balancing=' $STATE | cut -d= -f2 > /proc/sys/kernel/numa_balancing
    set_cstate "$(grep '^c6_disabled=' $STATE | cut -d= -f2)"
    rm -f "$STATE"
    echo "os_tune: restored"; show ;;
*) echo "usage: $0 show|apply|restore"; exit 1 ;;
esac
