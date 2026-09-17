# 3D Slicer WASD View Transform module

A minimal 3D Slicer ScriptedLoadableModule that enables camera-relative keyboard controls:
W/A/S/D = move in view plane, Q/E = rotate about camera focal point.
Hold **Shift** with any key for slow (precision) movement; the multiplier
("Shift slow factor", default 0.25) can be changed in the module panel, even while active.

## Usage
1. Place `WASDviewTransform.py` into Slicer's Additional Module Paths and restart Slicer.
2. Open **Transforms → WASD View Transform**, select a node (model, segmentation, volume, or markups such as a
   plane, point list or curve) and click **Start**. Each node gets its own transform, `WASD_<node name>`,
   so moving one node never shifts another.
3. Click inside a 3D view (to focus), then press W/A/S/D/Q/E to move/rotate. Hold Shift to slow down.
4. Click **Stop** to end control. Harden transform in the Transforms module to bake changes.

### Point axis (UP / DOWN)
Place two control points in a point list (e.g. condylion and gonion). In **Point axis**,
select the point list, choose which point is **UP** and which is **DOWN**, set the **Step** (mm),
and click **▲ Move UP** or **▼ Move DOWN**. The buttons are greyed out until you click **Start**;
they then move the node selected at the top (the started node) along the DOWN→UP axis by one step
per click, and the log below shows the node name, the distance moved, the net displacement along the
axis, and the UP–DOWN distance. Movement goes into the same `WASD_<node name>` transform, so it combines
with keyboard moves.

## License
MIT
