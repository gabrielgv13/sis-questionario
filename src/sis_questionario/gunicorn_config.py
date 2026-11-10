"""Configuration loaded by the master without importing database libraries."""
import math
import os
from pathlib import Path


def effective_cpus(root=Path('/sys/fs/cgroup'), membership=Path('/proc/self/cgroup')):
    """Minimum of affinity and visible cgroup v1/v2 quotas, including ancestors."""
    affinity = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else (
        os.process_cpu_count() or 1)
    limits = [float(affinity)]
    if 'WEB_CPU_CORES' in os.environ:
        configured = float(os.environ['WEB_CPU_CORES'])
        if not math.isfinite(configured) or configured <= 0:
            raise ValueError('WEB_CPU_CORES deve ser positivo e finito.')
        limits.append(configured)
    directories = {root, root / 'cpu', root / 'cpu,cpuacct'}
    try:
        for line in membership.read_text().splitlines():
            _, controllers, relative = line.split(':', 2)
            if controllers == '' or 'cpu' in controllers.split(','):
                bases = [root] if controllers == '' else [root / 'cpu', root / 'cpu,cpuacct']
                for base in bases:
                    directory = base / relative.lstrip('/')
                    if '..' not in directory.parts:
                        directories.update([directory, *[p for p in directory.parents if p.is_relative_to(base)]])
    except (OSError, ValueError):
        pass
    for directory in directories:
        try:
            quota, period = (directory / 'cpu.max').read_text().split()
            if quota != 'max' and int(quota) > 0 and int(period) > 0:
                limits.append(int(quota) / int(period))
        except (OSError, ValueError):
            pass
        try:
            quota = int((directory / 'cpu.cfs_quota_us').read_text())
            period = int((directory / 'cpu.cfs_period_us').read_text())
            if quota > 0 and period > 0:
                limits.append(quota / period)
        except (OSError, ValueError):
            pass
    return min(limits)


def default_workers():
    # Floor the final cores + 1 result: 0.1 CPU -> floor(1.1) -> 1 worker.
    return max(1, math.floor(effective_cpus() + 1))


workers = int(os.environ['WEB_WORKERS']) if 'WEB_WORKERS' in os.environ else default_workers()
if workers < 1:
    raise ValueError('WEB_WORKERS deve ser positivo.')
worker_class = 'gevent'
worker_connections = 64
preload_app = False


def post_worker_init(worker):
    from gevent import monkey
    if not all(monkey.is_module_patched(name) for name in ('select', 'threading', 'queue')):
        raise RuntimeError('O pool exige gevent com monkey patch antes da inicialização.')
    from .database_pool import iniciar_pool
    iniciar_pool()


def worker_exit(server, worker):
    from .database_pool import fechar_pool
    fechar_pool()
