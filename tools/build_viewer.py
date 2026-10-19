"""Build the standalone enclosure viewer from the generated STL parts."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mesh_checks as mc  # noqa: E402

TEMPLATE = ROOT / "viewer" / "enclosure_viewer.template.html"
THREE = ROOT / "vendor" / "three.min.js"
OUTPUT = ROOT / "enclosure_viewer.html"
PAYLOAD_TOKEN = "__ENCLOSURE_PAYLOAD__"
THREE_TOKEN = "<!-- INLINE_THREE -->"
THREE_VERSION = "0.128.0"
THREE_SHA256 = "9274bbcec8d96168626c732b5d31c775aa8cfb7eaa0599bec0c175908a2c1ce2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def mesh_payload(path: Path) -> dict:
    mesh = mc.read_stl(path)
    # SCAD is Z-up; three.js is Y-up. (x, y, z) -> (x, z, -y) is a rotation.
    points = np.column_stack([mesh.points[:, 0], mesh.points[:, 2], -mesh.points[:, 1]])
    return {
        "positions": [round(float(value), 4) for value in points.reshape(-1)],
        "indices": [int(value) for value in mesh.triangles.reshape(-1)],
        "triangles": int(mesh.triangle_count),
    }


def render() -> tuple[str, dict]:
    template = TEMPLATE.read_text(encoding="utf-8")
    three_source = THREE.read_text(encoding="utf-8")
    if sha256(THREE) != THREE_SHA256:
        raise SystemExit("vendor/three.min.js does not match the pinned SHA-256")
    if "</script" in three_source.lower():
        raise SystemExit("three.js source contains a script terminator")

    spec = json.loads((ROOT / "specs" / "sensor_gateway.json").read_text(encoding="utf-8"))
    checks_doc = json.loads((ROOT / "cad" / "mechanical-checks.json").read_text(encoding="utf-8"))
    mesh_report = json.loads((ROOT / "reports" / "mechanical-report.json").read_text(encoding="utf-8"))
    if checks_doc["failed"]:
        raise SystemExit("spec gates failed; refusing to build the viewer")
    if not mesh_report.get("passed"):
        raise SystemExit("mesh checks failed; refusing to build the viewer")

    parts = {
        "base": mesh_payload(ROOT / "stl" / "base.stl"),
        "lid_bme280": mesh_payload(ROOT / "stl" / "lid_bme280.stl"),
        "lid_vl53l1x": mesh_payload(ROOT / "stl" / "lid_vl53l1x.stl"),
    }
    enclosure = spec["enclosure"]
    payload = {
        "schema": "ENCLOSURE_VIEWER_V1",
        "provenance": spec["provenance"],
        "spec": {
            "name": enclosure["name"],
            "outer_width": enclosure["outer_width"],
            "outer_depth": enclosure["outer_depth"],
            "outer_height": enclosure["outer_height"],
            "wall_thickness": enclosure["wall_thickness"],
            "boss_diameter": spec["fasteners"]["boss_diameter"],
            "hole_diameter": spec["fasteners"]["hole_diameter"],
            "lid_clearance": enclosure["lid_clearance"],
        },
        "checks": checks_doc["checks"],
        "mesh": {
            "passed": True,
            "triangles": sum(part["triangles"] for part in parts.values()),
            "report": {
                kind: {
                    "watertight": part["topology"]["watertight"],
                    "volume_mm3": part["geometry"]["volume_mm3"],
                    "bbox_size_mm": part["geometry"]["bbox_size_mm"],
                }
                for kind, part in mesh_report["parts"].items()
            },
        },
        "parts": parts,
    }
    embedded = json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":")).replace("</", "<\\/")

    html = template.replace(PAYLOAD_TOKEN, embedded, 1)
    html = html.replace(THREE_TOKEN, "<script>\n" + three_source + "\n</script>")
    return html, {
        "parts": len(parts),
        "triangles": payload["mesh"]["triangles"],
        "checks": len(checks_doc["checks"]),
        "spec": enclosure["name"],
    }


def build(check_only: bool = False) -> dict:
    html, info = render()
    encoded = html.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    if check_only:
        if not OUTPUT.exists():
            raise SystemExit("viewer is missing; build it first")
        if OUTPUT.read_bytes() != encoded:
            raise SystemExit("viewer is stale; rebuild it")
    else:
        OUTPUT.write_bytes(encoded)
    return {"output": OUTPUT.name, "bytes": len(encoded), "sha256": digest, "checked": check_only,
            "three_version": THREE_VERSION, "three_sha256": THREE_SHA256, **info}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(build(check_only=arguments.check), indent=2))
