"""Parametric enclosure generator for a documented hand-transcribed sketch.

The generator validates mechanical parameters, writes deterministic OpenSCAD
sources, and exposes the check table used by the referee report. It does not
claim printability, drop resistance, IP rating or a physical prototype.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMA = "ENCLOSURE_SPEC_V1"
REQUIRED_ENCLOSURE = (
    "name", "outer_width", "outer_depth", "outer_height", "wall_thickness",
    "floor_thickness", "corner_radius", "lid_thickness", "lid_lip_height",
    "lid_lip_thickness", "lid_clearance",
)
REQUIRED_FASTENERS = (
    "thread", "screw_diameter", "boss_diameter", "hole_diameter", "boss_inset",
    "boss_height", "hole_depth", "counterbore_diameter", "counterbore_depth",
)


def load_spec(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError(f"unsupported spec schema: {data.get('schema')!r}")
    if data.get("units") != "mm":
        raise ValueError("only millimetres are supported")
    provenance = data.get("provenance") or {}
    if provenance.get("kind") not in ("manual_sketch_transcription", "measured_part"):
        raise ValueError("explicit provenance (manual_sketch_transcription or measured_part) is required")
    enclosure = data.get("enclosure") or {}
    for key in REQUIRED_ENCLOSURE:
        if key not in enclosure:
            raise ValueError(f"missing enclosure field: {key}")
        if key != "name" and (not isinstance(enclosure[key], (int, float)) or enclosure[key] <= 0):
            raise ValueError(f"enclosure field {key} must be a positive number")
    fasteners = data.get("fasteners") or {}
    for key in REQUIRED_FASTENERS:
        if key not in fasteners:
            raise ValueError(f"missing fastener field: {key}")
    if not data.get("ports"):
        raise ValueError("at least one port is required")
    if not data.get("sensor_mounts"):
        raise ValueError("at least one sensor-mount preset is required")
    presets = {mount["preset"] for mount in data["sensor_mounts"]}
    if len(presets) != len(data["sensor_mounts"]):
        raise ValueError("sensor-mount presets must be unique")
    return data


def _enclosure(spec: dict) -> dict:
    return spec["enclosure"]


def _fasteners(spec: dict) -> dict:
    return spec["fasteners"]


def boss_positions(spec: dict) -> list[tuple[float, float]]:
    enclosure, fasteners = _enclosure(spec), _fasteners(spec)
    inset = fasteners["boss_inset"]
    x = enclosure["outer_width"] / 2 - inset
    y = enclosure["outer_depth"] / 2 - inset
    return [(-x, -y), (x, -y), (-x, y), (x, y)]


def port_opening(port: dict) -> tuple[float, float]:
    return (port["connector_width"] + 2 * port["clearance"],
            port["connector_height"] + 2 * port["clearance"])


def mechanical_checks(spec: dict) -> list[dict]:
    enclosure, fasteners = _enclosure(spec), _fasteners(spec)
    minimums = spec.get("minimums", {})
    checks: list[dict] = []

    def add(check_id: str, value: float, limit: float, rule: str, note: str) -> None:
        if rule == "min":
            ok = value >= limit - 1e-9
        elif rule == "max":
            ok = value <= limit + 1e-9
        elif rule == "range":
            ok = limit[0] <= value <= limit[1]
        else:
            raise ValueError(rule)
        checks.append({"id": check_id, "value": round(value, 3), "limit": limit, "rule": rule, "pass": ok, "note": note})

    add("wall_thickness", enclosure["wall_thickness"], minimums.get("wall_thickness", 2.0), "min",
        "FDM perimeter wall thickness")
    add("floor_thickness", enclosure["floor_thickness"], minimums.get("floor_thickness", 2.0), "min",
        "Load-bearing floor thickness")
    add("lid_thickness", enclosure["lid_thickness"], minimums.get("lid_thickness", 2.0), "min",
        "Lid plate thickness")
    add("boss_ring_width", (fasteners["boss_diameter"] - fasteners["hole_diameter"]) / 2,
        minimums.get("boss_ring_width", 1.5), "min", "Material around the heat-set insert")
    add("screw_clearance", fasteners["hole_diameter"] - fasteners["screw_diameter"],
        minimums.get("screw_clearance", 0.2), "min", "Lid through-hole minus screw shank")
    add("lid_radial_clearance", enclosure["lid_clearance"],
        (minimums.get("lid_clearance_min", 0.2), minimums.get("lid_clearance_max", 0.6)), "range",
        "Radial lip clearance into the cavity")

    boss_edge = fasteners["boss_inset"] - fasteners["boss_diameter"] / 2
    add("boss_edge_to_wall", boss_edge - enclosure["wall_thickness"],
        minimums.get("boss_wall_margin", 1.0), "min", "Boss edge to inner wall")
    add("boss_to_wall_center", boss_edge, enclosure["wall_thickness"], "min", "Boss edge outside the cavity wall")

    for port in spec["ports"]:
        width, height = port_opening(port)
        add(f"port_{port['id']}_margin", port["clearance"], 0.3, "min", "Per-side connector clearance")
        center_x, center_z = port["center_x"], port["center_z"]
        edge = min(enclosure["outer_width"] / 2 - (center_x + width / 2),
                   enclosure["outer_width"] / 2 + (center_x - width / 2))
        add(f"port_{port['id']}_edge_margin", edge, minimums.get("port_edge_margin", 3.0), "min",
            "Port opening to enclosure corner")
        vertical = min(enclosure["outer_height"] - (center_z + height / 2), center_z - height / 2)
        add(f"port_{port['id']}_vertical_margin", vertical, minimums.get("port_edge_margin", 3.0), "min",
            "Port opening to floor/rim")

    for mount in spec["sensor_mounts"]:
        add(f"mount_{mount['preset']}_pocket_fit",
            mount["opening_width"] / 2, 1.0, "min",
            "Half-opening for the sensor aperture")
        add(f"mount_{mount['preset']}_hole_diameter", mount["hole_diameter"], 2.0, "min",
            "Self-tapping M2 pilot")
        add(f"mount_{mount['preset']}_hole_fit",
            (mount["module_width"] - mount["hole_spacing"]) / 2, 1.0, "min",
            "Edge distance from module edge to mounting hole")

    add("lid_lip_thickness", enclosure["lid_lip_thickness"], minimums.get("feature_size", 0.8), "min",
        "Printable minimum lip feature")
    add("minimum_feature", min(enclosure["wall_thickness"], enclosure["lid_lip_thickness"]),
        minimums.get("feature_size", 0.8), "min", "Smallest designed feature")
    add("corner_radius", enclosure["corner_radius"], enclosure["wall_thickness"], "min",
        "Outer radius at least one wall thick")
    return checks


def failed_checks(spec: dict) -> list[dict]:
    return [check for check in mechanical_checks(spec) if not check["pass"]]


def require_pass(spec: dict) -> None:
    failed = failed_checks(spec)
    if failed:
        detail = "; ".join(f"{item['id']}={item['value']}" for item in failed)
        raise ValueError(f"REFEREE GATE FAILED: {detail}")


def _fmt(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _header(spec: dict, part: str) -> str:
    provenance = spec["provenance"]["kind"]
    return (
        f"// {part} — generated from {spec['enclosure']['name']}\n"
        f"// Source: {provenance}; units mm; this is a design artifact, not a print guarantee.\n"
        f"// Generator: enclosure_generator.py (deterministic output)\n"
        "$fn = 64;\n\n"
    )


def _base_params(spec: dict) -> str:
    enclosure, fasteners = _enclosure(spec), _fasteners(spec)
    return (
        f"W = {_fmt(enclosure['outer_width'])}; D = {_fmt(enclosure['outer_depth'])}; H = {_fmt(enclosure['outer_height'])};\n"
        f"WT = {_fmt(enclosure['wall_thickness'])}; FLOOR = {_fmt(enclosure['floor_thickness'])}; R = {_fmt(enclosure['corner_radius'])};\n"
        f"BOSS_D = {_fmt(fasteners['boss_diameter'])}; HOLE_D = {_fmt(fasteners['hole_diameter'])};\n"
        f"BOSS_INSET = {_fmt(fasteners['boss_inset'])}; BOSS_H = {_fmt(enclosure['outer_height'] - enclosure['floor_thickness'] - 1.0)};\n"
        f"HOLE_DEPTH = {_fmt(fasteners['hole_depth'])};\n"
    )


def _rounded_rect_module() -> str:
    return (
        "module rounded_rect(w, d, r) {\n"
        "    offset(r = r) square([w - 2*r, d - 2*r], center = true);\n"
        "}\n\n"
    )


def base_scad(spec: dict) -> str:
    enclosure = _enclosure(spec)
    ports = spec["ports"]
    w, d, h = enclosure["outer_width"], enclosure["outer_depth"], enclosure["outer_height"]
    wt = enclosure["wall_thickness"]
    r = enclosure["corner_radius"]
    lines = [_header(spec, "base"), _base_params(spec), _rounded_rect_module()]
    lines.append("module base() {\n    difference() {\n        union() {\n")
    lines.append("            // Shell with an open cavity\n")
    lines.append("            difference() {\n")
    lines.append("                linear_extrude(height = H) rounded_rect(W, D, R);\n")
    lines.append("                translate([0, 0, FLOOR]) linear_extrude(height = H - FLOOR + 1)\n")
    lines.append("                    rounded_rect(W - 2*WT, D - 2*WT, max(0, R - WT));\n")
    for port in ports:
        width, height = port_opening(port)
        if port["wall"] == "front":
            lines.append(
                f"                // {port['id']} opening (front wall)\n"
                f"                translate([{_fmt(port['center_x'])}, {_fmt(-d/2 + wt/2)}, {_fmt(port['center_z'])}])\n"
                f"                    cube([{_fmt(width)}, {_fmt(wt + 2)}, {_fmt(height)}], center = true);\n"
            )
        elif port["wall"] == "back":
            lines.append(
                f"                // {port['id']} opening (back wall)\n"
                f"                translate([{_fmt(port['center_x'])}, {_fmt(d/2 - wt/2)}, {_fmt(port['center_z'])}])\n"
                f"                    cube([{_fmt(width)}, {_fmt(wt + 2)}, {_fmt(height)}], center = true);\n"
            )
        else:
            raise ValueError(f"unsupported port wall: {port['wall']}")
    lines.append("            }\n")
    lines.append("            // Bosses are unioned after the cavity so they stand on the floor\n")
    lines.append("            for (mx = [-1, 1], my = [-1, 1]) {\n")
    lines.append("                translate([mx * (W/2 - BOSS_INSET), my * (D/2 - BOSS_INSET), FLOOR - 0.1])\n")
    lines.append("                    cylinder(h = BOSS_H + 0.1, d = BOSS_D);\n")
    lines.append("            }\n")
    lines.append("        }\n")
    for mx in (-1, 1):
        for my in (-1, 1):
            lines.append(
                f"        // Insert hole at ({mx:+d}, {my:+d})\n"
                f"        translate([{mx} * (W/2 - BOSS_INSET), {my} * (D/2 - BOSS_INSET), H - 1 - HOLE_DEPTH])\n"
                f"            cylinder(h = HOLE_DEPTH + 1.5, d = HOLE_D);\n"
            )
    lines.append("    }\n}\n\nbase();\n")
    return "".join(lines)


def lid_scad(spec: dict, mount: dict) -> str:
    enclosure, fasteners = _enclosure(spec), _fasteners(spec)
    w, d, h = enclosure["outer_width"], enclosure["outer_depth"], enclosure["outer_height"]
    wt, r = enclosure["wall_thickness"], enclosure["corner_radius"]
    plate, lip_h, lip_t = enclosure["lid_thickness"], enclosure["lid_lip_height"], enclosure["lid_lip_thickness"]
    clr = enclosure["lid_clearance"]
    hole = fasteners["hole_diameter"]
    cb_d, cb_depth = fasteners["counterbore_diameter"], fasteners["counterbore_depth"]
    lines = [_header(spec, f"lid ({mount['preset']})")]
    lines.append(
        f"W = {_fmt(w)}; D = {_fmt(d)}; WT = {_fmt(wt)}; R = {_fmt(r)};\n"
        f"PLATE = {_fmt(plate)}; LIP_H = {_fmt(lip_h)}; LIP_T = {_fmt(lip_t)}; CLR = {_fmt(clr)};\n"
        f"HOLE_D = {_fmt(hole)}; CB_D = {_fmt(cb_d)}; CB_DEPTH = {_fmt(cb_depth)};\n"
        f"BOSS_INSET = {_fmt(fasteners['boss_inset'])};\n"
        f"OPEN_W = {_fmt(mount['opening_width'])}; OPEN_H = {_fmt(mount['opening_height'])};\n"
        f"MOD_W = {_fmt(mount['module_width'])}; MOD_H = {_fmt(mount['module_height'])};\n"
        f"HOLE_SPACING = {_fmt(mount['hole_spacing'])}; MOUNT_HOLE_D = {_fmt(mount['hole_diameter'])};\n"
        f"POCKET = {_fmt(mount['pocket_depth'])};\n"
    )
    lines.append(_rounded_rect_module())
    lines.append("module lid() {\n    difference() {\n        union() {\n")
    lines.append("            linear_extrude(height = PLATE) rounded_rect(W, D, R);\n")
    lines.append("            // Inner lip that registers into the cavity\n")
    lines.append("            translate([0, 0, -LIP_H]) linear_extrude(height = LIP_H)\n")
    lines.append("                difference() {\n")
    lines.append("                    rounded_rect(W - 2*WT - 2*CLR, D - 2*WT - 2*CLR, max(0, R - WT - CLR));\n")
    lines.append("                    rounded_rect(W - 2*WT - 2*CLR - 2*LIP_T, D - 2*WT - 2*CLR - 2*LIP_T, max(0, R - WT - CLR - LIP_T));\n")
    lines.append("                }\n")
    lines.append("        }\n")
    for window in spec["windows"]:
        if window["wall"] != "lid":
            continue
        lines.append(
            f"        // {window['id']} window\n"
            f"        translate([{_fmt(window['center_x'])}, {_fmt(window['center_y'])}, -1])\n"
            f"            linear_extrude(height = PLATE + 2)\n"
            f"                rounded_rect({_fmt(window['width'])}, {_fmt(window['height'])}, {_fmt(window['corner_radius'])});\n"
        )
    lines.append("        // Sensor aperture through the lid\n")
    lines.append("        translate([0, 0, -LIP_H - 1]) linear_extrude(height = LIP_H + PLATE + 2)\n")
    lines.append("            rounded_rect(OPEN_W, OPEN_H, min(1, OPEN_W/2, OPEN_H/2));\n")
    lines.append("        // Module pocket on the underside\n")
    lines.append("        translate([0, 0, -LIP_H - 1]) linear_extrude(height = LIP_H + POCKET + 1)\n")
    lines.append("            rounded_rect(MOD_W, MOD_H, 1);\n")
    lines.append("        // Module mounting holes (through the pocket floor)\n")
    lines.append("        for (sx = [-1, 1]) {\n")
    lines.append("            translate([sx * HOLE_SPACING/2, 0, -LIP_H - 1])\n")
    lines.append("                cylinder(h = LIP_H + PLATE + 2, d = MOUNT_HOLE_D);\n")
    lines.append("        }\n")
    lines.append("        // Lid screw holes and counterbores\n")
    lines.append("        for (mx = [-1, 1], my = [-1, 1]) {\n")
    lines.append("            translate([mx * (W/2 - BOSS_INSET), my * (D/2 - BOSS_INSET), -LIP_H - 1])\n")
    lines.append("                cylinder(h = LIP_H + PLATE + 2, d = HOLE_D);\n")
    lines.append("            translate([mx * (W/2 - BOSS_INSET), my * (D/2 - BOSS_INSET), PLATE - CB_DEPTH])\n")
    lines.append("                cylinder(h = CB_DEPTH + 1, d = CB_D);\n")
    lines.append("        }\n")
    lines.append("    }\n}\n\nlid();\n")
    return "".join(lines)


def assembly_scad(spec: dict, mount: dict) -> str:
    base_text = base_scad(spec)
    lid_text = lid_scad(spec, mount)
    base_module = base_text[base_text.index("module base()"):base_text.index("\nbase();")]
    lid_module = lid_text[lid_text.index("module lid()"):lid_text.index("\nlid();")]
    base_params = base_text[base_text.index("W = "):base_text.index("module rounded_rect")]
    lid_params = lid_text[lid_text.index("W = "):lid_text.index("module rounded_rect")]
    h = spec["enclosure"]["outer_height"]
    return (
        _header(spec, f"assembly ({mount['preset']})")
        + base_params
        + lid_params
        + _rounded_rect_module()
        + base_module + "\n\n"
        + lid_module + "\n\n"
        + f"translate([0, 0, {_fmt(h)}]) lid();\nbase();\n"
    )


def write_sources(spec: dict, out_dir: Path) -> list[Path]:
    require_pass(spec)
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    base_path = out_dir / "base.scad"
    base_path.write_text(base_scad(spec), encoding="utf-8", newline="\n")
    written.append(base_path)
    for mount in spec["sensor_mounts"]:
        path = out_dir / f"lid_{mount['preset']}.scad"
        path.write_text(lid_scad(spec, mount), encoding="utf-8", newline="\n")
        written.append(path)
    first = spec["sensor_mounts"][0]
    assembly_path = out_dir / f"assembly_{first['preset']}.scad"
    assembly_path.write_text(assembly_scad(spec, first), encoding="utf-8", newline="\n")
    written.append(assembly_path)
    checks_path = out_dir / "mechanical-checks.json"
    checks_path.write_text(json.dumps({
        "spec": spec["enclosure"]["name"],
        "provenance": spec["provenance"],
        "checks": mechanical_checks(spec),
        "failed": failed_checks(spec),
    }, indent=2) + "\n", encoding="utf-8", newline="\n")
    written.append(checks_path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "cad")
    arguments = parser.parse_args(argv)
    try:
        spec = load_spec(arguments.spec)
        written = write_sources(spec, arguments.out)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    def display(path: Path) -> str:
        try:
            return str(path.relative_to(ROOT))
        except ValueError:
            return str(path)
    print(json.dumps({"written": [display(path) for path in written],
                      "checks": len(mechanical_checks(spec))}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
