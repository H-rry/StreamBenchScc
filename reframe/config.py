ONEAPI = '/opt/intel/oneapi/compiler/2026.1'

site_configuration = {
    'systems': [{
        'name': 'scc-node',
        'descr': '2x Xeon Gold 6548Y+, 1 TB DDR5-5200',
        'hostnames': ['.*'],
        'partitions': [
            {
                'name': 'local', 'scheduler': 'local', 'launcher': 'local',
                'environs': ['gnu', 'intel'], 'max_jobs': 1,
            },
            {   # queue through Slurm with the whole node so STREAM never overlaps other jobs
                'name': 'slurm', 'scheduler': 'squeue', 'launcher': 'local',
                'access': ['--exclusive', '--partition=partition'],
                'environs': ['gnu', 'intel'], 'max_jobs': 1,
                'time_limit': '10m',
            },
        ],
    }],
    'environments': [
        {'name': 'gnu', 'cc': 'gcc', 'features': ['openmp']},
        {
            'name': 'intel', 'cc': 'icx', 'features': ['openmp'],
            'env_vars': [
                ['PATH', f'{ONEAPI}/bin:$PATH'],
                ['LD_LIBRARY_PATH', f'{ONEAPI}/lib:$LD_LIBRARY_PATH'],
            ],
        },
    ],
}
