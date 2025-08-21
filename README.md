@"
# WASD View Transform

A minimal 3D Slicer ScriptedLoadableModule that enables camera-relative keyboard controls:
W/A/S/D = move in view plane, Q/E = rotate about camera focal point.

## Usage
1. Place `WASDviewTransform.py` into Slicer's Additional Module Paths and restart Slicer.
2. Open **Transforms → WASD View Transform**, select a node and click **Start**.
3. Click inside a 3D view (to focus), then press W/A/S/D/Q/E to move/rotate.
4. Click **Stop** to end control. Harden transform in the Transforms module to bake changes.

## License
MIT
"@ > README.md
