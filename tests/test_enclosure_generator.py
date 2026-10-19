"""Tests for the parametric spec, referee gates and OpenSCAD source generation."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import enclosure_generator as gen  # noqa: E402

SPEC_PATH = ROOT / "specs" / "sensor_gateway.json"
SCRIPT = ROOT / "enclosure_generator.py"


@pytest.fixture()
def spec() -> dict:
    return gen.load_spec(SPEC_PATH)


def test_valid_spec_loads(spec):
    assert spec["schema"] == "ENCLOSURE_SPEC_V1"
    assert spec["enclosure"]["wall_thickness"] == 2.4
    assert len(spec["sensor_mounts"]) == 2


@pytest.mark.parametrize("schema", ["ENCLOSURE_SPEC_V2", None, 1])
def test_unsupported_schema_is_rejected(spec, tmp_path, schema):
    mutated = copy.deepcopy(spec)
    mutated["schema"] = schema
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported spec schema"):
        gen.load_spec(path)


def test_non_millimetre_units_are_rejected(spec, tmp_path):
    mutated = copy.deepcopy(spec)
    mutated["units"] = "inch"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(ValueError, match="millimetres"):
        gen.load_spec(path)


def test_missing_provenance_is_rejected(spec, tmp_path):
    mutated = copy.deepcopy(spec)
    mutated["provenance"] = {"kind": "guessed"}
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(ValueError, match="provenance"):
        gen.load_spec(path)


def test_missing_enclosure_field_is_rejected(spec, tmp_path):
    mutated = copy.deepcopy(spec)
    del mutated["enclosure"]["wall_thickness"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(ValueError, match="missing enclosure field"):
        gen.load_spec(path)


def test_missing_fastener_field_is_rejected(spec, tmp_path):
    mutated = copy.deepcopy(spec)
    del mutated["fasteners"]["hole_diameter"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(ValueError, match="missing fastener field"):
        gen.load_spec(path)


def test_empty_ports_and_duplicate_presets_are_rejected(spec, tmp_path):
    mutated = copy.deepcopy(spec)
    mutated["ports"] = []
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(ValueError, match="at least one port"):
        gen.load_spec(path)

    mutated = copy.deepcopy(spec)
    mutated["sensor_mounts"].append(copy.deepcopy(mutated["sensor_mounts"][0]))
    path.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(ValueError, match="presets must be unique"):
        gen.load_spec(path)


def test_boss_positions_are_symmetric(spec):
    positions = gen.boss_positions(spec)
    assert positions == [(-39.0, -24.0), (39.0, -24.0), (-39.0, 24.0), (39.0, 24.0)]


def test_port_opening_adds_clearance_each_side(spec):
    width, height = gen.port_opening(spec["ports"][0])
    assert width == pytest.approx(8.8 + 1.2)
    assert height == pytest.approx(3.2 + 1.2)


def test_all_design_checks_pass(spec):
    checks = gen.mechanical_checks(spec)
    assert len(checks) >= 15
    assert all(check["pass"] for check in checks)
    assert gen.failed_checks(spec) == []


@pytest.mark.parametrize(
    "path,value,expected",
    [
        (("enclosure", "wall_thickness"), 1.8, "wall_thickness"),
        (("enclosure", "floor_thickness"), 1.5, "floor_thickness"),
        (("enclosure", "lid_thickness"), 1.6, "lid_thickness"),
        (("enclosure", "lid_clearance"), 0.9, "lid_radial_clearance"),
        (("fasteners", "hole_diameter"), 3.05, "screw_clearance"),
        (("fasteners", "boss_inset"), 5.0, "boss_edge_to_wall"),
    ],
)
def test_gate_rejects_out_of_spec_parameters(spec, path, value, expected):
    mutated = copy.deepcopy(spec)
    mutated[path[0]][path[1]] = value
    failed = {check["id"] for check in gen.failed_checks(mutated)}
    assert expected in failed


def test_require_pass_raises_with_detail(spec):
    mutated = copy.deepcopy(spec)
    mutated["enclosure"]["wall_thickness"] = 1.0
    with pytest.raises(ValueError, match="REFEREE GATE FAILED"):
        gen.require_pass(mutated)


def test_base_source_is_deterministic_and_ordered(spec):
    first = gen.base_scad(spec)
    assert first == gen.base_scad(spec)
    assert "$fn = 64;" in first
    assert "module rounded_rect" in first
    assert "Bosses are unioned after the cavity" in first
    assert "10, 4.4, 4.4" in first  # USB-C opening width x depth x height
    assert "HOLE_D" in first


def test_lid_sources_differ_by_preset(spec):
    bme = gen.lid_scad(spec, spec["sensor_mounts"][0])
    tof = gen.lid_scad(spec, spec["sensor_mounts"][1])
    assert bme != tof
    assert "OPEN_W = 12" in bme
    assert "OPEN_W = 8" in tof
    assert "HOLE_SPACING = 14" in bme
    assert "HOLE_SPACING = 9" in tof
    assert "module lid()" in bme


def test_assembly_contains_both_modules(spec):
    assembly = gen.assembly_scad(spec, spec["sensor_mounts"][0])
    assert assembly.count("module base()") == 1
    assert assembly.count("module lid()") == 1
    assert "translate([0, 0, 34]) lid();" in assembly


def test_write_sources_creates_all_artifacts(spec, tmp_path):
    written = gen.write_sources(spec, tmp_path)
    names = {path.name for path in written}
    assert names == {"base.scad", "lid_bme280.scad", "lid_vl53l1x.scad", "assembly_bme280.scad", "mechanical-checks.json"}
    checks = json.loads((tmp_path / "mechanical-checks.json").read_text(encoding="utf-8"))
    assert checks["failed"] == []
    assert all(check["pass"] for check in checks["checks"])


def test_write_sources_refuses_failed_gate(spec, tmp_path):
    mutated = copy.deepcopy(spec)
    mutated["enclosure"]["wall_thickness"] = 1.2
    with pytest.raises(ValueError, match="REFEREE GATE FAILED"):
        gen.write_sources(mutated, tmp_path)


def test_cli_writes_sources_and_reports(spec, tmp_path):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--spec", str(SPEC_PATH), "--out", str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "base.scad").exists()
    assert "checks" in proc.stdout


def test_cli_rejects_bad_gate_cleanly(spec, tmp_path):
    mutated = copy.deepcopy(spec)
    mutated["enclosure"]["wall_thickness"] = 1.0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(mutated), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--spec", str(bad), "--out", str(tmp_path / "out")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr
    assert "error:" in proc.stderr.lower()
