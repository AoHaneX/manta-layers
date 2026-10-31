"""Tests d'intégration Qt, à exécuter après installation des dépendances."""
import io
import math
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # PySide6 absent : seuls les tests sans interface s'exécutent.
    QApplication = None
else:
    # Une erreur d'import dans l'application doit faire échouer la suite,
    # pas la faire passer pour « ignorée ».
    from PySide6.QtCore import QMimeData, QPointF, QSettings, Qt, QUrl
    from PySide6.QtGui import QFont, QFontMetricsF, QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QToolButton

    from app import graphics
    from app.graphics import MAX_ZOOM, CurvedTextGraphicItem, render_document
    from app.model import Document, Layer
    from app.window import MainWindow


def png_bytes(width, height, color):
    output = io.BytesIO()
    Image.new("RGBA", (width, height), color).save(output, format="PNG")
    return output.getvalue()


@unittest.skipIf(QApplication is None, 'PySide6 non disponible sur la machine de test')
class GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.settings_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.settings_dir, ignore_errors=True)

    def make_window(self):
        # Réglages isolés : les tests ne touchent pas aux préférences de l'utilisateur.
        settings = QSettings(str(Path(self.settings_dir) / "settings.ini"), QSettings.Format.IniFormat)
        win = MainWindow(settings=settings, recovery_dir=Path(self.settings_dir) / "recovery")
        self.addCleanup(self.close_window, win)
        return win

    @staticmethod
    def close_window(win):
        win.undo_stack.setClean()
        win.close()

    def test_demo_canvas_and_export_render(self):
        win = self.make_window()
        self.assertGreater(len(win.document.layers), 0)
        self.assertGreater(win.layer_list.count(), 0)
        result = render_document(win.document)
        self.assertEqual(result.width(), 1280)
        self.assertEqual(result.height(), 720)

    def test_undo_redo_changes_position(self):
        win = self.make_window()
        layer_id = win.document.layers[0].id
        old = win.document.layer(layer_id).x
        win.mutate('Test move',lambda doc: setattr(doc.layer(layer_id),'x',old+42),layer_id)
        self.assertAlmostEqual(win.document.layer(layer_id).x,old+42)
        win.undo_stack.undo()
        self.assertAlmostEqual(win.document.layer(layer_id).x,old)
        win.undo_stack.redo()
        self.assertAlmostEqual(win.document.layer(layer_id).x,old+42)

    def test_delete_key_removes_selected_layer_and_can_be_undone(self):
        win = self.make_window()
        layer_id = win.document.layers[-1].id
        win.select_layer(layer_id)
        count = len(win.document.layers)
        QTest.keyClick(win.canvas, Qt.Key.Key_Delete)
        self.assertEqual(len(win.document.layers), count - 1)
        self.assertIsNone(win.document.layer(layer_id))
        win.undo_stack.undo()
        self.assertIsNotNone(win.document.layer(layer_id))

    def test_lock_prevents_transform_and_delete(self):
        win = self.make_window()
        layer_id = win.document.layers[-1].id
        win.select_layer(layer_id)
        win.toggle_lock(layer_id)
        layer = win.document.layer(layer_id)
        self.assertTrue(layer.locked)
        graphic = next(item for item in win.canvas_scene.items() if item.data(0) == layer_id)
        self.assertFalse(bool(graphic.flags() & graphic.GraphicsItemFlag.ItemIsMovable))
        self.assertFalse(win.name_input.isEnabled())
        count = len(win.document.layers)
        win.delete_layer()
        self.assertEqual(len(win.document.layers), count)
        win.toggle_lock(layer_id)
        self.assertFalse(win.document.layer(layer_id).locked)

    def test_layer_and_history_tabs_are_available(self):
        win = self.make_window()
        self.assertEqual([win.tabs.tabText(i) for i in range(win.tabs.count())],
                         ["Calques", "Historique", "Outils"])
        controls = win.layer_list.itemWidget(win.layer_list.item(0))
        self.assertIsNotNone(controls)
        self.assertEqual(len(controls.findChildren(QToolButton)), 5)

    def test_last_selected_font_is_persistent(self):
        family = QApplication.font().family()
        win = self.make_window()
        win.on_font_changed(QFont(family))
        win.settings.sync()
        reopened = self.make_window()
        self.assertEqual(reopened.last_font_family, family)

    def test_eraser_stroke_is_one_undoable_operation(self):
        win = self.make_window()
        layer = next(layer for layer in win.document.layers if layer.kind == "image")
        win.select_layer(layer.id)
        before_index = win.undo_stack.index()
        win.commit_eraser_stroke(layer.id, [QPointF(2, 2), QPointF(9, 2)])
        self.assertEqual(win.undo_stack.index(), before_index + 1)
        self.assertEqual(len(win.document.layer(layer.id).eraser_strokes), 1)
        win.undo_stack.undo()
        self.assertEqual(len(win.document.layer(layer.id).eraser_strokes), 0)
        win.undo_stack.redo()
        self.assertEqual(len(win.document.layer(layer.id).eraser_strokes), 1)

    def test_image_pixel_mapping_remains_precise_after_zoom(self):
        win = self.make_window()
        layer = next(layer for layer in win.document.layers if layer.kind == "image")
        win.select_layer(layer.id)
        item = win.selected_image_item()
        expected = QPointF(4, 4)
        win.canvas.resetTransform()
        win.canvas.scale(8, 8)
        viewport_point = win.canvas.mapFromScene(item.mapToScene(expected))
        recovered = item.mapFromScene(win.canvas.mapToScene(viewport_point))
        self.assertLess(abs(recovered.x() - expected.x()), 0.2)
        self.assertLess(abs(recovered.y() - expected.y()), 0.2)

    def test_eraser_preview_updates_alpha_in_real_time(self):
        win = self.make_window()
        layer = next(layer for layer in win.document.layers if layer.kind == "image")
        win.select_layer(layer.id)
        item = win.selected_image_item()
        preview = QImage(12, 12, QImage.Format.Format_ARGB32)
        preview.fill(0xFFFFFFFF)
        win.canvas.eraser_item = item
        win.canvas.eraser_preview_image = preview
        win.eraser_size_preset.setCurrentIndex(2)  # 4 × 4 px
        win.canvas._apply_eraser_preview_segment(QPointF(6, 6), QPointF(6, 6))
        self.assertEqual(win.canvas.eraser_preview_image.pixelColor(6, 6).alpha(), 0)
        win.canvas.cancel_eraser_preview()

    def test_eraser_preview_applies_opacity_once_per_stroke(self):
        win = self.make_window()
        layer = next(layer for layer in win.document.layers if layer.kind == "image")
        win.select_layer(layer.id)
        preview = QImage(40, 40, QImage.Format.Format_ARGB32)
        preview.fill(0xFF000000)
        win.canvas.eraser_item = win.selected_image_item()
        win.canvas.eraser_preview_image = preview
        win.eraser_opacity.setValue(25)
        win.canvas._apply_eraser_preview_segment(QPointF(5, 20), QPointF(35, 20))
        self.assertAlmostEqual(win.canvas.eraser_preview_image.pixelColor(20, 20).alpha(), 191, delta=2)
        win.canvas.cancel_eraser_preview()

    def test_tool_options_are_separated(self):
        win = self.make_window()
        win.toggle_paint_mode("contiguous", True)
        self.assertFalse(win.paint_settings.isHidden())
        self.assertTrue(win.eraser_settings.isHidden())
        win.set_eraser_active(True)
        self.assertTrue(win.paint_settings.isHidden())
        self.assertFalse(win.eraser_settings.isHidden())
        self.assertTrue(win.color_editor.isHidden())

    def test_curved_text_stays_editable_and_uses_export_renderer(self):
        win = self.make_window()
        holder = {}
        def add_curved(doc):
            layer = doc.add_text("Été sur l’océan")
            layer.text_deformation = "arc_up"
            layer.curve_intensity = 65
            layer.character_spacing = 3
            holder["id"] = layer.id
        win.mutate("Texte courbé de test", add_curved)
        win.select_layer(holder["id"])
        self.assertIsInstance(win.canvas.selected_graphic(), CurvedTextGraphicItem)
        self.assertEqual(win.document.layer(holder["id"]).text, "Été sur l’océan")
        self.assertFalse(render_document(win.document).isNull())

    def test_curve_handle_commit_is_one_undoable_operation(self):
        win = self.make_window()
        layer = win.document.add_text("Vague")
        layer.text_deformation = "wave"
        win.install_document(win.document, layer.id)
        before = win.document.clone()
        start_index = win.undo_stack.index()
        win.commit_text_shape(before, layer.id, "custom", 82.5, layer.path_controls)
        self.assertEqual(win.undo_stack.index(), start_index + 1)
        self.assertEqual(win.document.layer(layer.id).curve_intensity, 82.5)
        win.undo_stack.undo()
        self.assertEqual(win.document.layer(layer.id).curve_intensity, 0.0)

    def test_curve_slider_change_without_mouse_is_committed(self):
        win = self.make_window()
        holder = {}
        win.mutate("Texte", lambda doc: holder.update(id=doc.add_text("Courbe").id))
        win.select_layer(holder["id"])
        start = win.undo_stack.count()
        win.curve_intensity.setValue(40)  # clavier, molette ou clic sur la rainure
        QTest.qWait(500)
        self.assertEqual(win.document.layer(holder["id"]).curve_intensity, 40.0)
        self.assertEqual(win.undo_stack.count(), start + 1)

    def test_canvas_accepts_local_image_drops(self):
        win = self.make_window()
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(r"C:\images\rapide.PNG"),
                      QUrl.fromLocalFile(r"C:\images\notes.txt")])
        self.assertTrue(win.acceptDrops())
        self.assertTrue(win.canvas.acceptDrops())
        paths = win.image_paths_from_mime(mime)
        self.assertEqual(len(paths), 1)
        self.assertEqual(Path(paths[0]).name, "rapide.PNG")
        self.assertFalse(win.windowIcon().isNull())

    def test_failed_render_leaves_interface_usable(self):
        win = self.make_window()
        layers_before = [layer.id for layer in win.document.layers]
        commands_before = win.undo_stack.count()

        def add_unreadable(doc):
            asset = "f" * 32
            doc.assets[asset] = b"pas une image"
            doc.layers.append(Layer(name="Cassée", kind="image", asset=asset))

        with mock.patch.object(win, "_report_failure") as report:
            self.assertFalse(win.mutate("Image cassée", add_unreadable))
        report.assert_called_once()
        self.assertFalse(win.refreshing)
        self.assertEqual(win.undo_stack.count(), commands_before)
        self.assertEqual([layer.id for layer in win.document.layers], layers_before)
        win.select_layer(layers_before[0])
        self.assertEqual(win.selected_id, layers_before[0])

    def test_zoom_is_never_stuck_outside_limits(self):
        win = self.make_window()
        win.install_document(Document(32, 32), None)
        for start in (30.0, 0.03):
            win.canvas.resetTransform()
            win.canvas.scale(start, start)
            win.change_zoom(1.2)
            zoomed_in = win.canvas.transform().m11()
            win.change_zoom(1 / 1.2)
            win.change_zoom(1 / 1.2)
            self.assertGreater(zoomed_in, start)
            self.assertLess(win.canvas.transform().m11(), zoomed_in)
        win.canvas.resetTransform()
        win.canvas.scale(MAX_ZOOM, MAX_ZOOM)
        win.change_zoom(1.2)
        self.assertAlmostEqual(win.canvas.transform().m11(), MAX_ZOOM)

    def test_pipette_then_bucket_fills_selected_layer(self):
        win = self.make_window()
        document = Document(100, 100)
        red = document.add_image_bytes(png_bytes(40, 40, (200, 10, 10, 255)), "Rouge")
        blue = document.add_image_bytes(png_bytes(10, 10, (10, 10, 200, 255)), "Bleu")
        win.install_document(document, red.id)
        blue_item = win.canvas.graphic_for(blue.id)
        win.activate_picker("tools", True)
        self.assertTrue(win.sample_canvas_color(blue_item, blue_item.mapToScene(QPointF(2, 2))))
        self.assertEqual(win.selected_id, red.id)
        win.toggle_paint_mode("contiguous", True)
        red_item = win.canvas.graphic_for(red.id)
        self.assertTrue(win.paint_canvas_color(red_item.mapToScene(QPointF(1, 1))))
        fills = win.document.layer(red.id).color_fills
        self.assertEqual(len(fills), 1)
        self.assertEqual((fills[0]["source"], fills[0]["target"]), ("#C80A0A", "#0A0AC8"))

    def test_tools_keep_last_selected_layer(self):
        win = self.make_window()
        layer = next(layer for layer in win.document.layers if layer.kind == "image")
        win.select_layer(layer.id)
        win.select_layer(None)  # clic dans le vide
        self.assertEqual(win.tool_target_id(), layer.id)
        win.set_eraser_active(True)
        self.assertEqual(win.selected_id, layer.id)
        win.tabs.setCurrentIndex(0)
        self.assertEqual(win.selected_id, layer.id)

    def test_property_edit_does_not_round_other_fields(self):
        win = self.make_window()
        layer = next(layer for layer in win.document.layers if layer.kind == "image")
        win.mutate("Échelle", lambda doc: setattr(doc.layer(layer.id), "sx", 0.333), layer.id)
        win.select_layer(layer.id)
        count = win.undo_stack.count()
        win.commit_property("sx")  # quitter le champ sans le modifier
        self.assertEqual(win.undo_stack.count(), count)
        win.name_input.setText("Nouveau nom")
        win.commit_property("name")
        edited = win.document.layer(layer.id)
        self.assertEqual(edited.name, "Nouveau nom")
        self.assertEqual(edited.sx, 0.333)

    def test_leaving_a_field_showing_a_clamped_value_changes_nothing(self):
        win = self.make_window()
        layer = next(layer for layer in win.document.layers if layer.kind == "image")
        far = win.inputs["x"].maximum() + 500
        win.mutate("Loin", lambda doc: setattr(doc.layer(layer.id), "x", far), layer.id)
        win.select_layer(layer.id)
        count = win.undo_stack.count()
        win.commit_property("x")  # the field shows its maximum, not the real position
        self.assertEqual(win.undo_stack.count(), count)
        self.assertEqual(win.document.layer(layer.id).x, far)
    def test_locked_layer_cannot_be_reordered_by_drag(self):
        win = self.make_window()
        document = Document(100, 100)
        first = document.add_text("Premier")
        document.add_text("Second")
        first.locked = True
        win.install_document(document, None)
        order = [layer.id for layer in win.document.layers]
        win.move_layer_to_display_position(first.id, 0)
        self.assertEqual([layer.id for layer in win.document.layers], order)

    def test_multiline_text_keeps_lines_and_tight_bounds(self):
        single = CurvedTextGraphicItem(Layer(kind="text", text="Manta", font_size=56))
        double = CurvedTextGraphicItem(Layer(kind="text", text="Manta\nLayers", font_size=56))
        metrics = QFontMetricsF(single.font)
        self.assertLess(single.boundingRect().height(), metrics.height() * 1.3)
        baselines = {round(point.y()) for _char, _advance, point, _angle in double.placements}
        self.assertEqual(len(baselines), 2)
        self.assertGreater(double.boundingRect().height(), single.boundingRect().height())

    def test_rotation_handle_stays_at_constant_screen_distance(self):
        win = self.make_window()
        layer = next(layer for layer in win.document.layers if layer.kind == "image")
        win.select_layer(layer.id)
        item = win.selected_image_item()
        for scale in (0.1, 5.0):
            item.setTransform(item.transform().fromScale(scale, scale))
            bounds = item.boundingRect()
            top = win.canvas.mapFromScene(item.mapToScene(QPointF(bounds.center().x(), bounds.top())))
            delta = win.canvas.mapFromScene(win.canvas.rotation_point(item)) - top
            self.assertAlmostEqual(math.hypot(delta.x(), delta.y()), 35, delta=2)

    def test_unchanged_layers_reuse_cached_render(self):
        win = self.make_window()
        layer = next(layer for layer in win.document.layers if layer.kind == "image")
        with mock.patch.object(graphics, "render_layer_image",
                               wraps=graphics.render_layer_image) as render:
            win.set_layer_visibility(layer.id, not layer.visible)
        render.assert_not_called()


if __name__ == '__main__':
    unittest.main()
