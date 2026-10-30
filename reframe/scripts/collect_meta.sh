#!/bin/bash
# Prints the run environment as "META key=value" lines into the STREAM output.
m() { echo "META $1=$2"; }
cpu=/sys/devices/system/cpu
unc=$cpu/intel_uncore_frequency
m date "$(date -Is)"
m hostname "$(hostname)"
m slurm_job_id "${SLURM_JOB_ID:-none}"
m nproc "$(env -u OMP_NUM_THREADS -u OMP_THREAD_LIMIT nproc)"
m affinity "$(taskset -cp $$ | awk -F': ' '{print $2}')"
m loadavg "$(cut -d' ' -f1-3 /proc/loadavg)"
m governor "$(cat $cpu/cpu0/cpufreq/scaling_governor)"
m uncore_min_khz "$(cat $unc/package_00_die_00/min_freq_khz)"
m uncore_max_khz "$(cat $unc/package_00_die_00/max_freq_khz)"
m thp "$(sed 's/.*\[\(.*\)\].*/\1/' /sys/kernel/mm/transparent_hugepage/enabled)"
m numa_balancing "$(cat /proc/sys/kernel/numa_balancing)"
m cstates_disabled "$(for s in $cpu/cpu0/cpuidle/state*; do echo -n "$(cat $s/name):$(cat $s/disable) "; done)"
m omp_env "$(env | grep -E '^OMP_' | sort | tr '\n' ' ')"
m other_jobs "$(squeue -h -o '%i:%j:%T' | grep -v "^${SLURM_JOB_ID:-x}:" | tr '\n' ' ')"
