"""Fresh-process, native-inclusive formatter memory measurements."""

from __future__ import annotations

import argparse
import ctypes
import gc
import hashlib
import json
import os
import platform
import resource
import sys
import time
from pathlib import Path

from chplfmt import _native
from chplfmt._chapel import CHAPEL_VERSION
from chplfmt.api import format_text
from unit.test_perf import synthetic


def peak_rss() -> int:
    scale = 1 if sys.platform == "darwin" else 1024
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * scale


def peak_footprint() -> int | None:
    if sys.platform != "darwin":
        return None

    # Darwin's rusage_info_v4 includes compressed pages in physical footprint.
    class Usage(ctypes.Structure):
        _fields_ = [
            ("uuid", ctypes.c_uint8 * 16),
            ("before_max", ctypes.c_uint64 * 28),
            ("lifetime_max_phys_footprint", ctypes.c_uint64),
            ("after_max", ctypes.c_uint64 * 6),
        ]

    info = Usage()
    lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    lib.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    lib.proc_pid_rusage.restype = ctypes.c_int
    if lib.proc_pid_rusage(os.getpid(), 4, ctypes.byref(info)) != 0:
        raise OSError(ctypes.get_errno(), "proc_pid_rusage")
    return info.lifetime_max_phys_footprint


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="file path, synthetic:LINE_COUNT, or ranges")
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=0)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--range", type=int, nargs=2, metavar=("FIRST", "LAST"))
    selection.add_argument("--whole-file", action="store_true")
    args = parser.parse_args()
    if args.iterations < 1 or args.warmup < 0:
        parser.error("iterations must be positive and warmup must be nonnegative")
    lines = (args.range[0], args.range[1]) if args.range is not None else None
    if lines is not None and not 1 <= lines[0] <= lines[1]:
        parser.error("range must have 1 <= FIRST <= LAST")
    if args.input.startswith("synthetic:"):
        source = synthetic(int(args.input.split(":")[1]))
        path = "Perf.chpl"
    elif args.input == "ranges":
        source = "/* hello\n world */\nvar values=[1,2,3];\n" + synthetic(1000)
        path = "Perf.chpl"
        if lines is None and not args.whole_file:
            lines = (1, 3)
    else:
        path = args.input
        with open(path, encoding="utf-8", newline="") as stream:
            source = stream.read()

    def once() -> str:
        result = format_text(source, path=path, lines=lines)
        digest = hashlib.sha256(result.text.encode()).hexdigest()
        del result
        gc.collect()
        return digest

    gc.collect()
    for _ in range(args.warmup):
        once()
    warmup_rss, warmup_footprint = peak_rss(), peak_footprint()
    start = time.perf_counter()
    output_hash = once()
    for _ in range(1, args.iterations):
        output_hash = once()
    elapsed = time.perf_counter() - start
    rss, footprint = peak_rss(), peak_footprint()
    print(
        json.dumps(
            {
                "input": Path(args.input).name,
                "input_bytes": len(source.encode()),
                "input_lines": source.count("\n"),
                "iterations": args.iterations,
                "warmup": args.warmup,
                "range": lines,
                "warmup_peak_rss_bytes": warmup_rss,
                "peak_rss_bytes": rss,
                "warmup_peak_footprint_bytes": warmup_footprint,
                "peak_footprint_bytes": footprint,
                "seconds": elapsed,
                "input_sha256": hashlib.sha256(source.encode()).hexdigest(),
                "output_sha256": output_hash,
                "python": platform.python_version(),
                "chapel": CHAPEL_VERSION,
                "platform": platform.platform(),
                "native_build": _native.__build__,
            }
        )
    )


if __name__ == "__main__":
    main()
