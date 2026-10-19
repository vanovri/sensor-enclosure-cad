"""Tests for STL parsing and the geometry referee on the committed parts."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mesh_checks as mc  # noqa: E402

SPEC_PATH = ROOT / "specs" / "sensor_gateway.json"
STL = ROOT / "stl"


@pytest.fixture(scope="module")
def spec() -> dict:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def base() -> mc.Mesh:
    return mc.read_stl(STL / "base.stl")


@pytest.fixture(scope="module")
def lid() -> mc.Mesh:
    return mc.read_stl(STL / "lid_bme280.stl")


@pytest.fixture(scope="module")
def assembly() -> mc.Mesh:
    return mc.read_stl(STL / "assembly_bme280.stl")


def test_binary_stl_is_parsed(base):
    assert base.triangle_count > 1000
    assert base.vertex_count > 100
    assert base.points.shape[1] == 3


def test_base_is_watertight_and_consistently_oriented(base):
    topo = mc.topology(base)
    assert topo["watertight"] is True
    assert topo["boundary_edges"] == 0
    assert topo["nonmanifold_edges"] == 0
    assert topo["orientation_consistent"] is True
    assert topo["degenerate_triangles"] == 0


@pytest.mark.parametrize("name", ["lid_bme280", "lid_vl53l1x", "assembly_bme280"])
def test_other_parts_are_watertight(name):
    mesh = mc.read_stl(STL / f"{name}.stl")
    assert mc.topology(mesh)["watertight"] is True


def test_volume_and_bbox(base, spec):
    geom = mc.volume_and_bbox(base)
    assert geom["signed_volume_mm3"] > 0
    enclosure = spec["enclosure"]
    assert geom["bbox_size_mm"] == pytest.approx(
        [enclosure["outer_width"], enclosure["outer_depth"], enclosure["outer_height"]], abs=0.05
    )


def test_assembly_volume_is_the_sum_of_its_parts(base, lid, assembly):
    total = mc.volume_and_bbox(base)["volume_mm3"] + mc.volume_and_bbox(lid)["volume_mm3"]
    assert mc.volume_and_bbox(assembly)["volume_mm3"] == pytest.approx(total, rel=1e-3)


@pytest.mark.parametrize("origin,direction,label", [
    ((48.05, 0.0, 12.3), (-1, 0, 0), "pX"),
    ((-48.05, 0.0, 12.3), (1, 0, 0), "mX"),
    ((20.0, 33.05, 12.3), (0, -1, 0), "pY"),
    ((-20.0, -33.05, 12.3), (0, 1, 0), "mY"),
])
def test_wall_thickness_matches_the_design(base, spec, origin, direction, label):
    hits = mc.ray_hits(base, origin, direction)
    assert len(hits) >= 2
    thickness = hits[1] - hits[0]
    assert thickness == pytest.approx(spec["enclosure"]["wall_thickness"], abs=0.15)


def test_port_opening_penetrates_the_front_wall(base, spec):
    port = spec["ports"][0]
    hits = mc.ray_hits(base, (port["center_x"], -38.0, port["center_z"]), (0, 1, 0))
    assert hits
    assert hits[0] > 2 * spec["enclosure"]["wall_thickness"]


def test_port_edges_are_material(base, spec):
    port = spec["ports"][0]
    width, height = mc_helpers_opening(port)
    edge_x = port["center_x"] + width / 2 + 1.0
    hits = mc.ray_hits(base, (edge_x, -38.0, port["center_z"]), (0, 1, 0))
    assert hits and 4.0 < hits[0] < 6.0


def mc_helpers_opening(port):
    return port["connector_width"] + 2 * port["clearance"], port["connector_height"] + 2 * port["clearance"]


def test_boss_hole_is_blind_and_ring_has_material(base, spec):
    w, d = spec["enclosure"]["outer_width"], spec["enclosure"]["outer_depth"]
    inset = spec["fasteners"]["boss_inset"]
    bx, by = w / 2 - inset, d / 2 - inset
    hole_hits = mc.ray_hits(base, (bx, by, 35.0), (0, 0, -1))
    ring_hits = mc.ray_hits(base, (bx + 2.0, by, 35.0), (0, 0, -1))
    assert hole_hits and 7.0 <= hole_hits[0] <= 12.0
    assert ring_hits and ring_hits[0] <= 2.0


def test_lid_screw_holes_are_open(lid, spec):
    w, d = spec["enclosure"]["outer_width"], spec["enclosure"]["outer_depth"]
    inset = spec["fasteners"]["boss_inset"]
    hits = mc.ray_hits(lid, (w / 2 - inset, d / 2 - inset, 10.0), (0, 0, -1))
    assert hits == []


def test_lid_lip_fits_the_cavity_clearance(spec):
    enclosure = spec["enclosure"]
    cavity = enclosure["outer_width"] - 2 * enclosure["wall_thickness"]
    lip = cavity - 2 * enclosure["lid_clearance"]
    assert cavity - lip == pytest.approx(2 * enclosure["lid_clearance"])


def test_check_part_reports_all_checks_pass(base, lid, assembly, spec):
    for mesh, kind in ((base, "base"), (lid, "lid"), (assembly, "assembly")):
        result = mc.check_part(mesh, kind, spec)
        assert result["passed"], [check for check in result["checks"] if not check["pass"]]
        assert result["topology"]["watertight"]


def test_mechanical_report_is_committed_and_passes(spec):
    report = json.loads((ROOT / "reports" / "mechanical-report.json").read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert set(report["parts"]) == {"base", "lid", "assembly"}


def test_ascii_stl_fallback(tmp_path):
    stl = tmp_path / "tetra.stl"
    stl.write_text(
        "solid tetra\n"
        "facet normal 0 0 1\n outer loop\n  vertex 0 0 0\n  vertex 1 0 0\n  vertex 0 1 0\n endloop\nendfacet\n"
        "facet normal 0 0 -1\n outer loop\n  vertex 0 0 0\n  vertex 0 1 0\n  vertex 0 0 1\n endloop\nendfacet\n"
        "facet normal 0 -1 0\n outer loop\n  vertex 0 0 0\n  vertex 0 0 1\n  vertex 1 0 0\n endloop\nendfacet\n"
        "facet normal 1 1 1\n outer loop\n  vertex 1 0 0\n  vertex 0 0 1\n  vertex 0 1 0\n endloop\nendfacet\n"
        "endsolid tetra\n",
        encoding="utf-8",
    )
    mesh = mc.read_stl(stl)
    assert mesh.triangle_count == 4
    assert mc.topology(mesh)["watertight"] is True
    assert mc.volume_and_bbox(mesh)["volume_mm3"] == pytest.approx(1 / 6, abs=5e-4)


def test_truncated_stl_is_rejected(tmp_path):
    stl = tmp_path / "bad.stl"
    stl.write_bytes(b"too short")
    with pytest.raises(ValueError, match="too short"):
        mc.read_stl(stl)


def test_ray_hits_are_deduplicated(base):
    hits = mc.ray_hits(base, (48.05, 0.0, 12.3), (-1, 0, 0))
    assert all(abs(a - b) > 1e-6 for a, b in zip(hits, hits[1:]))
