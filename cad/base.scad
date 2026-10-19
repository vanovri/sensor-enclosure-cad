// base — generated from Sensor_Gateway_Enclosure
// Source: manual_sketch_transcription; units mm; this is a design artifact, not a print guarantee.
// Generator: enclosure_generator.py (deterministic output)
$fn = 64;

W = 96; D = 66; H = 34;
WT = 2.4; FLOOR = 2.4; R = 6;
BOSS_D = 6.5; HOLE_D = 3.2;
BOSS_INSET = 9; BOSS_H = 30.6;
HOLE_DEPTH = 8;
module rounded_rect(w, d, r) {
    offset(r = r) square([w - 2*r, d - 2*r], center = true);
}

module base() {
    difference() {
        union() {
            // Shell with an open cavity
            difference() {
                linear_extrude(height = H) rounded_rect(W, D, R);
                translate([0, 0, FLOOR]) linear_extrude(height = H - FLOOR + 1)
                    rounded_rect(W - 2*WT, D - 2*WT, max(0, R - WT));
                // usb_c opening (front wall)
                translate([0, -31.8, 10])
                    cube([10, 4.4, 4.4], center = true);
            }
            // Bosses are unioned after the cavity so they stand on the floor
            for (mx = [-1, 1], my = [-1, 1]) {
                translate([mx * (W/2 - BOSS_INSET), my * (D/2 - BOSS_INSET), FLOOR - 0.1])
                    cylinder(h = BOSS_H + 0.1, d = BOSS_D);
            }
        }
        // Insert hole at (-1, -1)
        translate([-1 * (W/2 - BOSS_INSET), -1 * (D/2 - BOSS_INSET), H - 1 - HOLE_DEPTH])
            cylinder(h = HOLE_DEPTH + 1.5, d = HOLE_D);
        // Insert hole at (-1, +1)
        translate([-1 * (W/2 - BOSS_INSET), 1 * (D/2 - BOSS_INSET), H - 1 - HOLE_DEPTH])
            cylinder(h = HOLE_DEPTH + 1.5, d = HOLE_D);
        // Insert hole at (+1, -1)
        translate([1 * (W/2 - BOSS_INSET), -1 * (D/2 - BOSS_INSET), H - 1 - HOLE_DEPTH])
            cylinder(h = HOLE_DEPTH + 1.5, d = HOLE_D);
        // Insert hole at (+1, +1)
        translate([1 * (W/2 - BOSS_INSET), 1 * (D/2 - BOSS_INSET), H - 1 - HOLE_DEPTH])
            cylinder(h = HOLE_DEPTH + 1.5, d = HOLE_D);
    }
}

base();
