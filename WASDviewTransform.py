# -*- coding: utf-8 -*-
#
# WASDviewTransform - camera-relative WASD keyboard transform controller for 3D Slicer
# File name: WASDviewTransform.py
#
# Controls (camera-aligned):
#   W/S = up/down (screen)
#   A/D = left/right (screen)  <- LEFT/RIGHT inverted per user's request
#   Q/E = rotate (CW/CCW) ABOUT the camera's focal point  <- rotation direction inverted
#   Shift + any of the above = slow (precision) movement; factor adjustable in the panel
#
# Point axis (panel): pick two control points of a point list as UP and DOWN; the
#   "Move UP" / "Move DOWN" buttons translate the target along the DOWN->UP axis by a
#   fixed step and log the distance moved.
#
# Each target node gets its own Linear Transform named "WASD_<target name>".
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
        self.parent.helpText = ("W/A/S/D translate in view plane; Q/E rotate about camera focal point. "
                                "Hold Shift for slow (precision) movement. "
                                "Point axis: choose UP and DOWN control points and step the target along that axis. "
                                "Works on models, segmentations, volumes and markups (planes, points, curves). "
                                "Each target gets its own transform 'WASD_<target name>'.")
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
            "vtkMRMLMarkupsNode",  # planes, point lists, lines, curves, ROIs
            "vtkMRMLScalarVolumeNode",
            "vtkMRMLVectorVolumeNode",
            "vtkMRMLLabelMapVolumeNode",
        ]
        self.targetSelector.noneEnabled = False
        self.targetSelector.addEnabled = False
        self.targetSelector.removeEnabled = False
        formLayout.addRow("Target node:", self.targetSelector)

        # Shift slow-down factor (fraction of normal speed while Shift is held)
        self.slowFactorSpinBox = qt.QDoubleSpinBox()
        self.slowFactorSpinBox.setRange(0.01, 1.0)
        self.slowFactorSpinBox.setSingleStep(0.05)
        self.slowFactorSpinBox.setDecimals(2)
        self.slowFactorSpinBox.setValue(WASDviewController.SLOW_FACTOR)
        self.slowFactorSpinBox.toolTip = "Speed multiplier applied while Shift is held (0.25 = quarter speed)."
        formLayout.addRow("Shift slow factor:", self.slowFactorSpinBox)

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
        self.slowFactorSpinBox.valueChanged.connect(self.onSlowFactorChanged)

        # ---------------- Point axis: move along DOWN -> UP defined by two control points ----------------
        axisCollapsible = ctk.ctkCollapsibleButton()
        axisCollapsible.setText("Point axis (UP / DOWN)")
        self.layout.addWidget(axisCollapsible)
        axisLayout = qt.QFormLayout()
        axisCollapsible.setLayout(axisLayout)

        self.pointsSelector = slicer.qMRMLNodeComboBox()
        self.pointsSelector.setMRMLScene(slicer.mrmlScene)
        self.pointsSelector.nodeTypes = ["vtkMRMLMarkupsFiducialNode"]
        self.pointsSelector.noneEnabled = True
        self.pointsSelector.addEnabled = True
        self.pointsSelector.removeEnabled = False
        self.pointsSelector.toolTip = "Point list containing (at least) the two points that define the axis."
        axisLayout.addRow("Point list:", self.pointsSelector)

        self.upPointCombo = qt.QComboBox()
        self.upPointCombo.toolTip = "Control point that marks the UP end of the axis."
        axisLayout.addRow("UP point:", self.upPointCombo)

        self.downPointCombo = qt.QComboBox()
        self.downPointCombo.toolTip = "Control point that marks the DOWN end of the axis."
        axisLayout.addRow("DOWN point:", self.downPointCombo)

        self.stepSpinBox = qt.QDoubleSpinBox()
        self.stepSpinBox.setRange(0.01, 500.0)
        self.stepSpinBox.setSingleStep(0.5)
        self.stepSpinBox.setDecimals(2)
        self.stepSpinBox.setValue(1.0)
        self.stepSpinBox.setSuffix(" mm")
        self.stepSpinBox.toolTip = "Distance moved per button click."
        axisLayout.addRow("Step:", self.stepSpinBox)

        btnRow = qt.QHBoxLayout()
        self.moveUpButton = qt.QPushButton("▲ Move UP")
        self.moveDownButton = qt.QPushButton("▼ Move DOWN")
        self.moveUpButton.enabled = False
        self.moveDownButton.enabled = False
        btnRow.addWidget(self.moveUpButton)
        btnRow.addWidget(self.moveDownButton)
        axisLayout.addRow(btnRow)

        self.axisLog = qt.QPlainTextEdit()
        self.axisLog.setReadOnly(True)
        self.axisLog.setMaximumHeight(90)
        self.axisLog.setPlaceholderText("Click Start above, then Move UP / Move DOWN. Distance moved is shown here.")
        axisLayout.addRow(self.axisLog)

        self._pointsNode = None
        self._pointsObserverTags = []
        self._netAlongAxisMm = 0.0

        self.pointsSelector.currentNodeChanged.connect(self.onPointsNodeChanged)
        self.upPointCombo.currentIndexChanged.connect(self.onAxisSelectionChanged)
        self.downPointCombo.currentIndexChanged.connect(self.onAxisSelectionChanged)
        self.moveUpButton.clicked.connect(lambda: self.onMoveAlongAxis(+1.0))
        self.moveDownButton.clicked.connect(lambda: self.onMoveAlongAxis(-1.0))
        self.onPointsNodeChanged(self.pointsSelector.currentNode())

    def onSlowFactorChanged(self, value):
        if self.controller:
            self.controller.slowFactor = float(value)

    # ---------------- Point axis helpers ----------------

    def onPointsNodeChanged(self, node):
        # drop observers on the previous node
        if self._pointsNode is not None:
            for tag in self._pointsObserverTags:
                try:
                    self._pointsNode.RemoveObserver(tag)
                except Exception:
                    pass
        self._pointsObserverTags = []
        self._pointsNode = node
        if node is not None:
            for ev in (slicer.vtkMRMLMarkupsNode.PointAddedEvent,
                       slicer.vtkMRMLMarkupsNode.PointRemovedEvent,
                       slicer.vtkMRMLMarkupsNode.PointPositionDefinedEvent):
                try:
                    self._pointsObserverTags.append(node.AddObserver(ev, self._onPointsModified))
                except Exception:
                    pass
        self._netAlongAxisMm = 0.0
        self.refreshPointCombos()

    def _onPointsModified(self, caller=None, event=None):
        self.refreshPointCombos()

    def refreshPointCombos(self):
        upPrev = self.upPointCombo.currentText
        downPrev = self.downPointCombo.currentText
        labels = []
        if self._pointsNode is not None:
            n = self._pointsNode.GetNumberOfControlPoints()
            for i in range(n):
                label = self._pointsNode.GetNthControlPointLabel(i) or ("Point %d" % (i + 1))
                labels.append(label)
        for combo, prev, default in ((self.upPointCombo, upPrev, 0), (self.downPointCombo, downPrev, 1)):
            combo.blockSignals(True)
            combo.clear()
            for label in labels:
                combo.addItem(label)
            idx = combo.findText(prev) if prev else -1
            if idx < 0:
                idx = default if default < len(labels) else (len(labels) - 1)
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)
        self.onAxisSelectionChanged()

    def _axisDefinition(self):
        """Return (unit vector DOWN->UP in world coords, axis length mm) or (None, 0)."""
        if self._pointsNode is None:
            return None, 0.0
        iUp = self.upPointCombo.currentIndex
        iDown = self.downPointCombo.currentIndex
        n = self._pointsNode.GetNumberOfControlPoints()
        if iUp < 0 or iDown < 0 or iUp >= n or iDown >= n or iUp == iDown:
            return None, 0.0
        pUp = [0.0, 0.0, 0.0]; pDown = [0.0, 0.0, 0.0]
        self._pointsNode.GetNthControlPointPositionWorld(iUp, pUp)
        self._pointsNode.GetNthControlPointPositionWorld(iDown, pDown)
        v = [pUp[i] - pDown[i] for i in range(3)]
        length = math.sqrt(sum(c * c for c in v))
        if length < 1e-6:
            return None, 0.0
        return [c / length for c in v], length

    def onAxisSelectionChanged(self, *args):
        self._netAlongAxisMm = 0.0
        self._updateAxisButtons()

    def _updateAxisButtons(self):
        """Buttons are active only while the controller is running (Start pressed) and the axis is valid."""
        axis, _ = self._axisDefinition()
        ok = (self.controller is not None) and (axis is not None)
        self.moveUpButton.enabled = ok
        self.moveDownButton.enabled = ok
        if self.controller is None:
            self.moveUpButton.toolTip = "Click Start first."
            self.moveDownButton.toolTip = "Click Start first."
        elif axis is None:
            self.moveUpButton.toolTip = "Select two different points for UP and DOWN."
            self.moveDownButton.toolTip = "Select two different points for UP and DOWN."
        else:
            name = self.controller.targetNode.GetName()
            self.moveUpButton.toolTip = "Move '%s' one step toward the UP point." % name
            self.moveDownButton.toolTip = "Move '%s' one step toward the DOWN point." % name

    def onMoveAlongAxis(self, sign):
        if self.controller is None:
            slicer.util.errorDisplay("Click Start first; the UP/DOWN buttons move the started node.")
            return
        axis, axisLength = self._axisDefinition()
        if axis is None:
            slicer.util.errorDisplay("Select two different points for UP and DOWN.")
            return
        step = float(self.stepSpinBox.value)
        target = self.controller.targetNode
        txNode = self.controller.txNode
        t = [axis[i] * step * sign for i in range(3)]
        M = vtk.vtkMatrix4x4(); txNode.GetMatrixTransformToParent(M)
        T = vtk.vtkMatrix4x4(); T.Identity()
        T.SetElement(0, 3, t[0]); T.SetElement(1, 3, t[1]); T.SetElement(2, 3, t[2])
        newM = vtk.vtkMatrix4x4(); vtk.vtkMatrix4x4.Multiply4x4(T, M, newM)
        txNode.SetMatrixTransformToParent(newM)

        self._netAlongAxisMm += step * sign
        direction = "UP" if sign > 0 else "DOWN"
        self.axisLog.appendPlainText(
            "%s: moved %.2f mm toward %s   (net along axis: %+.2f mm; UP-DOWN distance %.2f mm)"
            % (target.GetName(), step, direction, self._netAlongAxisMm, axisLength))
        sb = self.axisLog.verticalScrollBar()
        sb.setValue(sb.maximum)

    def onStart(self):
        target = self.targetSelector.currentNode()
        if not target:
            slicer.util.errorDisplay("Please select a target node first.")
            return
        if self.controller:
            self.controller.disable()
            self.controller = None
        self.controller = WASDviewController(target)
        self.controller.slowFactor = float(self.slowFactorSpinBox.value)
        self.controller.enable()
        self.startButton.enabled = False
        self.stopButton.enabled = True
        self.statusLabel.text = ("Active: click 3D view and press W/A/S/D (translate) Q/E (rotate about view center). "
                                 "Hold Shift to move slowly.")
        self._netAlongAxisMm = 0.0
        self._updateAxisButtons()

    def onStop(self):
        if self.controller:
            self.controller.disable()
            self.controller = None
        self.startButton.enabled = True
        self.stopButton.enabled = False
        self.statusLabel.text = "Stopped."
        self._updateAxisButtons()

    def cleanup(self):
        self.onStop()
        self.onPointsNodeChanged(None)

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

