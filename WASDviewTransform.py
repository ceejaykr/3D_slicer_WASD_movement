# -*- coding: utf-8 -*-
#
# WASDviewTransform - camera-relative WASD keyboard transform controller for 3D Slicer
# File name: WASDviewTransform.py
#
# Controls (camera-aligned):
#   W/S = up/down (screen)
#   A/D = left/right (screen)  <- LEFT/RIGHT inverted per user's request
#   Q/E = rotate (CW/CCW) ABOUT the camera's focal point  <- rotation direction inverted
#
# Saves/uses a Linear Transform named "WASD_ViewTransform".
#

import math
from slicer.ScriptedLoadableModule import *
from __main__ import vtk, qt, ctk, slicer

class WASDviewTransform(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "WASD View Transform"
        self.parent.categories = ["Transforms"]
        self.parent.dependencies = []
        self.parent.contributors = ["Bianca (for Jun)"]
        self.parent.helpText = "W/A/S/D translate in view plane; Q/E rotate about camera focal point. Creates 'WASD_ViewTransform'."
        self.parent.acknowledgementText = "Camera-relative WASD transform."

class WASDviewTransformWidget(ScriptedLoadableModuleWidget):
    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        self.logic = WASDviewTransformLogic()

        collapsible = ctk.ctkCollapsibleButton()
        collapsible.setText("Controls")
        self.layout.addWidget(collapsible)
        formLayout = qt.QFormLayout()
        collapsible.setLayout(formLayout)

        # Node selector
        self.targetSelector = slicer.qMRMLNodeComboBox()
        self.targetSelector.setMRMLScene(slicer.mrmlScene)
        self.targetSelector.toolTip = "Pick a transformable node to drive."
        self.targetSelector.nodeTypes = [
            "vtkMRMLSegmentationNode",
            "vtkMRMLModelNode",
            "vtkMRMLScalarVolumeNode",
            "vtkMRMLVectorVolumeNode",
            "vtkMRMLLabelMapVolumeNode",
        ]
        self.targetSelector.noneEnabled = False
        self.targetSelector.addEnabled = False
        self.targetSelector.removeEnabled = False
        formLayout.addRow("Target node:", self.targetSelector)

        # Start / Stop
        row = qt.QHBoxLayout()
        self.startButton = qt.QPushButton("Start (capture WASD/QE)")
        self.stopButton = qt.QPushButton("Stop")
        self.stopButton.enabled = False
        row.addWidget(self.startButton)
        row.addWidget(self.stopButton)
        formLayout.addRow(row)

        self.statusLabel = qt.QLabel("")
        self.statusLabel.setStyleSheet("color: gray")
        formLayout.addRow(self.statusLabel)

        self.controller = None
        self.startButton.clicked.connect(self.onStart)
        self.stopButton.clicked.connect(self.onStop)

    def onStart(self):
        target = self.targetSelector.currentNode()
        if not target:
            slicer.util.errorDisplay("Please select a target node first.")
            return
        if self.controller:
            self.controller.disable()
            self.controller = None
        self.controller = WASDviewController(target)
        self.controller.enable()
        self.startButton.enabled = False
        self.stopButton.enabled = True
        self.statusLabel.text = "Active: click 3D view and press W/A/S/D (translate) Q/E (rotate about view center)."

    def onStop(self):
        if self.controller:
            self.controller.disable()
            self.controller = None
        self.startButton.enabled = True
        self.stopButton.enabled = False
        self.statusLabel.text = "Stopped."

    def cleanup(self):
        self.onStop()

class WASDviewTransformLogic(ScriptedLoadableModuleLogic):
    pass

# ----------------------- Helper to robustly get active 3D view -----------------------

def _get_active_threeD_view():
    lm = slicer.app.layoutManager()
    try:
        view = lm.activeThreeDView()
        if view:
            return view
    except Exception:
        pass
    try:
        count = lm.threeDWidgetCount()
    except Exception:
        count = 0
    for i in range(count):
        try:
            w = lm.threeDWidget(i)
            if w and w.isVisible():
                return w.threeDView()
        except Exception:
            continue
    try:
        return lm.threeDWidget(0).threeDView()
    except Exception:
        return None

# ----------------------- Controller (correct insertion + camera pivot) -----------------------

class WASDviewController(qt.QObject):
    """
    Controller that:
     - places a LinearTransform (WASD_ViewTransform) as the direct parent of the target node,
       preserving any existing parent transform (so chain becomes: target -> WASD_ViewTransform -> oldParent -> ...).
     - applies left-multiplied translations/rotations in world coordinates using camera axes.
     - rotation pivot is camera focal point (dynamic each tick).
    """

    TICK_HZ = 60.0
    TRANSLATION_MM_PER_SEC = 24.0
    ROTATION_DEG_PER_SEC = 36.0

    def __init__(self, targetNode):
        super().__init__()
        self.targetNode = targetNode
        self.timer = qt.QTimer()
        self.timer.setInterval(int(1000.0 / self.TICK_HZ))
        self.timer.timeout.connect(self.onTick)
        self._pressed = set()
        self._installed = False

        # 1) find or create transform node (unique name to avoid conflicts)
        nodes = slicer.util.getNodesByClass("vtkMRMLLinearTransformNode")
        wasdTx = None
        if isinstance(nodes, dict):
            for n in nodes.values():
                try:
                    if n.GetName() == "WASD_ViewTransform":
                        wasdTx = n
                        break
                except Exception:
                    continue
        elif isinstance(nodes, list):
            for n in nodes:
                try:
                    if n.GetName() == "WASD_ViewTransform":
                        wasdTx = n
                        break
                except Exception:
                    continue
        if wasdTx is None:
            wasdTx = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode", "WASD_ViewTransform")
        self.txNode = wasdTx

        # 2) Insert transform correctly:
        #    If target had parent P: we want chain target -> txNode -> P -> ...
        #    So set txNode's parent to P, then set target's parent to txNode.
        oldParent = self.targetNode.GetParentTransformNode()
        if oldParent is not None:
            try:
                self.txNode.SetAndObserveTransformNodeID(oldParent.GetID())
            except Exception:
                self.txNode.SetAttribute("ParentTransformID", oldParent.GetID())
        else:
            try:
                self.txNode.SetAndObserveTransformNodeID(None)
            except Exception:
                pass
        self.targetNode.SetAndObserveTransformNodeID(self.txNode.GetID())

    def enable(self):
        if not self._installed:
            slicer.app.installEventFilter(self)
            self._installed = True
        self.timer.start()
        slicer.util.showStatusMessage("WASD view controller active — click a 3D view and press W/A/S/D/Q/E", 3000)

    def disable(self):
        self.timer.stop()
        if self._installed:
            try:
                slicer.app.removeEventFilter(self)
            except Exception:
                pass
            self._installed = False
        slicer.util.showStatusMessage("WASD view controller stopped", 1500)

    def eventFilter(self, obj, event):
        et = event.type()
        if et == qt.QEvent.KeyPress and not event.isAutoRepeat():
            key = int(event.key())
            if key in (qt.Qt.Key_W, qt.Qt.Key_A, qt.Qt.Key_S, qt.Qt.Key_D, qt.Qt.Key_Q, qt.Qt.Key_E):
                self._pressed.add(key)
                return True
        elif et == qt.QEvent.KeyRelease and not event.isAutoRepeat():
            key = int(event.key())
            if key in (qt.Qt.Key_W, qt.Qt.Key_A, qt.Qt.Key_S, qt.Qt.Key_D, qt.Qt.Key_Q, qt.Qt.Key_E):
                self._pressed.discard(key)
                return True
        return False

    def onTick(self):
        if not self._pressed:
            return
        view = _get_active_threeD_view()
        if view is None:
            return
        try:
            camNode = slicer.modules.cameras.logic().GetViewActiveCameraNode(view.mrmlViewNode())
            cam = camNode.GetCamera() if camNode else None
        except Exception:
            cam = None
        if not cam:
            return

        # camera axes in world coordinates
        fwd = cam.GetDirectionOfProjection()
        up = cam.GetViewUp()
        def norm(v):
            mag = math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2]) or 1.0
            return [v[0]/mag, v[1]/mag, v[2]/mag]
        fwd = norm(fwd); up = norm(up)
        right = [ up[1]*fwd[2] - up[2]*fwd[1],
                  up[2]*fwd[0] - up[0]*fwd[2],
                  up[0]*fwd[1] - up[1]*fwd[0] ]

        tstep = self.TRANSLATION_MM_PER_SEC / self.TICK_HZ
        rstep = self.ROTATION_DEG_PER_SEC / self.TICK_HZ

        # TRANSLATION: NOTE left/right inverted per request:
        # W = up, S = down (unchanged)
        # A = move RIGHT (inverted)
        # D = move LEFT (inverted)
        t = [0.0,0.0,0.0]
        if qt.Qt.Key_W in self._pressed:
            t = [t[i] + up[i]*tstep for i in range(3)]
        if qt.Qt.Key_S in self._pressed:
            t = [t[i] - up[i]*tstep for i in range(3)]
        if qt.Qt.Key_A in self._pressed:
            # inverted: A moves RIGHT
            t = [t[i] + right[i]*tstep for i in range(3)]
        if qt.Qt.Key_D in self._pressed:
            # inverted: D moves LEFT
            t = [t[i] - right[i]*tstep for i in range(3)]
        if any(abs(v) > 1e-12 for v in t):
            M = vtk.vtkMatrix4x4(); self.txNode.GetMatrixTransformToParent(M)
            T = vtk.vtkMatrix4x4(); T.Identity()
            T.SetElement(0,3, t[0]); T.SetElement(1,3, t[1]); T.SetElement(2,3, t[2])
            newM = vtk.vtkMatrix4x4(); vtk.vtkMatrix4x4.Multiply4x4(T, M, newM)
            self.txNode.SetMatrixTransformToParent(newM)

        # ROTATION: dynamic pivot = camera focal point (world)
        # Rotation direction inverted per request:
        # Q now produces clockwise rotation, E produces counter-clockwise.
        if qt.Qt.Key_Q in self._pressed or qt.Qt.Key_E in self._pressed:
            try:
                pivotRAS = list(cam.GetFocalPoint())
            except Exception:
                bounds = [0.0]*6
                try:
                    self.targetNode.GetRASBounds(bounds)
                    pivotRAS = [(bounds[0]+bounds[1])*0.5, (bounds[2]+bounds[3])*0.5, (bounds[4]+bounds[5])*0.5]
                except Exception:
                    pivotRAS = [0.0,0.0,0.0]
            # inverted sign here: Q => -rstep (clockwise), E => +rstep (counterclockwise)
            deg = -rstep if qt.Qt.Key_Q in self._pressed else +rstep

            M = vtk.vtkMatrix4x4(); self.txNode.GetMatrixTransformToParent(M)
            Tto = vtk.vtkMatrix4x4(); Tto.Identity()
            Tto.SetElement(0,3, pivotRAS[0]); Tto.SetElement(1,3, pivotRAS[1]); Tto.SetElement(2,3, pivotRAS[2])
            Tback = vtk.vtkMatrix4x4(); Tback.Identity()
            Tback.SetElement(0,3, -pivotRAS[0]); Tback.SetElement(1,3, -pivotRAS[1]); Tback.SetElement(2,3, -pivotRAS[2])
            Rtf = vtk.vtkTransform(); Rtf.Identity()
            Rtf.RotateWXYZ(deg, fwd[0], fwd[1], fwd[2])
            R = vtk.vtkMatrix4x4(); R.DeepCopy(Rtf.GetMatrix())
            tmp1 = vtk.vtkMatrix4x4(); vtk.vtkMatrix4x4.Multiply4x4(R, Tback, tmp1)
            tmp2 = vtk.vtkMatrix4x4(); vtk.vtkMatrix4x4.Multiply4x4(Tto, tmp1, tmp2)
            newM = vtk.vtkMatrix4x4(); vtk.vtkMatrix4x4.Multiply4x4(tmp2, M, newM)
            self.txNode.SetMatrixTransformToParent(newM)
