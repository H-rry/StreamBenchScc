import os
import reframe as rfm
import reframe.utility.sanity as sn
import reframe.utility.typecheck as typ

REPO = os.path.expanduser('~/stream-bench')
SCRIPTS = os.path.join(REPO, 'reframe', 'scripts')
KERNELS = ['Copy', 'Scale', 'Add', 'Triad']

BASE_CFLAGS = {
    'gnu': ['-O3', '-Wall', '-fopenmp', '-mcmodel=medium',
            '-march=native', '-mprefer-vector-width=512'],
    'intel': ['-O3', '-Wall', '-qopenmp', '-mcmodel=medium', '-shared-intel',
              '-xCORE-AVX512', '-qopt-zmm-usage=high',
              '-qopt-streaming-stores=always', '-ffreestanding'],
}


class build_stream(rfm.CompileOnlyRegressionTest):
    '''Builds the unmodified stream.c with the repo Makefile.'''
    build_system = 'Make'
    sourcesdir = None
    array_size = variable(int, value=1_000_000_000)
    ntimes = variable(int, value=10)
    offset = variable(int, value=0)
    extra_cflags = variable(typ.List[str], value=[])

    @run_before('compile')
    def set_flags(self):
        cc = self.current_environ.cc
        cflags = BASE_CFLAGS[self.current_environ.name] + self.extra_cflags
        defines = (f'-DSTREAM_ARRAY_SIZE={self.array_size} '
                   f'-DNTIMES={self.ntimes} -DOFFSET={self.offset}')
        # Copy only the source and Makefile in, so no stale ./stream binary is reused
        self.prebuild_cmds = [
            f'cp {REPO}/stream.c {REPO}/Makefile .',
            f'{cc} --version',
        ]
        self.build_system.cflags = cflags
        self.build_system.options = [f'DEFINES="{defines}"']
        meta = {
            'compiler': self.current_environ.name,
            'cflags': ' '.join(cflags),
            'defines': defines,
            'array_size': self.array_size,
            'ntimes': self.ntimes,
            'offset': self.offset,
        }
        self.postbuild_cmds = [
            f'echo "META {k}={v}" >> build_info.txt' for k, v in meta.items()
        ] + [
            f'echo "META compiler_version=$({cc} --version | head -1)" >> build_info.txt',
            'echo "META nt_stores=$(objdump -d stream | grep -c vmovnt)" >> build_info.txt',
            'echo "META stream_c_sha256=$(sha256sum stream.c | cut -d" " -f1)" >> build_info.txt',
            'cat build_info.txt',
        ]

    @sanity_function
    def validate_build(self):
        return sn.assert_found(r'META nt_stores=\d+', self.stdout)


@rfm.simple_test
class stream_bench(rfm.RunOnlyRegressionTest):
    valid_systems = ['*']
    valid_prog_environs = ['gnu', 'intel']
    stream_bin = fixture(build_stream, scope='environment')

    phase = variable(str, value='adhoc')
    num_threads = variable(int, value=64)
    proc_bind = variable(str, value='spread')   # 'unset' = no OMP binding at all
    places = variable(str, value='cores')
    numa = variable(str, value='none')          # none | node0 | node1 | cross
    os_tuned = variable(bool, value=False)
    num_tasks = 1

    @run_before('run')
    def setup_run(self):
        binary = os.path.join(self.stream_bin.stagedir, 'stream')
        numa_opts = {
            'none': [],
            'node0': ['--cpunodebind=0', '--membind=0'],
            'node1': ['--cpunodebind=1', '--membind=1'],
            'cross': ['--cpunodebind=0', '--membind=1'],
        }[self.numa]
        if numa_opts:
            self.executable = 'numactl'
            self.executable_opts = numa_opts + [binary]
        else:
            self.executable = binary

        # Request the whole node; OMP_NUM_THREADS sets the thread count
        self.num_cpus_per_task = 128
        self.env_vars = {'OMP_NUM_THREADS': str(self.num_threads),
                         'OMP_DISPLAY_ENV': 'true'}
        if self.proc_bind != 'unset':
            self.env_vars['OMP_PROC_BIND'] = self.proc_bind
            self.env_vars['OMP_PLACES'] = self.places

        run_meta = {
            'phase': self.phase, 'num_threads': self.num_threads,
            'proc_bind': self.proc_bind,
            'places': self.places if self.proc_bind != 'unset' else 'unset',
            'numa': self.numa, 'os_tuned': self.os_tuned,
        }
        self.prerun_cmds = [f'cat {self.stream_bin.stagedir}/build_info.txt']
        self.prerun_cmds += [f'echo "META {k}={v}"' for k, v in run_meta.items()]
        if self.os_tuned:
            self.prerun_cmds.append(f'sudo -n {SCRIPTS}/os_tune.sh apply')
            self.postrun_cmds = [f'sudo -n {SCRIPTS}/os_tune.sh restore']
        self.prerun_cmds.append(f'{SCRIPTS}/collect_meta.sh')

    @sanity_function
    def validate(self):
        return sn.all([
            sn.assert_found(r'Solution Validates', self.stdout),
            sn.assert_found(rf'Array size = {self.stream_bin.array_size} ',
                            self.stdout),
            sn.assert_eq(sn.extractsingle(r'Number of Threads counted = (\d+)',
                                          self.stdout, 1, int),
                         self.num_threads),
        ])

    @run_before('performance')
    def set_perf_vars(self):
        self.perf_variables = {
            k: sn.make_performance_function(
                sn.extractsingle(rf'{k}:\s+(\S+)', self.stdout, 1, float), 'MB/s')
            for k in KERNELS
        }