# ----------------------- Shared transform insertion -----------------------

def _has_children(transformNode):
    """True if any node (including another transform) is directly under transformNode."""
    for node in slicer.util.getNodesByClass("vtkMRMLTransformableNode"):
        if node.GetTransformNodeID() == transformNode.GetID():
            return True
    return False


def _ensure_wasd_transform(targetNode):
    """
    Return the LinearTransform that drives targetNode, inserted as its direct parent and preserving
    any existing parent (chain: target -> WASD_<target> -> oldParent -> ...).
    Each target gets its own transform that starts at identity, so starting on a node never applies
    movements made to another node. The transform is reused while the target is still under it; after
    the target has been hardened it is reset to identity before reuse.
    """
    scene = slicer.mrmlScene
    txNode = scene.GetNodeByID(targetNode.GetAttribute("WASD.TransformID") or "")
    parent = targetNode.GetParentTransformNode()
    if txNode is not None and parent is not None and parent.GetID() == txNode.GetID():
        return txNode  # already driving this target
    if txNode is not None and _has_children(txNode):
        txNode = None  # still holding other nodes; leave it alone
    if txNode is None:
        txNode = scene.AddNewNodeByClass("vtkMRMLLinearTransformNode",
                                         scene.GenerateUniqueName("WASD_" + targetNode.GetName()))
        targetNode.SetAttribute("WASD.TransformID", txNode.GetID())
    else:
        txNode.SetMatrixTransformToParent(vtk.vtkMatrix4x4())  # identity
    txNode.SetAndObserveTransformNodeID(parent.GetID() if parent is not None else None)
    targetNode.SetAndObserveTransformNodeID(txNode.GetID())
    return txNode

