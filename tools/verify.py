"""Verification report for the spec → OpenSCAD → STL → viewer chain."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import enclosure_generator as gen  # noqa: E402
import mesh_checks as mc  # noqa: E402
from tools import build_viewer  # noqa: E402

HTML = ROOT / "enclosure_viewer.html"
REPORT = ROOT / "reports" / "verification.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    failures: list[str] = []
    spec = gen.load_spec(ROOT / "specs" / "sensor_gateway.json")
    if gen.failed_checks(spec):
        failures.append("spec gates failed")

    with tempfile.TemporaryDirectory() as temp_dir:
        written = gen.write_sources(spec, Path(temp_dir))
        for source in written:
            if source.suffix != ".scad":
                continue
            committed = ROOT / "cad" / source.name
            if not committed.exists() or committed.read_bytes() != source.read_bytes():
                failures.append(f"committed SCAD is stale: {source.name}")

    report_doc = json.loads((ROOT / "reports" / "mechanical-report.json").read_text(encoding="utf-8"))
    if not report_doc.get("passed"):
        failures.append("mesh report did not pass")
    for kind, part in report_doc["parts"].items():
        if not part["topology"]["watertight"]:
            failures.append(f"{kind} is not watertight")
        if part["geometry"]["signed_volume_mm3"] <= 0:
            failures.append(f"{kind} has non-positive volume")

    html = HTML.read_text(encoding="utf-8")
    template = (ROOT / "viewer" / "enclosure_viewer.template.html").read_text(encoding="utf-8")
    match = re.search(r'<script id="enclosure-data" type="application/json">(.*?)</script>', html, re.S)
    if not match:
        failures.append("embedded payload block missing")
        payload = {}
    else:
        payload = json.loads(match.group(1))
    if len(payload.get("parts", {})) != 3:
        failures.append("viewer payload does not contain three parts")
    viewer_parts = ("base", "lid_bme280", "lid_vl53l1x")
    expected_triangles = sum(
        mc.read_stl(ROOT / "stl" / f"{name}.stl").triangle_count for name in viewer_parts
    )
    if payload.get("mesh", {}).get("triangles") != expected_triangles:
        failures.append("viewer triangle total differs from the STL files")
    if re.search(r'(src|href)\s*=\s*["\']https?:', html, re.I):
        failures.append("viewer references an external asset")
    if re.search(r"\bfetch\s*\(", template):
        failures.append("viewer application performs a network fetch")

    build_info = build_viewer.build(check_only=True)
    if build_info["sha256"] != sha256(HTML):
        failures.append("committed viewer is not reproducible")

    verification = {
        "ok": not failures,
        "failures": failures,
        "spec": {
            "name": spec["enclosure"]["name"],
            "provenance": spec["provenance"],
            "gates": len(gen.mechanical_checks(spec)),
            "failed": gen.failed_checks(spec),
        },
        "parts": {
            kind: {
                "triangles": part["triangles"],
                "volume_mm3": part["geometry"]["volume_mm3"],
                "bbox_size_mm": part["geometry"]["bbox_size_mm"],
                "watertight": part["topology"]["watertight"],
                "checks": len(part["checks"]),
                "passed": part["passed"],
            }
            for kind, part in report_doc["parts"].items()
        },
        "viewer": {
            "file": HTML.name,
            "bytes": HTML.stat().st_size,
            "sha256": build_info["sha256"],
            "three_version": build_info["three_version"],
            "three_sha256": build_info["three_sha256"],
            "embedded_parts": len(payload.get("parts", {})),
            "external_assets": False,
            "network_fetch": False,
        },
        "claims": {
            "physical_print": False,
            "strength_or_drop_test": False,
            "ingress_protection": False,
            "snap_fit": False,
            "note": "Spec and mesh checks only. No printed prototype, fit test against a real board or manufacturing review exists.",
        },
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"ok": verification["ok"], "failures": failures}, indent=2))
    return 0 if verification["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
