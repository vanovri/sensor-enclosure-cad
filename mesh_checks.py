"""Geometry referee for the generated STL parts.

Checks are deliberately mechanical: manifoldness, orientation, volume, bounding
box, sampled wall thickness, port penetration and boss-hole depth. They do not
prove printability, strength, ingress protection or fit against a real board.
"""
from __future__ import annotations

import json
import math
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent


@dataclass
class Mesh:
    points: np.ndarray
    triangles: np.ndarray

    @property
    def triangle_count(self) -> int:
        return len(self.triangles)

    @property
    def vertex_count(self) -> int:
        return len(self.points)


def read_stl(path: Path) -> Mesh:
    data = path.read_bytes()
    if len(data) < 84:
        raise ValueError(f"{path.name}: too short to be an STL")
    count = struct.unpack("<I", data[80:84])[0]
    if 84 + count * 50 == len(data):
        return _read_binary(data, count, path)
    return _read_ascii(data, path)


def _read_binary(data: bytes, count: int, path: Path) -> Mesh:
    if count == 0:
        raise ValueError(f"{path.name}: empty STL")
    record = np.frombuffer(data[84:], dtype=np.uint8).reshape(count, 50)
    triangles = record[:, 12:48].copy().view("<f4").reshape(count, 3, 3).astype(np.float64)
    points, inverse = np.unique(np.round(triangles.reshape(-1, 3), 4), axis=0, return_inverse=True)
    return Mesh(points=points, triangles=inverse.reshape(count, 3))


def _read_ascii(data: bytes, path: Path) -> Mesh:
    vertices = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("vertex "):
            parts = stripped.split()
            if len(parts) != 4:
                raise ValueError(f"{path.name}: malformed vertex line")
            vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
    if not vertices or len(vertices) % 3:
        raise ValueError(f"{path.name}: ASCII STL needs whole triangles")
    array = np.array(vertices, dtype=np.float64)
    points, inverse = np.unique(np.round(array, 4), axis=0, return_inverse=True)
    return Mesh(points=points, triangles=inverse.reshape(-1, 3))


def topology(mesh: Mesh) -> dict:
    triangles = mesh.triangles
    directed = np.concatenate([
        triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]],
    ])
    undirected = np.sort(directed, axis=1)
    _, counts = np.unique(undirected, axis=0, return_counts=True)
    key_directed = directed[:, 0] * len(mesh.points) + directed[:, 1]
    key_reverse = directed[:, 1] * len(mesh.points) + directed[:, 0]
    directed_unique = len(np.unique(key_directed)) == len(key_directed)
    reversed_present = np.isin(key_reverse, key_directed)
    consistent = bool(directed_unique and reversed_present.all())
    degenerate = int(np.sum((triangles[:, 0] == triangles[:, 1]) |
                            (triangles[:, 1] == triangles[:, 2]) |
                            (triangles[:, 2] == triangles[:, 0])))
    return {
        "edges": int(len(counts)),
        "boundary_edges": int(np.sum(counts != 2)),
        "nonmanifold_edges": int(np.sum(counts > 2)),
        "duplicate_directed_edges": int(len(key_directed) - len(np.unique(key_directed))),
        "orientation_consistent": consistent,
        "degenerate_triangles": degenerate,
        "watertight": bool(np.all(counts == 2) and consistent and degenerate == 0),
    }


def volume_and_bbox(mesh: Mesh) -> dict:
    v0 = mesh.points[mesh.triangles[:, 0]]
    v1 = mesh.points[mesh.triangles[:, 1]]
    v2 = mesh.points[mesh.triangles[:, 2]]
    signed = float(np.sum(np.einsum("ij,ij->i", v0, np.cross(v1, v2))) / 6.0)
    minimum = mesh.points.min(axis=0)
    maximum = mesh.points.max(axis=0)
    return {
        "signed_volume_mm3": round(signed, 3),
        "volume_mm3": round(abs(signed), 3),
        "bbox_min_mm": [round(value, 4) for value in minimum],
        "bbox_max_mm": [round(value, 4) for value in maximum],
        "bbox_size_mm": [round(value, 4) for value in (maximum - minimum)],
    }


def ray_hits(mesh: Mesh, origin, direction, limit: float = 1000.0) -> list[float]:
    """Distances along a ray to triangle intersections (Moller-Trumbore)."""
    origin = np.array(origin, dtype=np.float64)
    direction = np.array(direction, dtype=np.float64)
    direction = direction / np.linalg.norm(direction)
    v0 = mesh.points[mesh.triangles[:, 0]]
    v1 = mesh.points[mesh.triangles[:, 1]]
    v2 = mesh.points[mesh.triangles[:, 2]]
    edge1 = v1 - v0
    edge2 = v2 - v0
    pvec = np.cross(direction, edge2)
    det = np.einsum("ij,ij->i", edge1, pvec)
    valid = np.abs(det) > 1e-12
    inv = np.zeros_like(det)
    inv[valid] = 1.0 / det[valid]
    tvec = origin - v0
    u = np.einsum("ij,ij->i", tvec, pvec) * inv
    qvec = np.cross(tvec, edge1)
    v = np.einsum("j,ij->i", direction, qvec) * inv
    t = np.einsum("ij,ij->i", edge2, qvec) * inv
    mask = valid & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > 1e-7) & (t <= limit)
    hits = sorted(float(value) for value in t[mask])
    unique = []
    for value in hits:
        if not unique or abs(value - unique[-1]) > 1e-6:
            unique.append(value)
    return unique


