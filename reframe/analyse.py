#!/usr/bin/env python3
'''Collect every STREAM run under runs/ into Excel-friendly CSVs.

  runs/csv/runs.csv     one row per run (every raw rfm_job.out found)
  runs/csv/summary.csv  one row per configuration: run count, spread, % of peak

Raw output files are only read, never modified.
'''
import csv
import os
import re
import statistics as st
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(REPO, 'runs')
OUT = os.path.join(RUNS, 'csv')

KERNELS = ['Copy', 'Scale', 'Add', 'Triad']
PEAK_NODE_GBS = 665.6       # 2 sockets x 8 ch x 5200 MT/s x 8 B
PEAK_SOCKET_GBS = 332.8
CACHE_BYTES = 248 * 2**20   # L2 (128 MiB) + L3 (120 MiB), non-inclusive

TABLE_RE = re.compile(
    r'^(Copy|Scale|Add|Triad):\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)', re.M)
CONFIG_KEYS = ['phase', 'compiler', 'cflags', 'array_size', 'ntimes', 'offset',
               'num_threads', 'proc_bind', 'places', 'numa', 'os_tuned']


def parse_run(path):
    text = open(path, errors='replace').read()
    meta = {}
    for line in text.splitlines():
        if line.startswith('META ') and '=' in line:
            k, v = line[5:].split('=', 1)
            meta[k.strip()] = v.strip()
    table = {m[0]: m[1:] for m in TABLE_RE.findall(text)}
    if not table:
        return None

    n = int(meta.get('array_size', 0) or 0)
    peak = PEAK_NODE_GBS if meta.get('numa', 'none') == 'none' else PEAK_SOCKET_GBS
    row = {
        'phase': meta.get('phase', ''),
        'date': meta.get('date', ''),
        'slurm_job_id': meta.get('slurm_job_id', ''),
        'compiler': meta.get('compiler', ''),
        'compiler_version': meta.get('compiler_version', ''),
        'cflags': meta.get('cflags', ''),
        'nt_stores_in_binary': meta.get('nt_stores', ''),
        'array_size': n,
        'gib_per_array': round(8 * n / 2**30, 3),
        'gib_total': round(24 * n / 2**30, 3),
        'array_x_cache': round(8 * n / CACHE_BYTES, 2),
        'ntimes': meta.get('ntimes', ''),
        'offset': meta.get('offset', ''),
        'num_threads': meta.get('num_threads', ''),
        'proc_bind': meta.get('proc_bind', ''),
        'places': meta.get('places', ''),
        'numa': meta.get('numa', ''),
        'os_tuned': meta.get('os_tuned', ''),
        'governor': meta.get('governor', ''),
        'uncore_min_khz': meta.get('uncore_min_khz', ''),
        'uncore_max_khz': meta.get('uncore_max_khz', ''),
        'thp': meta.get('thp', ''),
        'numa_balancing': meta.get('numa_balancing', ''),
        'cstates_disabled': meta.get('cstates_disabled', ''),
        'loadavg_before': meta.get('loadavg', ''),
        'other_jobs': meta.get('other_jobs', ''),
        'peak_gbs': peak,
        'validated': 'Solution Validates' in text,
    }
    for k in KERNELS:
        rate, avg, mn, mx = (float(x) for x in table.get(k, (0, 0, 0, 0)))
        row[f'{k}_GBs'] = round(rate / 1000, 2)
        row[f'{k}_pct_peak'] = round(100 * rate / 1000 / peak, 2)
        row[f'{k}_avg_s'] = avg
        row[f'{k}_min_s'] = mn
        row[f'{k}_max_s'] = mx
    row['raw_file'] = os.path.relpath(path, REPO)
    return row


def find_runs():
    for root, _, files in os.walk(RUNS):
        if 'rfm_job.out' in files and f'{os.sep}output{os.sep}' in root + os.sep:
            yield os.path.join(root, 'rfm_job.out')


def summarise(rows):
    groups = defaultdict(list)
    for r in rows:
        groups[tuple(r[k] for k in CONFIG_KEYS)].append(r)

    out = []
    for key, rs in groups.items():
        s = dict(zip(CONFIG_KEYS, key))
        s['runs'] = len(rs)
        s['all_validated'] = all(r['validated'] for r in rs)
        s['first_date'] = min(r['date'] for r in rs)
        s['last_date'] = max(r['date'] for r in rs)
        peak = rs[0]['peak_gbs']
        s['peak_gbs'] = peak
        for k in KERNELS:
            v = [r[f'{k}_GBs'] for r in rs]
            sd = st.stdev(v) if len(v) > 1 else 0.0
            s[f'{k}_best'] = max(v)
            s[f'{k}_median'] = round(st.median(v), 2)
            s[f'{k}_mean'] = round(st.mean(v), 2)
            s[f'{k}_min'] = min(v)
            s[f'{k}_stdev'] = round(sd, 2)
            s[f'{k}_cov_pct'] = round(100 * sd / st.mean(v), 2) if st.mean(v) else 0
            s[f'{k}_best_pct_peak'] = round(100 * max(v) / peak, 2)
            s[f'{k}_median_pct_peak'] = round(100 * st.median(v) / peak, 2)
        out.append(s)
    return sorted(out, key=lambda s: s['first_date'])


def write_csv(path, rows):
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    rows = [r for r in (parse_run(p) for p in find_runs()) if r]
    if not rows:
        sys.exit(f'no STREAM runs found under {RUNS}')
    rows.sort(key=lambda r: r['date'])
    summary = summarise(rows)
    os.makedirs(OUT, exist_ok=True)
    write_csv(os.path.join(OUT, 'runs.csv'), rows)
    write_csv(os.path.join(OUT, 'summary.csv'), summary)

    print(f'{len(rows)} runs, {len(summary)} configurations -> {OUT}/')
    print(f'{"phase":<14}{"cc":<6}{"thr":>4} {"bind":<7}{"numa":<6}{"tuned":<6}'
          f'{"N":>11}{"runs":>5}{"Triad best":>11}{"median":>8}{"CoV%":>6}{"%peak":>7}')
    for s in summary:
        print(f'{s["phase"]:<14}{s["compiler"]:<6}{s["num_threads"]:>4} '
              f'{s["proc_bind"]:<7}{s["numa"]:<6}{s["os_tuned"]:<6}'
              f'{s["array_size"]:>11}{s["runs"]:>5}{s["Triad_best"]:>11}'
              f'{s["Triad_median"]:>8}{s["Triad_cov_pct"]:>6}'
              f'{s["Triad_best_pct_peak"]:>7}')


if __name__ == '__main__':
    main()
