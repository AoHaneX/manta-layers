"""Tests d'intégration Qt, à exécuter après installation des dépendances."""
import os
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QToolButton
    from app.window import MainWindow
    from app.graphics import CurvedTextGraphicItem, render_document
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, 'PySide6 non disponible sur la machine de test')
class GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_demo_canvas_and_export_render(self):
        win = MainWindow()
        self.assertGreater(len(win.document.layers), 0)
        self.assertGreater(win.layer_list.count(), 0)
        result = render_document(win.document)
        self.assertEqual(result.width(), 1280)
        self.assertEqual(result.height(), 720)
        win.undo_stack.setClean()
        win.close()

    def test_undo_redo_changes_position(self):
        win = MainWindow()
        layer_id = win.document.layers[0].id
        old = win.document.layer(layer_id).x
        win.mutate('Test move',lambda doc: setattr(doc.layer(layer_id),'x',old+42),layer_id)
        self.assertAlmostEqual(win.document.layer(layer_id).x,old+42)
        win.undo_stack.undo()
        self.assertAlmostEqual(win.document.layer(layer_id).x,old)
        win.undo_stack.redo()
        self.assertAlmostEqual(win.document.layer(layer_id).x,old+42)
        win.undo_stack.setClean()
        win.close()

    def test_delete_key_removes_selected_layer_and_can_be_undone(self):
        win = MainWindow()
        layer_id = win.document.layers[-1].id
        win.select_layer(layer_id)
        count = len(win.document.layers)
        QTest.keyClick(win.canvas, Qt.Key.Key_Delete)
        self.assertEqual(len(win.document.layers), count - 1)
        self.assertIsNone(win.document.layer(layer_id))
        win.undo_stack.undo()
        self.assertIsNotNone(win.document.layer(layer_id))
        win.undo_stack.setClean()
        win.close()

    def test_lock_prevents_transform_and_delete(self):
        win = MainWindow()
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
        win.undo_stack.setClean()
        win.close()

    def test_layer_and_history_tabs_are_available(self):
        win = MainWindow()
        self.assertEqual([win.tabs.tabText(i) for i in range(win.tabs.count())],
                         ["Calques", "Historique", "Outils"])
        controls = win.layer_list.itemWidget(win.layer_list.item(0))
        self.assertIsNotNone(controls)
        self.assertEqual(len(controls.findChildren(QToolButton)), 5)
        win.undo_stack.setClean()
        win.close()

    def test_eraser_stroke_is_one_undoable_operation(self):
        win = MainWindow()
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
        win.undo_stack.setClean()
        win.close()

    def test_image_pixel_mapping_remains_precise_after_zoom(self):
        win = MainWindow()
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
        win.undo_stack.setClean()
        win.close()

    def test_eraser_preview_updates_alpha_in_real_time(self):
        win = MainWindow()
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
        win.undo_stack.setClean()
        win.close()

    def test_tool_options_are_separated(self):
        win = MainWindow()
        win.toggle_paint_mode("contiguous", True)
        self.assertFalse(win.paint_settings.isHidden())
        self.assertTrue(win.eraser_settings.isHidden())
        win.set_eraser_active(True)
        self.assertTrue(win.paint_settings.isHidden())
        self.assertFalse(win.eraser_settings.isHidden())
        self.assertTrue(win.color_editor.isHidden())
        win.undo_stack.setClean()
        win.close()

    def test_curved_text_stays_editable_and_uses_export_renderer(self):
        win = MainWindow()
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
        win.undo_stack.setClean()
        win.close()

    def test_curve_handle_commit_is_one_undoable_operation(self):
        win = MainWindow()
        layer = win.document.add_text("Vague")
        layer.text_deformation = "wave"
        win.install_document(win.document, layer.id)
        before = win.document.clone()
        start_index = win.undo_stack.index()
        win.commit_curve_handle(before, layer.id, 82.5)
        self.assertEqual(win.undo_stack.index(), start_index + 1)
        self.assertEqual(win.document.layer(layer.id).curve_intensity, 82.5)
        win.undo_stack.undo()
        self.assertEqual(win.document.layer(layer.id).curve_intensity, 0.0)
        win.undo_stack.setClean()
        win.close()

    def test_canvas_accepts_local_image_drops(self):
        win = MainWindow()
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(r"C:\images\rapide.PNG"),
                      QUrl.fromLocalFile(r"C:\images\notes.txt")])
        self.assertTrue(win.acceptDrops())
        self.assertTrue(win.canvas.acceptDrops())
        paths = win.image_paths_from_mime(mime)
        self.assertEqual(len(paths), 1)
        self.assertEqual(Path(paths[0]).name, "rapide.PNG")
        self.assertFalse(win.windowIcon().isNull())
        win.undo_stack.setClean()
        win.close()


if __name__ == '__main__':
    unittest.main()
