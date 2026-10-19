"""Render the generated OpenSCAD sources to binary STL with the local OpenSCAD CLI."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATES = [
    Path(r"C:\Program Files\OpenSCAD\openscad.com"),
    Path(r"C:\Program Files\OpenSCAD\openscad.exe"),
    Path("/usr/bin/openscad"),
    Path("/usr/local/bin/openscad"),
]


def find_openscad(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise SystemExit(f"OpenSCAD not found at {path}")
        return path
    if os.environ.get("OPENSCAD"):
        path = Path(os.environ["OPENSCAD"])
        if path.exists():
            return path
    for candidate in DEFAULT_CANDIDATES:
        if candidate.exists():
            return candidate
    found = shutil.which("openscad")
    if found:
        return Path(found)
    raise SystemExit("OpenSCAD CLI not found; set OPENSCAD or pass --openscad")


def render(executable: Path, scad: Path, stl: Path) -> None:
    stl.parent.mkdir(parents=True, exist_ok=True)
    command = [str(executable), "-o", str(stl), "--export-format", "binstl", str(scad)]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise SystemExit(f"OpenSCAD failed for {scad.name}:\n{completed.stderr.strip()}")
    if not stl.exists() or stl.stat().st_size < 84:
        raise SystemExit(f"OpenSCAD produced no usable STL for {scad.name}")
    warnings = [line for line in completed.stderr.splitlines() if "WARNING" in line or "ERROR" in line]
    if warnings:
        raise SystemExit(f"OpenSCAD reported problems for {scad.name}: {warnings[:3]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scad-dir", type=Path, default=ROOT / "cad")
    parser.add_argument("--out", type=Path, default=ROOT / "stl")
    parser.add_argument("--openscad", default=None)
    arguments = parser.parse_args(argv)

    executable = find_openscad(arguments.openscad)
    sources = {
        "base": arguments.scad_dir / "base.scad",
        "lid_bme280": arguments.scad_dir / "lid_bme280.scad",
        "lid_vl53l1x": arguments.scad_dir / "lid_vl53l1x.scad",
        "assembly_bme280": arguments.scad_dir / "assembly_bme280.scad",
    }
    for name, source in sources.items():
        if not source.exists():
            raise SystemExit(f"missing generated source: {source}")
        render(executable, source, arguments.out / f"{name}.stl")

    summary = {
        "openscad": str(executable),
        "parts": {name: (arguments.out / f"{name}.stl").stat().st_size for name in sources},
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
