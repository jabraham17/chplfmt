"""Compare release-built revisions in an isolated worktree, without installing them."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from chplfmt._chapel import CHAPEL_VERSION
from conftest import _native_build_hash

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], **kwargs) -> None:
    subprocess.run(command, check=True, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", action="append", required=True, help="LABEL=REF")
    parser.add_argument("--work-dir", type=Path, required=True, help="new directory")
    parser.add_argument("--lapack", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--case", action="append", help="run only this named workload")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    revisions = []
    for spec in args.revision:
        label, separator, ref = spec.partition("=")
        if (
            not separator
            or not label
            or not ref
            or label == ".."
            or Path(label).name != label
        ):
            parser.error("each revision must be LABEL=REF with a simple label")
        revision = subprocess.check_output(
            ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=ROOT, text=True
        ).strip()
        revisions.append((label, revision))
    if len({label for label, _ in revisions}) != len(revisions):
        parser.error("revision labels must be unique")
    home = Path(os.environ["CHPL_HOME"])
    lapack = args.lapack.resolve(strict=True)
    cases = [
        ("LAPACK", [str(lapack)]),
        ("IO", [str(home / "modules/standard/IO.chpl")]),
        ("ChapelArray", [str(home / "modules/internal/ChapelArray.chpl")]),
        ("synthetic-5k", ["synthetic:5000"]),
        ("synthetic-25k", ["synthetic:25000"]),
        ("long-strings", ["long-strings"]),
        ("LAPACK-range", [str(lapack), "--range", "5000", "5005"]),
        ("synthetic-25k-range", ["synthetic:25000", "--range", "100", "105"]),
        ("ranges-20", ["ranges", "--warmup", "5", "--iterations", "20"]),
        (
            "whole-20",
            ["ranges", "--whole-file", "--warmup", "5", "--iterations", "20"],
        ),
    ]
    if args.case:
        unknown = set(args.case) - {name for name, _ in cases}
        if unknown:
            parser.error(f"unknown workloads: {sorted(unknown)}")
        cases = [(name, inputs) for name, inputs in cases if name in args.case]
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=False)
    checkout = work / "checkout"
    build_env = {
        **os.environ,
        "CARGO_BUILD_JOBS": "4",
        "CARGO_TARGET_DIR": str(work / "target"),
    }
    probe_env = {**os.environ, "PYTHONPATH": str(checkout / "src")}
    fingerprints: dict[str, tuple[str, str]] = {}
    run(
        ["git", "worktree", "add", "--detach", str(checkout), revisions[0][1]], cwd=ROOT
    )
    try:
        with (work / "measurements.jsonl").open("x") as output:
            for label, revision in revisions:
                run(["git", "checkout", "--detach", revision], cwd=checkout)
                wheels = work / "wheels" / label
                run(
                    [
                        sys.executable,
                        "-m",
                        "maturin",
                        "build",
                        "--release",
                        "--locked",
                        "--interpreter",
                        sys.executable,
                        "--manifest-path",
                        str(checkout / "native/py/Cargo.toml"),
                        "--out",
                        str(wheels),
                    ],
                    cwd=checkout,
                    env=build_env,
                )
                (wheel,) = wheels.glob("*.whl")
                with zipfile.ZipFile(wheel) as archive:
                    (extension,) = (
                        name
                        for name in archive.namelist()
                        if name.startswith("chplfmt/_native.") and name.endswith(".so")
                    )
                    (checkout / "src" / extension).write_bytes(archive.read(extension))
                native_hash = _native_build_hash(checkout / "native")
                for case, inputs in cases:
                    for repeat in range(1, args.repeats + 1):
                        proc = subprocess.run(
                            [
                                sys.executable,
                                str(ROOT / "tests/memory_probe.py"),
                                *inputs,
                            ],
                            cwd=checkout,
                            env=probe_env,
                            capture_output=True,
                            text=True,
                            timeout=300,
                        )
                        if proc.returncode:
                            raise RuntimeError(
                                f"{label}/{case}: {proc.stdout}{proc.stderr}"
                            )
                        row = json.loads(proc.stdout)
                        if row["native_build"] != native_hash:
                            raise RuntimeError(
                                f"{label}: wrong native extension loaded"
                            )
                        if row["chapel"] != CHAPEL_VERSION:
                            raise RuntimeError(f"{label}: Chapel version changed")
                        hashes = (row["input_sha256"], row["output_sha256"])
                        if fingerprints.setdefault(case, hashes) != hashes:
                            raise RuntimeError(f"{label}/{case}: input/output changed")
                        row.update(
                            stage=label, revision=revision, case=case, repeat=repeat
                        )
                        output.write(json.dumps(row) + "\n")
                        output.flush()
                        footprint = row["peak_footprint_bytes"]
                        print(
                            f"{label}/{case} #{repeat}: RSS "
                            f"{row['peak_rss_bytes'] / 1024**2:.1f} MiB, "
                            f"footprint {footprint / 1024**2 if footprint else None} MiB",
                            flush=True,
                        )
    finally:
        run(["git", "worktree", "remove", str(checkout)], cwd=ROOT)
    print(
        f"Verified identical input/output hashes; results: {work / 'measurements.jsonl'}"
    )


if __name__ == "__main__":
    main()
