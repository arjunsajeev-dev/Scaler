"""CPU percent is derived from consecutive samples, not precpu_stats."""

from scaler.collectors.docker_stats import cpu_percent_from_delta, parse_cpu_sample
from scaler.models import CpuSample


def test_cpu_percent_from_delta():
    prev = CpuSample(total_usage=100, system_cpu_usage=1_000, online_cpus=2)
    curr = CpuSample(total_usage=300, system_cpu_usage=2_000, online_cpus=2)
    pct = cpu_percent_from_delta(prev, curr)
    assert pct == (200 / 1_000) * 2 * 100.0


def test_warmup_zero_system_delta_returns_none():
    prev = CpuSample(total_usage=100, system_cpu_usage=1_000, online_cpus=2)
    curr = CpuSample(total_usage=100, system_cpu_usage=1_000, online_cpus=2)
    assert cpu_percent_from_delta(prev, curr) is None


def test_parse_cpu_sample_ignores_precpu_stats():
    stats = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 500, "percpu_usage": [250, 250]},
            "system_cpu_usage": 10_000,
            "online_cpus": 2,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 0},
            "system_cpu_usage": 0,
        },
    }
    sample = parse_cpu_sample(stats)
    assert sample is not None
    assert sample.total_usage == 500
    assert sample.system_cpu_usage == 10_000
    assert sample.online_cpus == 2
