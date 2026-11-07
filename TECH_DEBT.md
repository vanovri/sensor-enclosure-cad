# sensor-enclosure-cad performance and technical debt

Reviewed 2026-11-07. These are proposals, not applied production changes. Line numbers refer to the reviewed working tree. No runtime speedup is claimed without measurement.

## 1. Reject boolean and non-finite dimensions explicitly

Location: `enclosure_generator.py:40-42`.

Python treats bool as an int. NaN also passes the `<= 0` check, and positive infinity passes. A malformed spec can therefore escape the loader's stated numeric contract before later geometry checks or serialization. Add `import math` to the module for this proposal. Apply equivalent finite/type validation to fastener, port, window, sensor-mount, and minimum fields; the excerpt covers enclosure dimensions only.

Proposed change:

```diff
--- a/enclosure_generator.py
+++ b/enclosure_generator.py
@@ -1,2 +1,3 @@
-        if key != "name" and (not isinstance(enclosure[key], (int, float)) or enclosure[key] <= 0):
-            raise ValueError(f"enclosure field {key} must be a positive number")
+        if key != "name" and (type(enclosure[key]) not in (int, float)
+                              or not math.isfinite(enclosure[key]) or enclosure[key] <= 0):
+            raise ValueError(f"enclosure field {key} must be a finite positive number")
```

Validation: Test True, NaN, Infinity, numeric strings, and each nested numeric family. Assert rejection happens before any generated file is created.

## 2. Make invalid ray directions fail explicitly

Location: `mesh_checks.py:116-117`.

A zero direction divides by zero and can become NaN. The intersection mask then returns an empty list, which some mechanical checks interpret as an open hole. The direct ray API should distinguish an invalid query from valid no-hit geometry. Validate origin shape/finiteness and positive finite limit as the same boundary contract.

Proposed change:

```diff
--- a/mesh_checks.py
+++ b/mesh_checks.py
@@ -1 +1,4 @@
-    direction = direction / np.linalg.norm(direction)
+    norm = np.linalg.norm(direction)
+    if direction.shape != (3,) or not np.isfinite(direction).all() or not np.isfinite(norm) or norm <= 0:
+        raise ValueError("ray direction must be a finite nonzero 3-vector")
+    direction = direction / norm
```

Validation: Add zero/NaN/Infinity/wrong-shape direction tests and invalid origin/limit cases. Preserve scaled-direction invariance, wall measurements, and current mechanical report outcomes.