def check_part(mesh: Mesh, kind: str, spec: dict) -> dict:
    enclosure = spec["enclosure"]
    fasteners = spec["fasteners"]
    w, d, h = enclosure["outer_width"], enclosure["outer_depth"], enclosure["outer_height"]
    wt = enclosure["wall_thickness"]
    plate = enclosure["lid_thickness"]
    lip = enclosure["lid_lip_height"]
    topo = topology(mesh)
    geom = volume_and_bbox(mesh)
    checks = []

    def add(check_id, ok, detail):
        checks.append({"id": check_id, "pass": bool(ok), "detail": detail})

    add("watertight", topo["watertight"],
        f"boundary={topo['boundary_edges']}, nonmanifold={topo['nonmanifold_edges']}, degenerate={topo['degenerate_triangles']}")
    add("positive_volume", geom["signed_volume_mm3"] > 0, f"signed volume {geom['signed_volume_mm3']} mm3")

    expected = {"base": (w, d, h), "lid": (w, d, plate + lip), "assembly": (w, d, h + plate)}[kind]
    size = geom["bbox_size_mm"]
    size_ok = all(abs(size[i] - expected[i]) <= 0.25 for i in range(3))
    add("bounding_box", size_ok, f"{size} vs expected {list(expected)}")

    if kind == "base":
        samples = [
            ("+X wall", (w / 2 + 0.05, 0.0, h / 2), (-1.0, 0.0, 0.0)),
            ("-X wall", (-w / 2 - 0.05, 0.0, h / 2), (1.0, 0.0, 0.0)),
            ("+Y wall", (20.0, d / 2 + 0.05, h / 2), (0.0, -1.0, 0.0)),
            ("-Y wall", (-20.0, -d / 2 - 0.05, h / 2), (0.0, 1.0, 0.0)),
        ]
        for label, origin, direction in samples:
            hits = ray_hits(mesh, origin, direction)
            thickness = hits[1] - hits[0] if len(hits) >= 2 else None
            ok = thickness is not None and abs(thickness - wt) <= 0.15
            add(f"wall_thickness_{label.replace(' ', '_').replace('+', 'p').replace('-', 'm')}",
                ok, f"measured {None if thickness is None else round(thickness, 3)} mm, design {wt} mm")

        port = spec["ports"][0]
        width, height = (port["connector_width"] + 2 * port["clearance"],
                         port["connector_height"] + 2 * port["clearance"])
        origin = (port["center_x"], -d / 2 - 5.0, port["center_z"])
        hits = ray_hits(mesh, origin, (0.0, 1.0, 0.0))
        first = hits[0] if hits else None
        add("port_penetrates_wall", first is not None and first > 2 * wt,
            f"first hit at {None if first is None else round(first, 2)} mm; opening {round(width,2)}x{round(height,2)} mm")

        bx = w / 2 - fasteners["boss_inset"]
        by = d / 2 - fasteners["boss_inset"]
        hole_hits = ray_hits(mesh, (bx, by, h + 1.0), (0.0, 0.0, -1.0))
        ring_hits = ray_hits(mesh, (bx + 2.0, by, h + 1.0), (0.0, 0.0, -1.0))
        hole_depth = hole_hits[0] if hole_hits else None
        add("boss_hole_present", hole_depth is not None and 7.0 <= hole_depth <= 12.0,
            f"first hit {None if hole_depth is None else round(hole_depth, 2)} mm below the rim")
        ring_material = ring_hits[0] if ring_hits else None
        add("boss_ring_material", ring_material is not None and ring_material <= 2.0,
            f"ring hit at {None if ring_material is None else round(ring_material, 2)} mm")

    if kind == "lid":
        bx = w / 2 - fasteners["boss_inset"]
        by = d / 2 - fasteners["boss_inset"]
        through = ray_hits(mesh, (bx, by, plate + 2.0), (0.0, 0.0, -1.0))
        add("screw_hole_open", not through or through[0] > plate + lip + 0.5,
            f"hits through a screw hole: {[round(value, 2) for value in through]}")

    return {
        "kind": kind,
        "triangles": mesh.triangle_count,
        "vertices": mesh.vertex_count,
        "topology": topo,
        "geometry": geom,
        "checks": checks,
        "passed": all(check["pass"] for check in checks),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--stl-dir", type=Path, default=ROOT / "stl")
    parser.add_argument("--out", type=Path, default=ROOT / "reports" / "mechanical-report.json")
    arguments = parser.parse_args(argv)

    spec = json.loads(arguments.spec.read_text(encoding="utf-8"))
    parts = {
        "base": arguments.stl_dir / "base.stl",
        "lid": arguments.stl_dir / "lid_bme280.stl",
        "assembly": arguments.stl_dir / "assembly_bme280.stl",
    }
    report = {"spec": spec["enclosure"]["name"], "provenance": spec["provenance"], "parts": {}, "passed": True}
    for kind, path in parts.items():
        if not path.exists():
            report["parts"][kind] = {"error": f"missing {path.name}"}
            report["passed"] = False
            continue
        result = check_part(read_stl(path), kind, spec)
        result["file"] = path.name
        result["bytes"] = path.stat().st_size
        report["parts"][kind] = result
        report["passed"] = report["passed"] and result["passed"]

    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({kind: {"passed": part.get("passed"), "triangles": part.get("triangles")}
                      for kind, part in report["parts"].items()} | {"all": report["passed"]}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
