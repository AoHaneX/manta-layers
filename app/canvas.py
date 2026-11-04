"""Interactive canvas: the view of the document scene and every mouse and keyboard tool.

Rendering (layer pixels, caches, exports) stays in app/graphics.py; this view
only turns user input into previews and calls the main window to commit them.
"""
from __future__ import annotations

from math import atan2, cos, degrees, hypot, radians, sin
from typing import TYPE_CHECKING

from PIL import Image, ImageChops
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsView

from . import selection
from .graphics import (
    MAX_ZOOM,
    CurvedTextGraphicItem,
    checker_brush,
    eraser_dab_origin,
    eraser_source_position,
    layer_transform,
    pil_to_qimage,
    render_layer_with_mask,
    selection_outline,
    selection_overlay,
    stamp_eraser_stroke,
)
from .model import Layer
from .shape_item import arrow_head_path, shape_from_drag, shape_path
from .theme import COLORS

if TYPE_CHECKING:
    from .window import MainWindow

MIN_ZOOM = 0.01
ROTATION_HANDLE_DISTANCE = 35  # pixels écran au-dessus du cadre
SNAP_DISTANCE = 8  # screen pixels within which a dragged layer snaps to a guide


class CanvasView(QGraphicsView):
    """Sélection, déplacement à la souris, quatre poignées et rotation."""

    def __init__(self, window: MainWindow):
        super().__init__()
        # Not named "window": that would hide QWidget.window().
        self.main_window = window
        self.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self._pan_last = None
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QColor(COLORS["canvas"]))
        self._checker = checker_brush()
        self.mode = None
        self.old_layer = None
        self.drag_item = None
        self.handle_index = None
        self.selection_drag: dict | None = None
        # Lasso outline being drawn (free or polygonal), in document coordinates.
        self.lasso_points: list[QPointF] | None = None
        self.lasso_hover: QPointF | None = None
        self.lasso_modifiers = Qt.KeyboardModifier.NoModifier
        # Shape being drawn with a shape tool: {"start", "end", "modifiers"}.
        self.shape_drag: dict | None = None
        # Layers being dragged (start positions), snapping targets and guides shown.
        self.move_start: dict = {}
        self.move_press = QPointF()
        self.snap_targets: tuple[list[float], list[float]] = ([], [])
        self.active_guides: list[tuple[str, float]] = []
        # Pixels being moved with Ctrl+drag inside the selection.
        self.lift: dict | None = None
        self.selection_overlay_image: QImage | None = None
        self.selection_path: QPainterPath | None = None
        self.selection_box: tuple[int, int, int, int] | None = None
        self.fixed_world = None
        self.fixed_local = None
        self.corner_local = None
        self.angle_offset = 0
        self.fixed_center = None
        self.eraser_item: QGraphicsPixmapItem | None = None
        self.eraser_points: list[QPointF] = []
        self.eraser_cursor_local: QPointF | None = None
        # Live eraser preview, computed in source pixels exactly like the final render.
        self.eraser_base: Image.Image | None = None  # layer pixels before the stroke, not flipped
        self.eraser_coverage: Image.Image | None = None  # coverage of the current stroke
        self.eraser_settings: dict | None = None  # stroke settings (size, shape…) without points
        self.eraser_flips = (False, False)
        self.eraser_pixmap: QPixmap | None = None  # displayed pixmap, updated area by area
        self.eraser_original_pixmap: QPixmap | None = None
        self.eraser_preview_last: QPointF | None = None
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def drawBackground(self, painter: QPainter, rect: QRectF | QRect) -> None:
        super().drawBackground(painter, rect)
        if not self.scene():
            return
        area = QRectF(0, 0, self.main_window.document.width, self.main_window.document.height).intersected(QRectF(rect))
        if area.isEmpty():
            return
        background = self.main_window.document.background
        painter.save()
        if background:
            painter.fillRect(area, QColor(background))
        else:
            painter.setBrushOrigin(0, 0)
            painter.fillRect(area, self._checker)
        painter.restore()

    def selected_graphic(self):
        for item in self.scene().selectedItems() if self.scene() else []:
            if self.main_window.document.layer(item.data(0)):
                return item
        return None

    def graphic_for(self, layer_id: str | None):
        if not layer_id or self.scene() is None:
            return None
        return next((item for item in self.scene().items() if item.data(0) == layer_id), None)

    def tool_target_graphic(self):
        """Graphique du calque visé par les outils, même s'il n'est plus sélectionné."""
        return self.graphic_for(self.main_window.tool_target_id())

    def local_handles(self, item):
        bounds = item.boundingRect()
        x, y, w, h = bounds.x(), bounds.y(), bounds.width(), bounds.height()
        return [QPointF(x, y), QPointF(x + w, y), QPointF(x + w, y + h), QPointF(x, y + h)]

    def rotation_point(self, item):
        # Distance constante à l'écran, quels que soient l'échelle du calque et le zoom.
        bounds = item.boundingRect()
        top = item.mapToScene(QPointF(bounds.center().x(), bounds.top()))
        center = item.mapToScene(bounds.center())
        direction = top - center
        length = hypot(direction.x(), direction.y())
        if length < 1e-9:
            direction, length = QPointF(0, -1), 1.0
        distance = ROTATION_HANDLE_DISTANCE / self.transform().m11()
        return top + direction * (distance / length)

    def drawForeground(self, painter: QPainter, rect: QRectF | QRect) -> None:
        super().drawForeground(painter, rect)
        if not self.scene():
            return
        painter.save()
        factor = self.transform().m11()
        border_pen = QPen(QColor(COLORS["canvas_border"]), 1)
        border_pen.setCosmetic(True)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(0, 0, self.main_window.document.width, self.main_window.document.height))
        self._draw_selection(painter)
        self._draw_guides(painter)
        # Transform and shape handles only make sense without an active tool.
        item = None if self.main_window.any_tool_active() else self.selected_graphic()
        layer = self.main_window.document.layer(item.data(0)) if item else None
        if isinstance(item, CurvedTextGraphicItem) and layer:
            if layer.show_curve_guide:
                guide_pen = QPen(QColor(COLORS["primary"]), 1)
                guide_pen.setCosmetic(True)
                guide_pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(guide_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(item.sceneTransform().map(item.visual_guide_path()))
            polygon = [item.mapToScene(point) for point in item.control_polygon_local()]
            if polygon:
                # Bézier tangents of the custom shape: start -> P1 and P2 -> end.
                tangent_pen = QPen(QColor(COLORS["muted"]), 1)
                tangent_pen.setCosmetic(True)
                tangent_pen.setStyle(Qt.PenStyle.DotLine)
                painter.setPen(tangent_pen)
                painter.drawLine(polygon[0], polygon[1])
                painter.drawLine(polygon[2], polygon[3])
            if not layer.locked:
                radius = 7 / factor
                painter.setPen(QPen(QColor(COLORS["background"]), 1 / factor))
                painter.setBrush(QColor(COLORS["primary"]))
                for handle in item.shape_handles_local():
                    painter.drawEllipse(item.mapToScene(handle), radius, radius)
        if item:
            size = 9 / factor
            painter.setBrush(QColor(COLORS["primary"]))
            painter.setPen(QPen(QColor(COLORS["background"]), 1 / factor))
            for local in self.local_handles(item):
                p = item.mapToScene(local)
                painter.drawRect(QRectF(p.x() - size/2, p.y() - size/2, size, size))
            p = self.rotation_point(item)
            painter.setBrush(QColor(COLORS["rotation_handle"]))
            painter.drawEllipse(p, size/2, size/2)
        target = self.eraser_item or self.tool_target_graphic()
        if self.main_window.eraser_active and isinstance(target, QGraphicsPixmapItem):
            local = self.eraser_cursor_local
            if local is not None:
                size = self.main_window.eraser_size.value()
                path = QPainterPath()
                # Same placement as the saved dabs, soft or pixel art.
                bounds = QRectF(eraser_dab_origin(local.x(), size), eraser_dab_origin(local.y(), size), size, size)
                if self.main_window.eraser_shape.currentData() == "square" and self.main_window.eraser_pixel_art.isChecked():
                    path.addRect(bounds)
                else:
                    path.addEllipse(bounds)
                scene_path = target.sceneTransform().map(path)
                preview_pen = QPen(QColor(COLORS["primary"]), 1)
                preview_pen.setCosmetic(True)
                painter.setPen(preview_pen)
                fill = QColor(COLORS["primary"])
                fill.setAlpha(45)
                painter.setBrush(fill)
                painter.drawPath(scene_path)
            if len(self.eraser_points) > 1:
                path = QPainterPath(self.eraser_points[0])
                for point in self.eraser_points[1:]:
                    path.lineTo(point)
                scene_path = target.sceneTransform().map(path)
                stroke_color = QColor(COLORS["primary"])
                stroke_color.setAlpha(150)
                stroke_pen = QPen(stroke_color, 2)
                stroke_pen.setCosmetic(True)
                painter.setPen(stroke_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(scene_path)
        painter.restore()

    # --- Alignment guides and snapping while a layer is dragged ------------------------

    def _start_move(self, item, press: QPointF) -> None:
        """Remember where the dragged layers start and what they can align with."""
        window = self.main_window
        moving = [item]
        layer_id = item.data(0)
        if layer_id in window.checked_ids:
            # Dragging a checked layer moves the whole multiple selection.
            for other_id in window.checked_layer_ids():
                layer = window.document.layer(other_id)
                graphic = self.graphic_for(other_id)
                if (other_id != layer_id and graphic is not None and layer is not None and not layer.locked
                        and graphic.isVisible()):
                    moving.append(graphic)
        self.move_start = {graphic: QPointF(graphic.pos()) for graphic in moving}
        self.move_press = QPointF(press)
        document = window.document
        xs = [0.0, document.width / 2, float(document.width)]
        ys = [0.0, document.height / 2, float(document.height)]
        for graphic in self.scene().items():
            if graphic in self.move_start or not graphic.isVisible() or not document.layer(graphic.data(0)):
                continue
            rect = graphic.sceneBoundingRect()
            xs += [rect.left(), rect.center().x(), rect.right()]
            ys += [rect.top(), rect.center().y(), rect.bottom()]
        self.snap_targets = (xs, ys)
        self.active_guides = []

    @staticmethod
    def _closest(edges, targets, threshold):
        best = None
        for edge in edges:
            for target in targets:
                distance = target - edge
                if abs(distance) <= threshold and (best is None or abs(distance) < abs(best)):
                    best = distance
        return best

    def _moving_rect(self) -> QRectF:
        rect = QRectF()
        for graphic in self.move_start:
            rect = rect.united(graphic.sceneBoundingRect())
        return rect

    def _after_move_step(self, modifiers, mouse: QPointF) -> None:
        """Snap the dragged layers to the nearest guide, show the guides, move the selection with them.

        Positions always derive from the pointer travel since the press, so a
        snap never accumulates once the pointer moves away from the guide.
        """
        if self.drag_item not in self.move_start:
            return
        delta = mouse - self.move_press
        for graphic, origin in self.move_start.items():
            graphic.setPos(origin + delta)
        xs, ys = self.snap_targets
        zoom = max(1e-6, self.transform().m11())
        rect = self._moving_rect()
        if self.main_window.snap_enabled and not modifiers & Qt.KeyboardModifier.AltModifier:
            dx = self._closest((rect.left(), rect.center().x(), rect.right()), xs, SNAP_DISTANCE / zoom) or 0.0
            dy = self._closest((rect.top(), rect.center().y(), rect.bottom()), ys, SNAP_DISTANCE / zoom) or 0.0
            if dx or dy:
                for graphic in self.move_start:
                    graphic.setPos(graphic.pos() + QPointF(dx, dy))
                rect = self._moving_rect()
        horizontal = (rect.left(), rect.center().x(), rect.right())
        vertical = (rect.top(), rect.center().y(), rect.bottom())
        tolerance = 0.5 / zoom
        self.active_guides = sorted(
            {("v", x) for x in xs if any(abs(x - edge) <= tolerance for edge in horizontal)}
            | {("h", y) for y in ys if any(abs(y - edge) <= tolerance for edge in vertical)}
        )
        self.viewport().update()

    def _finish_move(self) -> list:
        """Clear the guides; return the graphics moved along with the dragged one, if any."""
        group = list(self.move_start)
        self.move_start, self.active_guides = {}, []
        return group if len(group) > 1 else []

    def _draw_guides(self, painter: QPainter) -> None:
        if not self.active_guides:
            return
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        pen = QPen(QColor(COLORS["copper"]), 1, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        for orientation, value in self.active_guides:
            if orientation == "v":
                painter.drawLine(QPointF(value, visible.top()), QPointF(value, visible.bottom()))
            else:
                painter.drawLine(QPointF(visible.left(), value), QPointF(visible.right(), value))

    def update_selection_visual(self, mask, show_mask: bool) -> None:
        """Recompute the tint and outline once per selection change."""
        if mask is None or selection.is_empty(mask):
            self.selection_overlay_image = self.selection_path = self.selection_box = None
        else:
            self.selection_overlay_image = selection_overlay(mask, show_mask)
            self.selection_path = selection_outline(mask)
            self.selection_box = selection.bounds(mask)
        self.viewport().update()

    def _selection_pens(self) -> tuple[QPen, QPen]:
        # White under black dashes: visible on any background, at any zoom.
        under = QPen(QColor("white"), 1)
        under.setCosmetic(True)
        over = QPen(QColor("black"), 1, Qt.PenStyle.DashLine)
        over.setCosmetic(True)
        return under, over

    def _draw_selection(self, painter: QPainter) -> None:
        document = self.main_window.document
        if self.selection_overlay_image is not None:
            painter.drawImage(QRectF(0, 0, document.width, document.height), self.selection_overlay_image)
        outlines = []
        if self.selection_path is not None:
            outlines.append(self.selection_path)
        elif self.selection_box is not None:
            box = QPainterPath()
            left, top, right, bottom = self.selection_box
            box.addRect(QRectF(left, top, right - left, bottom - top))
            outlines.append(box)
        if self.selection_drag is not None:
            outlines.append(self._drag_shape_path())
        if self.lasso_points:
            outlines.append(self._lasso_path())
        if self.shape_drag is not None:
            outlines.append(self._shape_preview_path())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for path in outlines:
            for pen in self._selection_pens():
                painter.setPen(pen)
                painter.drawPath(path)
        if self.lift is not None:
            painter.setOpacity(0.85)
            painter.drawPixmap(self.lift["origin"] + self.lift["delta"], self.lift["pixmap"])
            painter.setOpacity(1.0)

    def _drag_rect(self) -> QRectF:
        drag = self.selection_drag
        assert drag is not None
        rect = QRectF(drag["start"], drag["end"]).normalized()
        if self.main_window.selection_pixel_perfect.isChecked():
            rect = QRectF(round(rect.left()), round(rect.top()),
                          round(rect.right()) - round(rect.left()), round(rect.bottom()) - round(rect.top()))
        return rect

    def _drag_shape_path(self) -> QPainterPath:
        path = QPainterPath()
        rect = self._drag_rect()
        if self.selection_drag is not None and self.selection_drag["tool"] == "ellipse":
            path.addEllipse(rect)
        else:
            path.addRect(rect)
        return path

    def _shape_preview_path(self) -> QPainterPath:
        drag = self.shape_drag
        assert drag is not None
        layer = shape_from_drag(self.main_window.shape_tool or "rectangle",
                                (drag["start"].x(), drag["start"].y()), (drag["end"].x(), drag["end"].y()),
                                bool(drag["modifiers"] & Qt.KeyboardModifier.ShiftModifier), "#000000")
        path = shape_path(layer)
        if layer.shape_type == "arrow":
            path = path.united(arrow_head_path(layer))
        return layer_transform(layer).map(path)

    def _lasso_path(self) -> QPainterPath:
        """Lasso being drawn: its points, the pointer for the polygonal lasso, closed back to the start."""
        points = list(self.lasso_points or [])
        if self.lasso_hover is not None and self.main_window.selection_tool == "polygon":
            points.append(self.lasso_hover)
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        if len(points) > 2:
            path.closeSubpath()
        return path

    def finish_lasso(self) -> None:
        points, modifiers = self.lasso_points, self.lasso_modifiers
        self.lasso_points, self.lasso_hover = None, None
        if points:
            self.main_window.apply_selection_polygon([(point.x(), point.y()) for point in points], modifiers)
        self.viewport().update()

    def cancel_lasso(self) -> bool:
        if self.lasso_points is None:
            return False
        self.lasso_points, self.lasso_hover = None, None
        self.viewport().update()
        return True

    def _lasso_press(self, event, scene_position: QPointF, modifiers) -> None:
        if self.main_window.selection_tool == "lasso" or self.lasso_points is None:
            self.lasso_points, self.lasso_modifiers = [scene_position], modifiers
            return
        # Polygonal lasso: a click near the first point closes the outline.
        first = self.mapFromScene(self.lasso_points[0])
        if len(self.lasso_points) >= 3 and (first - event.position().toPoint()).manhattanLength() <= 10:
            self.finish_lasso()
            return
        self.lasso_points.append(scene_position)

    def _selection_press(self, event) -> None:
        scene_position = self.mapToScene(event.position().toPoint())
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier and self.lasso_points is None:
            lift = self.main_window.lift_selection(scene_position)
            if lift is not None:
                self.lift = {**lift, "start": scene_position, "delta": QPointF(0, 0)}
            return
        if self.main_window.selection_tool in ("lasso", "polygon"):
            self._lasso_press(event, scene_position, modifiers)
            return
        if self.main_window.selection_tool == "wand":
            self.main_window.apply_magic_wand(scene_position, modifiers)
            return
        self.selection_drag = {"tool": self.main_window.selection_tool, "start": scene_position,
                               "end": scene_position, "modifiers": modifiers}

    def _hit_handle(self, item, viewport_pos):
        if isinstance(item, CurvedTextGraphicItem):
            for index, local in enumerate(item.shape_handles_local()):
                if (self.mapFromScene(item.mapToScene(local)) - viewport_pos).manhattanLength() <= 15:
                    return "shape", index
        targets = [("resize", i, item.mapToScene(pt)) for i, pt in enumerate(self.local_handles(item))]
        targets.append(("rotate", None, self.rotation_point(item)))
        for mode, index, world in targets:
            if (self.mapFromScene(world) - viewport_pos).manhattanLength() <= 13:
                return mode, index
        return None, None

    def _start_eraser_stroke(self, event) -> None:
        layer_id = self.main_window.tool_target_id()
        item = self.graphic_for(layer_id)
        layer = self.main_window.document.layer(layer_id)
        if not layer or not isinstance(item, QGraphicsPixmapItem):
            self.main_window.statusBar().showMessage(
                "La gomme nécessite un calque image sélectionné", 3000
            )
            return
        if layer.locked:
            self.main_window.statusBar().showMessage(
                "Déverrouillez le calque pour utiliser la gomme", 3000
            )
            return
        local = item.mapFromScene(self.mapToScene(event.position().toPoint()))
        if not item.boundingRect().contains(local):
            return
        if not self.begin_eraser_preview(item, layer):
            return
        if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                and self.main_window.last_eraser_point
                and self.main_window.last_eraser_layer_id == layer.id):
            self.eraser_points = [QPointF(*self.main_window.last_eraser_point), local]
        else:
            self.eraser_points = [local]
        self._apply_eraser_preview_segment(self.eraser_points[0], local)
        self.eraser_preview_last = local
        self.eraser_cursor_local = local

    def mousePressEvent(self, event):
        self.setFocus()
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            # Un outil actif ne modifie jamais la sélection : il continue de
            # viser le dernier calque choisi.
            if self.main_window.eraser_active:
                self._start_eraser_stroke(event)
                self.viewport().update()
                event.accept()
                return
            if self.main_window.picker_active:
                item = self.itemAt(event.position().toPoint())
                self.main_window.sample_canvas_color(item, self.mapToScene(event.position().toPoint()))
                event.accept()
                return
            if self.main_window.paint_mode:
                self.main_window.paint_canvas_color(self.mapToScene(event.position().toPoint()))
                event.accept()
                return
            if self.main_window.shape_tool:
                position = self.mapToScene(event.position().toPoint())
                self.shape_drag = {"start": position, "end": position, "modifiers": event.modifiers()}
                event.accept()
                return
            if self.main_window.text_tool_active:
                self.main_window.begin_inline_text_create(self.mapToScene(event.position().toPoint()))
                event.accept()
                return
            if self.main_window.selection_tool:
                self._selection_press(event)
                self.viewport().update()
                event.accept()
                return
            item = self.selected_graphic()
            layer = self.main_window.document.layer(item.data(0)) if item else None
            if item and layer and not layer.locked:
                mode, handle = self._hit_handle(item, event.position().toPoint())
                if mode:
                    self.mode = mode
                    self.old_layer = self.main_window.document.clone()
                    self.drag_item = item
                    self.handle_index = handle
                    if mode == "resize":
                        local = self.local_handles(item)
                        self.corner_local = local[handle]
                        self.fixed_local = local[(handle + 2) % 4]
                        self.fixed_world = item.mapToScene(self.fixed_local)
                    elif mode == "rotate":
                        self.fixed_center = item.mapToScene(item.boundingRect().center())
                        sp = self.mapToScene(event.position().toPoint())
                        self.angle_offset = degrees(atan2(sp.y()-self.fixed_center.y(), sp.x()-self.fixed_center.x())) - layer.rotation
                    event.accept()
                    return
            at = self.itemAt(event.position().toPoint())
            at_layer = self.main_window.document.layer(at.data(0)) if at else None
            if at_layer and not at_layer.locked:
                self.mode = "move"
                self.old_layer = self.main_window.document.clone()
                self.drag_item = at
                self._start_move(at, self.mapToScene(event.position().toPoint()))
        super().mousePressEvent(event)
        self.viewport().update()

    def mouseDoubleClickEvent(self, event):
        if self.lasso_points is not None and self.main_window.selection_tool == "polygon":
            # The double click's first press already added its point.
            self.finish_lasso()
            event.accept()
            return
        # Double-clicking a text edits its content directly on the canvas.
        if event.button() == Qt.MouseButton.LeftButton and not self.main_window.any_tool_active():
            item = self.itemAt(event.position().toPoint())
            layer = self.main_window.document.layer(item.data(0)) if item else None
            if isinstance(item, CurvedTextGraphicItem) and layer and not layer.locked:
                self.mode = self.drag_item = self.old_layer = None
                self.main_window.begin_inline_text_edit(layer.id)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        # Copy, cut and paste are window actions whose shortcuts are handled before
        # this event. Delete is also an action; it stays here, with its Backspace
        # alias, for a canvas whose window is not shown (its shortcuts are inactive).
        if event.key() == Qt.Key.Key_Escape and self.cancel_lasso():
            event.accept()
            return
        if self.lasso_points is not None and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish_lasso()
            event.accept()
            return
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)
                and self.main_window.selection_mask is not None):
            # Enter separates the selected pixels into a new layer, like the button of the selection tools.
            self.main_window.selection_to_new_layer(cut=True)
            event.accept()
            return
        if self.lasso_points is not None and event.key() == Qt.Key.Key_Backspace:
            self.lasso_points.pop()  # polygonal lasso: remove the last point
            if not self.lasso_points:
                self.lasso_points = None
            self.viewport().update()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            # With an active selection, Delete erases its content instead of the layer.
            self.main_window.delete_selection_or_layer()
            event.accept()
            return
        arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                  Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if event.key() in arrows and not self.main_window.any_tool_active():
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            dx, dy = arrows[event.key()]
            if self.main_window.nudge_layer(dx * step, dy * step):
                event.accept()
                return
        if event.key() == Qt.Key.Key_BracketLeft:
            self.main_window.adjust_eraser_size(-1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_BracketRight:
            self.main_window.adjust_eraser_size(1)
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if item and self.main_window.document.layer(item.data(0)):
            self.main_window.select_layer(item.data(0))
        self.main_window.show_canvas_context_menu(event.globalPos())
        event.accept()

    def dragEnterEvent(self, event):
        if self.main_window.image_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.main_window.image_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = self.main_window.image_paths_from_mime(event.mimeData())
        if paths:
            self.main_window._import_paths(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if self._pan_last is not None:
            pos = event.position().toPoint()
            delta = pos - self._pan_last
            self._pan_last = pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        if self.shape_drag is not None:
            self.shape_drag["end"] = self.mapToScene(event.position().toPoint())
            self.shape_drag["modifiers"] = event.modifiers()
            self.viewport().update()
            event.accept()
            return
        if self.lasso_points is not None:
            position = self.mapToScene(event.position().toPoint())
            if self.main_window.selection_tool == "polygon":
                self.lasso_hover = position
            elif event.buttons() & Qt.MouseButton.LeftButton:
                step = 1 / max(1e-6, self.transform().m11())  # one screen pixel
                if (position - self.lasso_points[-1]).manhattanLength() >= step:
                    self.lasso_points.append(position)
            self.viewport().update()
            event.accept()
            return
        if self.selection_drag is not None or self.lift is not None:
            position = self.mapToScene(event.position().toPoint())
            if self.selection_drag is not None:
                self.selection_drag["end"] = position
            else:
                delta = position - self.lift["start"]
                self.lift["delta"] = QPointF(round(delta.x()), round(delta.y()))
            self.viewport().update()
            event.accept()
            return
        if self.main_window.eraser_active:
            item = self.eraser_item or self.tool_target_graphic()
            if item and isinstance(item, QGraphicsPixmapItem):
                local = item.mapFromScene(self.mapToScene(event.position().toPoint()))
                self.eraser_cursor_local = local
                if self.eraser_item is item and event.buttons() & Qt.MouseButton.LeftButton:
                    if not self.eraser_points or (local - self.eraser_points[-1]).manhattanLength() >= 0.25:
                        self.eraser_points.append(local)
                        self._apply_eraser_preview_segment(self.eraser_preview_last or local, local)
                        self.eraser_preview_last = local
                self.viewport().update()
            event.accept()
            return
        if self.mode in ("resize", "rotate", "shape") and self.drag_item:
            item = self.drag_item
            old = self.old_layer.layer(item.data(0))
            mouse = self.mapToScene(event.position().toPoint())
            if self.mode == "shape" and isinstance(item, CurvedTextGraphicItem):
                # Live deformation; the model is only updated on release.
                item.drag_shape_handle(self.handle_index, item.mapFromScene(mouse))
                self.main_window.show_text_shape(item.path_shape, item.curve_intensity)
            elif self.mode == "resize":
                d = mouse - self.fixed_world
                r = radians(old.rotation)
                dx = cos(r)*d.x() + sin(r)*d.y()
                dy = -sin(r)*d.x() + cos(r)*d.y()
                local_dx = self.corner_local.x() - self.fixed_local.x()
                local_dy = self.corner_local.y() - self.fixed_local.y()
                sx = max(0.05, min(50, dx / local_dx))
                sy = max(0.05, min(50, dy / local_dy))
                item.setTransform(QTransform.fromScale(sx, sy))
                off_x = cos(r)*sx*self.fixed_local.x() - sin(r)*sy*self.fixed_local.y()
                off_y = sin(r)*sx*self.fixed_local.x() + cos(r)*sy*self.fixed_local.y()
                item.setPos(self.fixed_world - QPointF(off_x, off_y))
            else:
                heading = degrees(atan2(mouse.y()-self.fixed_center.y(), mouse.x()-self.fixed_center.x()))
                angle = heading - self.angle_offset
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    angle = round(angle / 15) * 15
                item.setRotation(angle)
                shift = self.fixed_center - item.mapToScene(item.boundingRect().center())
                item.setPos(item.pos() + shift)
            self.viewport().update()
            event.accept()
            return
        super().mouseMoveEvent(event)
        if self.mode == "move" and self.drag_item is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._after_move_step(event.modifiers(), self.mapToScene(event.position().toPoint()))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_last is not None:
            self._pan_last = None
            self.unsetCursor()
            event.accept()
            return
        if (event.button() == Qt.MouseButton.LeftButton and self.main_window.eraser_active
                and self.eraser_item and self.eraser_points):
            layer_id = self.eraser_item.data(0)
            points = self.eraser_points
            last = points[-1]
            # L'aperçu est retiré avant validation : si le trait est refusé,
            # le calque ne garde pas un effacement absent du document.
            self.cancel_eraser_preview()
            self.main_window.commit_eraser_stroke(layer_id, points)
            self.main_window.last_eraser_point = (last.x(), last.y())
            self.main_window.last_eraser_layer_id = layer_id
            self.viewport().update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.shape_drag is not None:
            drag, self.shape_drag = self.shape_drag, None
            self.main_window.create_shape(drag["start"], self.mapToScene(event.position().toPoint()),
                                          event.modifiers())
            self.viewport().update()
            event.accept()
            return
        if (event.button() == Qt.MouseButton.LeftButton and self.lasso_points is not None
                and self.main_window.selection_tool == "lasso"):
            self.finish_lasso()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.selection_drag is not None:
            drag, rect = self.selection_drag, self._drag_rect()
            self.selection_drag = None
            self.main_window.apply_selection_shape(drag["tool"], rect, drag["modifiers"])
            self.viewport().update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.lift is not None:
            delta, self.lift = self.lift["delta"], None
            self.main_window.move_selection_content(int(delta.x()), int(delta.y()))
            self.viewport().update()
            event.accept()
            return
        mode, item, before = self.mode, self.drag_item, self.old_layer
        if mode == "shape" and item and before and isinstance(item, CurvedTextGraphicItem):
            self.main_window.commit_text_shape(before, item.data(0), item.path_shape,
                                          item.curve_intensity, item.controls)
            self.mode = self.drag_item = self.old_layer = None
            self.viewport().update()
            event.accept()
            return
        if mode not in ("resize", "rotate"):
            super().mouseReleaseEvent(event)
        moved_group = self._finish_move()
        if item and before and mode == "move" and moved_group:
            positions = {graphic.data(0): (graphic.pos().x(), graphic.pos().y()) for graphic in moved_group}
            self.main_window.commit_canvas_moves(before, positions)
        elif item and before and mode:
            src = before.layer(item.data(0))
            if src:
                sx = item.transform().m11()
                sy = item.transform().m22()
                state = (item.pos().x(), item.pos().y(), sx, sy, item.rotation())
                old_state = (src.x, src.y, src.sx, src.sy, src.rotation)
                if any(abs(a-b) > 0.001 for a,b in zip(state, old_state)):
                    self.main_window.commit_canvas_transform(before, src.id, state,
                                                        "Déplacer" if mode == "move" else "Redimensionner" if mode == "resize" else "Faire pivoter")
        self.mode = self.drag_item = self.old_layer = None
        self.viewport().update()
        event.accept()

    def leaveEvent(self, event):
        if not self.eraser_item:
            self.eraser_cursor_local = None
            self.viewport().update()
        super().leaveEvent(event)

    def begin_eraser_preview(self, item: QGraphicsPixmapItem, layer: Layer) -> bool:
        """Prepare the live preview of a stroke on ``item``; False if the layer cannot be read."""
        try:
            base = render_layer_with_mask(layer, self.main_window.document)
        except Exception as exc:
            self.main_window.statusBar().showMessage(f"Gomme impossible : {exc}", 4000)
            return False
        self.eraser_item = item
        self.eraser_original_pixmap = item.pixmap()
        self.eraser_base = base
        self.eraser_coverage = Image.new("L", base.size, 0)
        self.eraser_settings = self.main_window.eraser_stroke_settings()
        self.eraser_flips = (layer.flip_horizontal, layer.flip_vertical)
        # A private copy (the item's pixmap is shared with the pixmap cache), created
        # transparent first: a pixmap made from an opaque image may have no alpha channel.
        original = item.pixmap()
        self.eraser_pixmap = QPixmap(original.size())
        self.eraser_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.eraser_pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawPixmap(0, 0, original)
        painter.end()
        return True

    def eraser_source_point(self, point: QPointF) -> list[float]:
        """Source coordinates of a point of the current stroke (see eraser_source_position)."""
        assert self.eraser_base is not None and self.eraser_settings is not None
        size = self.eraser_settings["size"]
        return [eraser_source_position(point.x(), self.eraser_base.width, size, self.eraser_flips[0]),
                eraser_source_position(point.y(), self.eraser_base.height, size, self.eraser_flips[1])]

    def _apply_eraser_preview_segment(self, start: QPointF, end: QPointF) -> None:
        """Show the segment as the final render will draw it, recomputing only the touched area."""
        if (self.eraser_item is None or self.eraser_base is None or self.eraser_coverage is None
                or self.eraser_settings is None or self.eraser_pixmap is None):
            return
        points = [self.eraser_source_point(start), self.eraser_source_point(end)]
        box = stamp_eraser_stroke(self.eraser_coverage, self.eraser_settings, points)
        if box is None:
            return
        region = self.eraser_base.crop(box)
        region.putalpha(ImageChops.multiply(region.getchannel("A"),
                                            ImageChops.invert(self.eraser_coverage.crop(box))))
        left, top = box[0], box[1]
        flip_horizontal, flip_vertical = self.eraser_flips
        if flip_horizontal:
            region = region.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            left = self.eraser_base.width - box[2]
        if flip_vertical:
            region = region.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            top = self.eraser_base.height - box[3]
        # The item shares the pixmap: release it first, so painting does not copy the whole image.
        self.eraser_item.setPixmap(QPixmap())
        painter = QPainter(self.eraser_pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawImage(left, top, pil_to_qimage(region))
        painter.end()
        self.eraser_item.setPixmap(self.eraser_pixmap)

    def _reset_eraser_preview(self) -> None:
        self.eraser_item = None
        self.eraser_points = []
        self.eraser_base = None
        self.eraser_coverage = None
        self.eraser_settings = None
        self.eraser_pixmap = None
        self.eraser_original_pixmap = None
        self.eraser_preview_last = None

    def cancel_eraser_preview(self) -> None:
        if self.eraser_item is not None and self.eraser_original_pixmap is not None:
            try:
                self.eraser_item.setPixmap(self.eraser_original_pixmap)
            except RuntimeError:
                pass
        self._reset_eraser_preview()

    def reset_interaction(self) -> None:
        """Forget a mouse interaction in progress: the items it refers to are being deleted.

        Called when the scene is replaced (undo or redo while a button is held,
        for instance). Selection drags and lassos are kept: they only use
        document coordinates.
        """
        self.mode = self.drag_item = self.old_layer = self.handle_index = None
        self.move_start, self.active_guides = {}, []
        # The lifted pixels come from the previous document.
        self.lift = None
        self._reset_eraser_preview()

    def cancel_selection_drag(self) -> None:
        self.selection_drag = None
        self.lasso_points, self.lasso_hover = None, None
        self.lift = None
        self.viewport().update()

    def zoom_by(self, factor: float) -> None:
        """Zoom borné : le pas est raccourci au lieu d'être refusé près des limites."""
        current = self.transform().m11()
        target = max(MIN_ZOOM, min(MAX_ZOOM, current * factor))
        if abs(target - current) > 1e-9:
            self.scale(target / current, target / current)
        self.main_window.update_zoom()

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120  # one notch of a classic wheel
        if not steps:
            super().wheelEvent(event)  # tilted wheel or Shift+wheel: horizontal scrolling
            return
        # Touchpads and fine wheels send small steps: zoom in proportion.
        self.zoom_by(1.15 ** steps)
        event.accept()

    def fit_document(self):
        if self.scene():
            region = QRectF(0, 0, self.main_window.document.width, self.main_window.document.height)
            self.fitInView(region, Qt.AspectRatioMode.KeepAspectRatio)
            current = self.transform().m11()
            clamped = max(MIN_ZOOM, min(MAX_ZOOM, current))
            if clamped != current:
                self.scale(clamped / current, clamped / current)
                self.centerOn(region.center())
            self.main_window.update_zoom()
