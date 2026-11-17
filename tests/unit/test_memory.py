"""Run serially: subprocess peaks include Python, Rust, and Chapel allocations."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = [
    pytest.mark.memory,
    pytest.mark.skipif(
        sys.platform not in {"darwin", "linux"}, reason="requires Unix memory counters"
    ),
]

MIB = 1024 * 1024
PROBE = Path(__file__).resolve().parents[1] / "memory_probe.py"


def measure(*args: str) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(PROBE), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    print(json.dumps(result, sort_keys=True))
    return result


def test_large_file_peak_memory() -> None:
    result = measure("synthetic:25000")
    assert result["input_lines"] >= 25000
    peak = max(result["peak_rss_bytes"], result["peak_footprint_bytes"] or 0)
    assert peak < 512 * MIB, f"peak memory: {peak / MIB:.1f} MiB"


def test_repeated_ranges_memory_growth() -> None:
    # Some chapel-py versions retain native parser memory even without ranges.
    # Compare identical inputs to isolate additional range-specific retention.
    control = measure("ranges", "--whole-file", "--warmup", "5", "--iterations", "20")
    result = measure("ranges", "--warmup", "5", "--iterations", "20")
    metric = "footprint" if sys.platform == "darwin" else "rss"
    before = result[f"warmup_peak_{metric}_bytes"]
    after = result[f"peak_{metric}_bytes"]
    control_growth = (
        control[f"peak_{metric}_bytes"] - control[f"warmup_peak_{metric}_bytes"]
    )
    assert result["input_sha256"] == control["input_sha256"]
    assert (
        after - before - control_growth < 24 * MIB
    ), f"extra range {metric} growth: {(after - before - control_growth) / MIB:.1f} MiB"
    for row in (control, result):
        assert max(row["peak_rss_bytes"], row["peak_footprint_bytes"] or 0) < 384 * MIB
