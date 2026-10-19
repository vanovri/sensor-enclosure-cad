// lid (vl53l1x) — generated from Sensor_Gateway_Enclosure
// Source: manual_sketch_transcription; units mm; this is a design artifact, not a print guarantee.
// Generator: enclosure_generator.py (deterministic output)
$fn = 64;

W = 96; D = 66; WT = 2.4; R = 6;
PLATE = 4; LIP_H = 3; LIP_T = 2; CLR = 0.3;
HOLE_D = 3.2; CB_D = 6; CB_DEPTH = 2;
BOSS_INSET = 9;
OPEN_W = 8; OPEN_H = 8;
MOD_W = 13; MOD_H = 18;
HOLE_SPACING = 9; MOUNT_HOLE_D = 2.2;
POCKET = 1;
module rounded_rect(w, d, r) {
    offset(r = r) square([w - 2*r, d - 2*r], center = true);
}

module lid() {
    difference() {
        union() {
            linear_extrude(height = PLATE) rounded_rect(W, D, R);
            // Inner lip that registers into the cavity
            translate([0, 0, -LIP_H]) linear_extrude(height = LIP_H)
                difference() {
                    rounded_rect(W - 2*WT - 2*CLR, D - 2*WT - 2*CLR, max(0, R - WT - CLR));
                    rounded_rect(W - 2*WT - 2*CLR - 2*LIP_T, D - 2*WT - 2*CLR - 2*LIP_T, max(0, R - WT - CLR - LIP_T));
                }
        }
        // oled window
        translate([0, 8, -1])
            linear_extrude(height = PLATE + 2)
                rounded_rect(26, 14, 2);
        // Sensor aperture through the lid
        translate([0, 0, -LIP_H - 1]) linear_extrude(height = LIP_H + PLATE + 2)
            rounded_rect(OPEN_W, OPEN_H, min(1, OPEN_W/2, OPEN_H/2));
        // Module pocket on the underside
        translate([0, 0, -LIP_H - 1]) linear_extrude(height = LIP_H + POCKET + 1)
            rounded_rect(MOD_W, MOD_H, 1);
        // Module mounting holes (through the pocket floor)
        for (sx = [-1, 1]) {
            translate([sx * HOLE_SPACING/2, 0, -LIP_H - 1])
                cylinder(h = LIP_H + PLATE + 2, d = MOUNT_HOLE_D);
        }
        // Lid screw holes and counterbores
        for (mx = [-1, 1], my = [-1, 1]) {
            translate([mx * (W/2 - BOSS_INSET), my * (D/2 - BOSS_INSET), -LIP_H - 1])
                cylinder(h = LIP_H + PLATE + 2, d = HOLE_D);
            translate([mx * (W/2 - BOSS_INSET), my * (D/2 - BOSS_INSET), PLATE - CB_DEPTH])
                cylinder(h = CB_DEPTH + 1, d = CB_D);
        }
    }
}

lid();
