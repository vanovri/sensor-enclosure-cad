# sensor-enclosure-cad: performance and technical debt

Source crosscheck: 2026-11-08 WIB. Locations refer to the current production files. The unified diffs below are proposals only. Production code has not been changed. No elapsed-time improvement is claimed without measurement.

## 1. Require finite genuine numbers at the enclosure-spec boundary

Location: enclosure_generator.py:27-53.

The positive-number check accepts bool and does not reject NaN or positive infinity. The focused proposal adds the missing math import and validates required enclosure dimensions. Nested fastener/port/mount fields still need a separately specified schema; this proposal does not claim to validate them.

```diff
diff --git a/enclosure_generator.py b/enclosure_generator.py
--- a/enclosure_generator.py
+++ b/enclosure_generator.py
@@ -8,6 +8,7 @@
 
 import argparse
 import json
+import math
 import sys
 from pathlib import Path
 
@@ -37,8 +38,9 @@
     for key in REQUIRED_ENCLOSURE:
         if key not in enclosure:
             raise ValueError(f"missing enclosure field: {key}")
-        if key != "name" and (not isinstance(enclosure[key], (int, float)) or enclosure[key] <= 0):
-            raise ValueError(f"enclosure field {key} must be a positive number")
+        if key != "name" and (type(enclosure[key]) not in (int, float)
+                              or not math.isfinite(enclosure[key]) or enclosure[key] <= 0):
+            raise ValueError(f"enclosure field {key} must be a finite positive number")
     fasteners = data.get("fasteners") or {}
     for key in REQUIRED_FASTENERS:
         if key not in fasteners:
```

Validation: Reject booleans, NaN, infinity and strings before creating geometry or output files. Retain all current valid dimensions and mechanical checks.

## 2. Distinguish invalid ray queries from valid geometry with no intersections

Location: mesh_checks.py:112-117.

Normalizing a zero/non-finite vector can yield NaN and an empty hit list. Reject malformed direction, origin and limit before vectorized intersection math. The entire input guard is included rather than referring to additional unwritten changes.

```diff
diff --git a/mesh_checks.py b/mesh_checks.py
--- a/mesh_checks.py
+++ b/mesh_checks.py
@@ -113,7 +113,16 @@
     """Distances along a ray to triangle intersections (Moller-Trumbore)."""
     origin = np.array(origin, dtype=np.float64)
     direction = np.array(direction, dtype=np.float64)
-    direction = direction / np.linalg.norm(direction)
+    if origin.shape != (3,) or not np.isfinite(origin).all():
+        raise ValueError("ray origin must be a finite 3-vector")
+    if direction.shape != (3,) or not np.isfinite(direction).all():
+        raise ValueError("ray direction must be a finite nonzero 3-vector")
+    norm = np.linalg.norm(direction)
+    if not np.isfinite(norm) or norm <= 0:
+        raise ValueError("ray direction must be a finite nonzero 3-vector")
+    if isinstance(limit, bool) or not np.isfinite(limit) or limit <= 0:
+        raise ValueError("ray limit must be finite and positive")
+    direction = direction / norm
     v0 = mesh.points[mesh.triangles[:, 0]]
     v1 = mesh.points[mesh.triangles[:, 1]]
     v2 = mesh.points[mesh.triangles[:, 2]]
```

Validation: Test zero, non-finite and wrong-shape vectors, invalid limits and scaled-direction invariance. Preserve valid wall/hole reports. A separate public type contract may choose TypeError for nonnumeric limits.