# ----------------------- Controller (correct insertion + camera pivot) -----------------------

class WASDviewController(qt.QObject):
    """
    Controller that:
     - places the target's own LinearTransform (WASD_<target>) as its direct parent,
       preserving any existing parent transform (so chain becomes: target -> WASD_<target> -> oldParent -> ...).
     - applies left-multiplied translations/rotations in world coordinates using camera axes.
     - rotation pivot is camera focal point (dynamic each tick).
     - holding Shift multiplies translation and rotation speed by slowFactor (precision mode).
    """

    TICK_HZ = 60.0
    TRANSLATION_MM_PER_SEC = 24.0
    ROTATION_DEG_PER_SEC = 36.0
    SLOW_FACTOR = 0.25   # speed multiplier while Shift is held

    def __init__(self, targetNode):
        super().__init__()
        self.targetNode = targetNode
        self.slowFactor = self.SLOW_FACTOR
        self.timer = qt.QTimer()
        self.timer.setInterval(int(1000.0 / self.TICK_HZ))
        self.timer.timeout.connect(self.onTick)
        self._pressed = set()
        self._installed = False

        # find/create the target's 'WASD_<target>' transform and insert it as its direct parent
        self.txNode = _ensure_wasd_transform(self.targetNode)

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
        # Qt reports the same key code (e.g. Key_W) with or without Shift, so Shift+W is
        # captured here exactly like W. The Shift key itself is not consumed.
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

    def _shiftHeld(self):
        """Poll the live modifier state so Shift works whether pressed before or after a movement key."""
        try:
            mods = qt.QApplication.keyboardModifiers()
            return bool(int(mods) & int(qt.Qt.ShiftModifier))
        except Exception:
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

        speed = self.slowFactor if self._shiftHeld() else 1.0
        tstep = self.TRANSLATION_MM_PER_SEC / self.TICK_HZ * speed
        rstep = self.ROTATION_DEG_PER_SEC / self.TICK_HZ * speed

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
