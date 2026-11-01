"""Fenêtre principale de Manta Layers, éditeur simple à calques pour Windows."""
from __future__ import annotations

import time
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from shutil import copy2

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, QSettings, QSize, QStandardPaths, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QImage,
    QKeySequence,
    QPixmap,
    QShortcut,
    QUndoCommand,
    QUndoStack,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QGraphicsPixmapItem,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QToolButton,
    QUndoView,
    QVBoxLayout,
    QWidget,
)

from . import __version__, background, background_dialog, export, selection
from .background_dialog import BackgroundRemovalDialog
from .dialogs import NewProjectDialog, ResizeDocumentDialog
from .graphics import (
    CanvasView,
    CurvedTextGraphicItem,
    crop_image_layer,
    document_mask_to_layer,
    font_is_installed,
    forget_font_families,
    layers_bounds,
    make_scene,
    merge_changes_appearance,
    pil_to_qimage,
    qimage_png,
    qimage_to_pil,
    render_document,
    render_layer_image,
    render_layer_with_mask,
    render_layers,
    render_layers_region,
    resolve_font_family,
)
from .icons import alignment_icon, color_tool_icon, history_arrow_icon, sidebar_arrow_icon
from .imaging import alpha_bounds
from .layer_panel import FOLDER_ROLE, build_folder_row, build_layer_row, set_row_checked
from .model import ASSET_FORMATS, MAX_DIMENSION, MAX_DOCUMENT_PIXELS, Document, Layer, new_id
from .paths import safe_file_stem, user_data_directory
from .recovery import SessionRecovery, recovery_text
from .screen_picker import ScreenColorPicker
from .selection import COMBINE_LABELS, COMBINE_MODES
from .shape_item import shape_from_drag
from .shape_panel import ShapePropertyRows
from .sprite_dialog import SpriteSheetDialog
from .storage import open_project, save_project
from .template_library import TemplateLibraryDialog
from .templates import extract_elements, insert_elements, list_templates, save_template
from .textpath import DEFAULT_CONTROLS, SHAPE_LABELS, TEXT_SHAPES, normalize_controls
from .theme import COLORS, STYLE, dialog_button_style
from .token_dialog import TokenDialog
from .widgets import CommitPlainTextEdit, InlineTextEditor, LayerListWidget, SidebarBackground

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
FONT_SUFFIXES = {".ttf", ".otf", ".ttc"}
# Polices livrées avec l'application (lecture seule) puis polices importées
# par l'utilisateur, rangées dans son dossier de données.
BUNDLED_FONTS_DIR = ROOT / "fonts"
USER_FONTS_DIR = user_data_directory() / "fonts"
RECOVERY_INTERVAL_MS = 60_000
NUDGE_MERGE_SECONDS = 1.0
PROPERTY_LABELS = {
    "name": "Renommer le calque",
    "x": "Position X", "y": "Position Y",
    "sx": "Échelle X", "sy": "Échelle Y",
    "rotation": "Rotation",
    "opacity": "Opacité",
    "text": "Contenu du texte",
    "font_family": "Police du texte",
    "font_size": "Taille du texte",
    "curve_intensity": "Courbure du texte",
    "character_spacing": "Espacement des caractères",
    "path_alignment": "Alignement du texte",
    "text_deformation": "Forme du texte",
    "path_orientation": "Orientation des lettres",
}


class DocumentCommand(QUndoCommand):
    def __init__(self, win: "MainWindow", before: Document, after: Document,
                 description: str, selected_before: str | None, selected_after: str | None,
                 merge_key=None):
        super().__init__(description)
        self.win = win
        self.before = before
        self.after = after
        self.selected_before = selected_before
        self.selected_after = selected_after
        # Commands sharing a merge key and close in time collapse into one step.
        self.merge_key = merge_key
        self.timestamp = time.monotonic()

    def id(self):
        return 1 if self.merge_key is not None else -1

    def mergeWith(self, other):
        if (not isinstance(other, DocumentCommand) or other.merge_key != self.merge_key
                or other.timestamp - self.timestamp > NUDGE_MERGE_SECONDS):
            return False
        self.after = other.after
        self.selected_after = other.selected_after
        self.timestamp = other.timestamp
        return True

    def _apply(self, document: Document, selected: str | None):
        try:
            self.win.install_document(document.clone(), selected)
        except Exception as exc:
            self.win.command_failed(self, exc)

    def undo(self):
        self._apply(self.before, self.selected_before)

    def redo(self):
        self._apply(self.after, self.selected_after)


class SelectionCommand(QUndoCommand):
    """Undoable selection change; masks are kept PNG-compressed."""

    def __init__(self, win: "MainWindow", before: bytes | None, after: bytes | None, description: str):
        super().__init__(description)
        self.win = win
        self.before = before
        self.after = after

    def undo(self):
        self.win._install_selection(self.before)

    def redo(self):
        self.win._install_selection(self.after)


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None, recovery_dir: Path | None = None):
        super().__init__()
        # Crash-recovery copies; tests pass a temporary folder.
        self.recovery_dir = Path(recovery_dir) if recovery_dir is not None else user_data_directory() / "recovery"
        self.document = Document()
        self.project_path: Path | None = None
        # Element template opened for editing ({"path", "name"}): saving writes it back.
        self.editing_template: dict | None = None
        # Template the document comes from (its key), for the remembered folders.
        self.template_origin: str | None = None
        self.selected_id: str | None = None
        # Dernier calque choisi : les outils continuent de le viser même si la
        # sélection est vidée, par exemple après un clic dans le vide.
        self.last_selected_id: str | None = None
        self.refreshing = False
        self.picker_active = False
        self.picker_target = "tools"
        self.picker_text_layer_id: str | None = None
        self.paint_mode: str | None = None
        self.eraser_active = False
        self.text_tool_active = False
        self.selection_tool: str | None = None
        # Shape being drawn on the canvas: rectangle, ellipse, polygon, line or arrow.
        self.shape_tool: str | None = None
        self.shape_tool_buttons: dict[str, QToolButton] = {}
        self._screen_picker: ScreenColorPicker | None = None
        self.selection_tool_buttons: dict[str, QToolButton] = {}
        # Floating editor used to type a text directly on the canvas.
        self._inline: dict | None = None
        self.selection_mask = None
        # Multiple selection of the layer panel (layer ids), see set_layer_checked.
        self.checked_ids: set[str] = set()
        # Folded folders of the current document, kept across undo and redo.
        self._collapsed_folders: dict[str, bool] = {}
        self._layer_rows: dict[str, QWidget] = {}
        self.models_dir = background.models_directory()
        self._clipboard_origin = None
        self._setting_clipboard = False
        self.last_eraser_point: tuple[float, float] | None = None
        self.last_eraser_layer_id: str | None = None
        self.replacement_color = COLORS["primary"]
        self._updating_color_fields = False
        self._pushing_command: DocumentCommand | None = None
        self._push_error: Exception | None = None
        self.variation_colors: list[str] = []
        self.left_sidebar_expanded = True
        self.left_sidebar_width = 245
        self.settings = settings if settings is not None else QSettings("Blue Shrimp", "Manta Layers")
        self.last_font_family = str(self.settings.value("text/last_font", "Arial"))
        self.snap_enabled = self.settings.value("canvas/snap", True, type=bool)
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(100)
        self.custom_font_ids: list[int] = []
        self.load_custom_fonts()
        self.setWindowIcon(QIcon(str(ASSETS / "manta.png")))
        self.setAcceptDrops(True)
        self.setMinimumSize(960, 600)
        self.resize(1440, 870)
        self.setStyleSheet(STYLE)
        self._build_layout()
        self._build_actions()
        self._name_icon_buttons(self)
        self.undo_stack.indexChanged.connect(self.update_title)
        self.undo_stack.cleanChanged.connect(self.update_title)
        self._revision = 0
        self._load_demo()
        self._setup_recovery()

    def load_custom_fonts(self):
        """Charge les polices livrées avec l'application puis celles importées."""
        for directory in (BUNDLED_FONTS_DIR, USER_FONTS_DIR):
            try:
                paths = sorted(directory.iterdir()) if directory.is_dir() else []
            except OSError:
                continue
            for path in paths:
                if path.is_file() and path.suffix.lower() in FONT_SUFFIXES:
                    font_id = QFontDatabase.addApplicationFont(str(path))
                    if font_id >= 0:
                        self.custom_font_ids.append(font_id)
        forget_font_families()

    def import_fonts(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Importer des polices", "", "Polices (*.ttf *.otf *.ttc);;Tous les fichiers (*)"
        )
        if not paths:
            return
        imported = []
        for raw_path in paths:
            source = Path(raw_path)
            if source.suffix.lower() not in FONT_SUFFIXES:
                continue
            destination = USER_FONTS_DIR / source.name
            if destination.exists():
                answer = QMessageBox.question(
                    self, "Police déjà présente",
                    f"Remplacer la police {source.name} ?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    continue
            try:
                # La police est validée avant la copie : un fichier invalide
                # n'est jamais laissé dans le dossier des polices.
                font_id = QFontDatabase.addApplicationFontFromData(source.read_bytes())
                if font_id < 0:
                    raise ValueError("format de police non pris en charge")
                USER_FONTS_DIR.mkdir(parents=True, exist_ok=True)
                copy2(source, destination)
                self.custom_font_ids.append(font_id)
                imported.extend(QFontDatabase.applicationFontFamilies(font_id))
            except Exception as exc:
                QMessageBox.warning(self, "Import de police impossible", f"{source.name}\n{exc}")
        if imported:
            forget_font_families()
            self.statusBar().showMessage(
                "Police(s) ajoutée(s) : " + ", ".join(dict.fromkeys(imported)), 6000
            )

    def update_properties_panel_visibility(self, tab_index: int):
        visible = tab_index == 0
        self.properties_label.setVisible(visible)
        self.properties_panel.setVisible(visible)
        if hasattr(self, "tools_tab") and tab_index != self.tabs.indexOf(self.tools_tab):
            self.deactivate_active_tools()
        self._schedule_right_panel_layout()

    def _schedule_right_panel_layout(self):
        """Recalcule la hauteur naturelle du panneau sans bloquer l'interface."""
        if hasattr(self, "right_content") and hasattr(self, "property_form"):
            QTimer.singleShot(0, self._update_right_panel_layout)

    def _update_right_panel_layout(self):
        """Empêche les contrôles de se comprimer : le panneau externe défile à la place."""
        if not hasattr(self, "right_content"):
            return

        self.property_form.invalidate()
        self.property_form.activate()
        property_height = max(1, self.property_form.sizeHint().height() + 4)
        self.properties_panel.setFixedHeight(property_height)

        current_tab = self.tabs.currentWidget()
        if current_tab is not None and current_tab.layout() is not None:
            current_tab.layout().invalidate()
            current_tab.layout().activate()
        tab_content_height = current_tab.sizeHint().height() if current_tab is not None else 0
        tab_height = max(365, tab_content_height + self.tabs.tabBar().sizeHint().height() + 18)
        self.tabs.setFixedHeight(tab_height)

        self.right_content.layout().invalidate()
        self.right_content.layout().activate()
        self.right_content.adjustSize()
        self.right_content.updateGeometry()

    def _build_layout(self):
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.main_splitter = splitter
        self.setCentralWidget(splitter)

        left = SidebarBackground(ASSETS / "sidebar_ocean.png")
        self.left_panel = left
        left.setObjectName("sidePanel")
        left.setMinimumWidth(220)
        left.setMaximumWidth(285)
        left_outer = QVBoxLayout(left)
        left_outer.setContentsMargins(0, 0, 0, 0)
        # The panel scrolls instead of being cut on short screens
        # (1080p at 150 % or 768p leave less than 700 px of height).
        left_scroll = QScrollArea()
        left_scroll.setObjectName("leftPanelScroll")
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        left_outer.addWidget(left_scroll)
        left_content = QWidget()
        # Long button labels are elided by the panel width, as before, rather
        # than widening the content beyond the visible area.
        left_content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        left_layout = QVBoxLayout(left_content)
        self.left_layout = left_layout
        left_layout.setSpacing(9)
        self.left_collapsible_widgets = []
        self.left_toggle = QPushButton()
        self.left_toggle.setObjectName("sidebarToggle")
        self.left_toggle.setIcon(sidebar_arrow_icon(False))
        self.left_toggle.setIconSize(QSize(18, 18))
        self.left_toggle.setToolTip("Replier le panneau d'utilitaires")
        self.left_toggle.clicked.connect(self.toggle_left_sidebar)
        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setPixmap(QPixmap(str(ASSETS / "manta.png")).scaled(
            190, 124, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))
        left_layout.addWidget(logo)
        self.left_collapsible_widgets.append(logo)
        title = QLabel("MANTA LAYERS")
        title.setObjectName("brandTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(title)
        self.left_collapsible_widgets.append(title)
        subtitle = QLabel("Éditeur d'images à calques\nBlue Shrimp · ReefKit")
        subtitle.setObjectName("muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        left_layout.addWidget(subtitle)
        self.left_collapsible_widgets.append(subtitle)
        self.doc_info = QPushButton()
        self.doc_info.setObjectName("docInfo")
        self.doc_info.setToolTip("Modifier les dimensions finales du document")
        self.doc_info.clicked.connect(self.resize_document)
        left_layout.addWidget(self.doc_info)
        self.left_collapsible_widgets.append(self.doc_info)
        left_layout.addSpacing(17)
        tools_label = QLabel("UTILITAIRES")
        tools_label.setObjectName("sectionTitle")
        left_layout.addWidget(tools_label)
        self.left_collapsible_widgets.append(tools_label)
        self.utility_buttons = {}
        for key, text, method in [
            ("import", "+ Importer des images", self.add_images),
            ("add_text", "T  Ajouter du texte", self.add_text),
            ("duplicate", "⧉ Dupliquer le calque", self.duplicate_layer),
            ("flip_horizontal", "⇆ Retourner horizontalement", self.flip_layer_horizontal),
            ("flip_vertical", "⇅ Retourner verticalement", self.flip_layer_vertical),
            ("lock", "▣ Verrouiller le calque", self.toggle_lock),
            ("delete", "× Supprimer le calque", self.delete_layer),
            ("fit", "⤢ Cadrer le document", lambda: self.canvas.fit_document()),
        ]:
            btn = QPushButton(text)
            if text.startswith("+ Importer"):
                btn.setProperty("variant", "primary")
            elif text.startswith("× Supprimer"):
                btn.setProperty("variant", "danger")
            btn.clicked.connect(method)
            left_layout.addWidget(btn)
            self.utility_buttons[key] = btn
            self.left_collapsible_widgets.append(btn)
        self.update_utility_buttons()
        left_layout.addStretch(1)

        history_controls = QWidget()
        history_layout = QHBoxLayout(history_controls)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(7)
        self.left_undo_btn = QToolButton()
        self.left_undo_btn.setObjectName("leftHistoryButton")
        self.left_undo_btn.setIcon(history_arrow_icon(False))
        self.left_undo_btn.setIconSize(QSize(24, 24))
        self.left_undo_btn.setToolTip("Annuler · Ctrl+Z")
        self.left_undo_btn.setEnabled(self.undo_stack.canUndo())
        self.left_undo_btn.clicked.connect(self.undo_stack.undo)
        self.undo_stack.canUndoChanged.connect(self.left_undo_btn.setEnabled)
        self.left_redo_btn = QToolButton()
        self.left_redo_btn.setObjectName("leftHistoryButton")
        self.left_redo_btn.setIcon(history_arrow_icon(True))
        self.left_redo_btn.setIconSize(QSize(24, 24))
        self.left_redo_btn.setToolTip("Rétablir · Ctrl+Y")
        self.left_redo_btn.setEnabled(self.undo_stack.canRedo())
        self.left_redo_btn.clicked.connect(self.undo_stack.redo)
        self.undo_stack.canRedoChanged.connect(self.left_redo_btn.setEnabled)
        history_layout.addWidget(self.left_undo_btn)
        history_layout.addWidget(self.left_redo_btn)
        left_layout.addWidget(history_controls)
        self.left_collapsible_widgets.append(history_controls)

        new_project_btn = QPushButton("Nouveau projet")
        new_project_btn.clicked.connect(self.new_document)
        left_layout.addWidget(new_project_btn)
        self.left_collapsible_widgets.append(new_project_btn)
        save_project_btn = QPushButton("Sauvegarder le projet")
        save_project_btn.clicked.connect(self.save_document)
        left_layout.addWidget(save_project_btn)
        self.left_collapsible_widgets.append(save_project_btn)
        save_image_btn = QPushButton("Sauvegarder l'image")
        save_image_btn.setProperty("variant", "primary")
        save_image_btn.clicked.connect(self.export_image)
        left_layout.addWidget(save_image_btn)
        self.left_collapsible_widgets.append(save_image_btn)
        left_scroll.setWidget(left_content)
        splitter.addWidget(left)

        self.canvas = CanvasView(self)
        self.left_toggle.setParent(self.canvas.viewport())
        self.left_toggle.setFixedSize(27, 34)
        self.left_toggle.move(5, 8)
        self.left_toggle.raise_()
        splitter.addWidget(self.canvas)

        right = QWidget()
        right.setObjectName("sidePanel")
        right.setMinimumWidth(270)
        right.setMaximumWidth(405)
        r_layout = QVBoxLayout(right)
        r_layout.setContentsMargins(0, 0, 0, 0)
        right_scroll = QScrollArea()
        right_scroll.setObjectName("rightPanelScroll")
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.right_scroll = right_scroll
        right_content = QWidget()
        right_content.setObjectName("sidePanel")
        right_content.setMinimumWidth(245)
        self.right_content = right_content
        right_content_layout = QVBoxLayout(right_content)
        right_content_layout.setContentsMargins(10, 10, 10, 10)
        right_content_layout.setSpacing(8)
        right_content_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.tabs = QTabWidget()
        self.tabs.setMinimumHeight(365)
        self.tabs.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.layer_list = LayerListWidget(self)
        self.layer_list.setMinimumHeight(170)
        self.layer_list.currentItemChanged.connect(self.on_layer_list_select)
        self.tabs.addTab(self.layer_list, "Calques")
        self.history = QUndoView(self.undo_stack)
        self.history.setEmptyLabel("Document initial")
        self.tabs.addTab(self.history, "Historique")
        self.tabs.addTab(self._build_tools_tab(), "Outils")
        self.tabs.currentChanged.connect(self.update_properties_panel_visibility)
        right_content_layout.addWidget(self.tabs)
        self._build_properties_panel()
        right_content_layout.addWidget(self.properties_label)
        right_content_layout.addWidget(self.properties_panel)
        right_content_layout.addStretch(1)
        right_scroll.setWidget(right_content)
        r_layout.addWidget(right_scroll)
        self._schedule_right_panel_layout()
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([245, 870, 315])
        self.zoom_label = QLabel("100 %")
        self.statusBar().addPermanentWidget(self.zoom_label)
        self.statusBar().showMessage("Prêt · Déplacez les objets sur le canvas")

    @staticmethod
    def _tool_button(icon: str, text: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("colorTool")
        button.setCheckable(True)
        button.setIcon(color_tool_icon(icon))
        button.setIconSize(QSize(20, 20))
        button.setText(text)
        button.setToolTip(tooltip)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return button

    def _build_selection_settings(self) -> QWidget:
        """Options shared by the selection tools, plus the magic wand settings."""
        self.selection_settings = QWidget()
        layout = QFormLayout(self.selection_settings)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(5)
        self.selection_mode_combo = QComboBox()
        for mode in COMBINE_MODES:
            self.selection_mode_combo.addItem(COMBINE_LABELS[mode], mode)
        self.selection_mode_combo.setToolTip(
            "Maj : ajouter · Alt : soustraire · Maj+Alt : intersection"
        )
        self.selection_pixel_perfect = QCheckBox("Pixel parfait")
        self.selection_pixel_perfect.setChecked(True)
        self.selection_pixel_perfect.setToolTip("Bords nets, sans anticrénelage (pixel art)")
        self.selection_feather = QSpinBox()
        self.selection_feather.setRange(0, 100)
        self.selection_feather.setSuffix(" px")
        self.selection_feather.setToolTip("Adoucissement des bords, pour les images classiques")
        self.selection_feather.setEnabled(False)
        self.selection_pixel_perfect.toggled.connect(
            lambda checked: self.selection_feather.setEnabled(not checked)
        )
        self.show_selection_mask = QCheckBox("Afficher le masque")
        self.show_selection_mask.setToolTip("Voile rouge sur les zones non sélectionnées")
        self.show_selection_mask.toggled.connect(lambda _checked: self._refresh_selection_visual())
        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(4)
        for text, tooltip, method in (("Tout", "Tout sélectionner · Ctrl+A", self.select_all),
                                      ("Aucune", "Désélectionner · Ctrl+Maj+A", self.deselect),
                                      ("Inverser", "Inverser · Ctrl+Maj+I", self.invert_selection)):
            button = QPushButton(text)
            button.setToolTip(tooltip)
            button.clicked.connect(method)
            buttons_layout.addWidget(button)
        layout.addRow("Mode", self.selection_mode_combo)
        layout.addRow("Bords", self.selection_pixel_perfect)
        layout.addRow("Adoucissement", self.selection_feather)
        layout.addRow(buttons)
        layout.addRow(self.show_selection_mask)
        # Shared by the rectangle, ellipse and magic wand tools.
        self.separate_selection_btn = QPushButton("Séparer en nouveau calque")
        self.separate_selection_btn.setProperty("variant", "primary")
        self.separate_selection_btn.setToolTip(
            "Déplace la partie sélectionnée dans un nouveau calque · Entrée ou Ctrl+Maj+J"
        )
        self.separate_selection_btn.clicked.connect(lambda: self.selection_to_new_layer(cut=True))
        layout.addRow(self.separate_selection_btn)
        self.wand_settings = QWidget()
        wand_layout = QFormLayout(self.wand_settings)
        wand_layout.setContentsMargins(0, 0, 0, 0)
        wand_layout.setSpacing(5)
        self.wand_tolerance = QSpinBox()
        self.wand_tolerance.setRange(0, 255)
        self.wand_tolerance.setValue(32)
        self.wand_tolerance.setToolTip("Écart maximal sur chaque canal R, V, B et alpha")
        self.wand_contiguous = QCheckBox("Pixels contigus uniquement")
        self.wand_contiguous.setChecked(True)
        self.wand_contiguous.setToolTip("Décoché : toutes les couleurs similaires de l'image")
        self.wand_all_layers = QCheckBox("Échantillonner tous les calques")
        self.wand_all_layers.setToolTip("Décoché : seul le calque sélectionné est analysé")
        wand_layout.addRow("Tolérance", self.wand_tolerance)
        wand_layout.addRow(self.wand_contiguous)
        wand_layout.addRow(self.wand_all_layers)
        return self.selection_settings

    def _build_tools_tab(self) -> QWidget:
        tools = QWidget()
        tools_layout = QVBoxLayout(tools)
        tools_layout.setContentsMargins(10, 12, 10, 12)
        add_text_tool = QPushButton("T  Ajouter un calque texte")
        add_text_tool.clicked.connect(self.add_text)
        tools_layout.addWidget(add_text_tool)
        library_button = QPushButton("Insérer un modèle…")
        library_button.setToolTip("Bulles, encadrés, bandeaux, cadres et vos propres modèles · Ctrl+Maj+B")
        library_button.clicked.connect(self.open_template_library)
        tools_layout.addWidget(library_button)
        self.color_tools_label = QLabel("Couleur")
        tools_layout.addWidget(self.color_tools_label)
        color_editor = QWidget()
        color_editor.setObjectName("colorEditor")
        self.color_editor = color_editor
        color_layout = QHBoxLayout(color_editor)
        color_layout.setContentsMargins(8, 8, 8, 8)
        color_layout.setSpacing(10)
        self.color_preview = QPushButton()
        self.color_preview.setFixedSize(54, 76)
        self.color_preview.setToolTip("Cliquer pour choisir une couleur")
        self.color_preview.clicked.connect(self.choose_replacement_color)
        preview_column = QWidget()
        preview_layout = QVBoxLayout(preview_column)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(5)
        preview_layout.addWidget(self.color_preview)
        self.picker_btn = QToolButton()
        self.picker_btn.setObjectName("colorTool")
        self.picker_btn.setCheckable(True)
        self.picker_btn.setIcon(color_tool_icon("picker"))
        self.picker_btn.setIconSize(QSize(20, 20))
        self.picker_btn.setToolTip("Prélever une couleur sur le canvas")
        self.picker_btn.clicked.connect(
            lambda checked: self.activate_picker("tools", checked)
        )
        color_layout.addWidget(preview_column)
        color_fields = QWidget()
        color_fields_layout = QFormLayout(color_fields)
        color_fields_layout.setContentsMargins(0, 0, 0, 0)
        color_fields_layout.setSpacing(5)
        self.sampled_color_input = QLineEdit()
        self.sampled_rgb_input = QLineEdit()
        self.sampled_hsl_input = QLineEdit()
        self.sampled_color_input.setPlaceholderText(COLORS["primary"])
        self.sampled_rgb_input.setPlaceholderText("77, 214, 231")
        self.sampled_hsl_input.setPlaceholderText("187, 76 %, 60 %")
        self.sampled_color_input.textChanged.connect(self.update_color_from_hex)
        self.sampled_rgb_input.textChanged.connect(self.update_color_from_rgb)
        self.sampled_hsl_input.textChanged.connect(self.update_color_from_hsl)
        color_fields_layout.addRow("HEX", self.sampled_color_input)
        color_fields_layout.addRow("RVB", self.sampled_rgb_input)
        color_fields_layout.addRow("HSL", self.sampled_hsl_input)
        color_layout.addWidget(color_fields, stretch=1)
        tools_layout.addWidget(color_editor)
        paint_tools = QWidget()
        paint_tools_layout = QVBoxLayout(paint_tools)
        paint_tools_layout.setContentsMargins(0, 0, 0, 0)
        paint_tools_layout.setSpacing(6)
        self.picker_btn.setText("Pipette")
        self.picker_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.picker_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        paint_tools_layout.addWidget(self.picker_btn)
        self.screen_picker_btn = self._tool_button(
            "screen_picker", "Pipette écran",
            "Prélever une couleur n'importe où sur l'écran, même hors de Manta Layers")
        self.screen_picker_btn.setCheckable(False)
        self.screen_picker_btn.clicked.connect(self.start_screen_picker)
        paint_tools_layout.addWidget(self.screen_picker_btn)
        self.paint_bucket_btn = QToolButton()
        self.paint_bucket_btn.setObjectName("colorTool")
        self.paint_bucket_btn.setCheckable(True)
        self.paint_bucket_btn.setIcon(color_tool_icon("bucket"))
        self.paint_bucket_btn.setIconSize(QSize(20, 20))
        self.paint_bucket_btn.setText("Remplissage")
        self.paint_bucket_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.paint_bucket_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.paint_bucket_btn.setToolTip("Pot de peinture : remplir les pixels contigus")
        self.paint_bucket_btn.clicked.connect(
            lambda checked: self.toggle_paint_mode("contiguous", checked)
        )
        self.paint_global_btn = QToolButton()
        self.paint_global_btn.setObjectName("colorTool")
        self.paint_global_btn.setCheckable(True)
        self.paint_global_btn.setIcon(color_tool_icon("bucket_global"))
        self.paint_global_btn.setIconSize(QSize(20, 20))
        self.paint_global_btn.setText("Remplissage +")
        self.paint_global_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.paint_global_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.paint_global_btn.setToolTip("Pot + : remplacer cette couleur partout sur le calque")
        self.paint_global_btn.clicked.connect(
            lambda checked: self.toggle_paint_mode("global", checked)
        )
        paint_tools_layout.addWidget(self.paint_bucket_btn)
        paint_tools_layout.addWidget(self.paint_global_btn)
        self.eraser_btn = QToolButton()
        self.eraser_btn.setObjectName("colorTool")
        self.eraser_btn.setCheckable(True)
        self.eraser_btn.setIcon(color_tool_icon("eraser"))
        self.eraser_btn.setIconSize(QSize(20, 20))
        self.eraser_btn.setText("Gomme")
        self.eraser_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.eraser_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.eraser_btn.setToolTip("Gomme (E)")
        self.eraser_btn.clicked.connect(self.set_eraser_active)
        paint_tools_layout.addWidget(self.eraser_btn)
        self.text_tool_btn = self._tool_button(
            "text", "Texte", "Outil texte (T) : cliquer sur le canvas pour écrire"
        )
        self.text_tool_btn.clicked.connect(self.set_text_tool_active)
        paint_tools_layout.addWidget(self.text_tool_btn)
        paint_tools_layout.addWidget(QLabel("Sélection"))
        for tool, icon, text, tooltip in (
            ("rect", "select_rect", "Rectangle", "Sélection rectangulaire (M)"),
            ("ellipse", "select_ellipse", "Ellipse", "Sélection elliptique"),
            ("wand", "wand", "Baguette magique", "Baguette magique (W) : pixels de couleur proche"),
            ("lasso", "lasso", "Lasso", "Lasso libre (L) : dessiner le contour en maintenant le bouton"),
            ("polygon", "polygon_lasso", "Lasso polygonal",
             "Lasso polygonal : un clic par point ; double-clic, Entrée ou clic sur le premier point "
             "pour fermer ; Retour arrière retire un point ; Échap annule"),
        ):
            button = self._tool_button(icon, text, tooltip)
            button.clicked.connect(
                lambda checked, tool=tool: self.set_selection_tool(tool if checked else None)
            )
            paint_tools_layout.addWidget(button)
            self.selection_tool_buttons[tool] = button
        paint_tools_layout.addWidget(QLabel("Formes"))
        for kind, icon, text, tooltip in (
            ("rectangle", "shape_rectangle", "Rectangle", "Rectangle : glisser sur le canvas · Maj : carré"),
            ("ellipse", "shape_ellipse", "Ellipse", "Ellipse : glisser sur le canvas · Maj : cercle"),
            ("polygon", "shape_polygon", "Polygone", "Polygone régulier : glisser sur le canvas"),
            ("line", "shape_line", "Ligne", "Ligne droite : glisser · Maj : angles de 45°"),
            ("arrow", "shape_arrow", "Flèche", "Flèche : glisser de la base vers la pointe · Maj : angles de 45°"),
        ):
            button = self._tool_button(icon, text, tooltip)
            button.clicked.connect(lambda checked, kind=kind: self.set_shape_tool(kind if checked else None))
            paint_tools_layout.addWidget(button)
            self.shape_tool_buttons[kind] = button
        tools_layout.addWidget(paint_tools)
        self.remove_background_btn = QPushButton("Supprimer l'arrière-plan…")
        self.remove_background_btn.setToolTip("Détourage local, avec aperçu, appliqué comme masque modifiable")
        self.remove_background_btn.clicked.connect(self.remove_background)
        tools_layout.addWidget(self.remove_background_btn)
        self.paint_settings = QWidget()
        paint_settings_layout = QFormLayout(self.paint_settings)
        paint_settings_layout.setContentsMargins(0, 0, 0, 0)
        paint_settings_layout.setSpacing(5)
        self.paint_tolerance = QSpinBox()
        self.paint_tolerance.setRange(0, 255)
        self.paint_tolerance.setValue(15)
        self.paint_tolerance.setToolTip(
            "Écart maximal autorisé sur chacun des canaux rouge, vert et bleu"
        )
        self.preserve_shading = QCheckBox("Préserver ombres et reflets")
        self.preserve_shading.setToolTip(
            "Recoloriser en conservant les nuances de luminosité d'origine"
        )
        paint_settings_layout.addRow("Tolérance", self.paint_tolerance)
        paint_settings_layout.addRow("Recolorisation", self.preserve_shading)
        tools_layout.addWidget(self.paint_settings)
        self.eraser_settings = QWidget()
        self.eraser_settings.setObjectName("eraserSettings")
        eraser_layout = QFormLayout(self.eraser_settings)
        eraser_layout.setContentsMargins(0, 6, 0, 0)
        eraser_layout.setSpacing(5)
        self.eraser_size_preset = QComboBox()
        for size in (1, 2, 4, 8, 16, 32):
            self.eraser_size_preset.addItem(f"{size} × {size} px", size)
        self.eraser_size_preset.addItem("Personnalisée", None)
        self.eraser_size_preset.setCurrentIndex(3)
        self.eraser_size_preset.currentIndexChanged.connect(self.update_eraser_size_preset)
        self.eraser_size = QSpinBox()
        self.eraser_size.setRange(1, 2048)
        self.eraser_size.setValue(8)
        self.eraser_size.setSuffix(" px")
        self.eraser_size.setEnabled(False)
        self.eraser_shape = QComboBox()
        self.eraser_shape.addItem("Carré", "square")
        self.eraser_shape.addItem("Cercle", "circle")
        self.eraser_pixel_art = QCheckBox("Mode Pixel Art")
        self.eraser_pixel_art.setChecked(True)
        self.eraser_pixel_art.toggled.connect(self.update_eraser_mode_controls)
        self.eraser_hardness = QSpinBox()
        self.eraser_hardness.setRange(0, 100)
        self.eraser_hardness.setValue(100)
        self.eraser_hardness.setSuffix(" %")
        self.eraser_hardness.setEnabled(False)
        self.eraser_opacity = QSpinBox()
        self.eraser_opacity.setRange(1, 100)
        self.eraser_opacity.setSingleStep(25)
        self.eraser_opacity.setValue(100)
        self.eraser_opacity.setSuffix(" %")
        eraser_layout.addRow("Taille gomme", self.eraser_size_preset)
        eraser_layout.addRow("Taille libre", self.eraser_size)
        eraser_layout.addRow("Forme", self.eraser_shape)
        eraser_layout.addRow("Mode", self.eraser_pixel_art)
        eraser_layout.addRow("Dureté", self.eraser_hardness)
        eraser_layout.addRow("Opacité", self.eraser_opacity)
        tools_layout.addWidget(self.eraser_settings)
        tools_layout.addWidget(self._build_selection_settings())
        tools_layout.addWidget(self.wand_settings)
        self.alternative_label = QLabel("Alternative :")
        tools_layout.addWidget(self.alternative_label)
        self.variations_widget = QWidget()
        variations_layout = QHBoxLayout(self.variations_widget)
        variations_layout.setContentsMargins(0, 0, 0, 0)
        variations_layout.setSpacing(4)
        self.variation_buttons = []
        for index in range(9):
            swatch = QToolButton()
            swatch.setFixedSize(25, 25)
            swatch.clicked.connect(lambda _checked=False, i=index: self.choose_variation(i))
            variations_layout.addWidget(swatch)
            self.variation_buttons.append(swatch)
        tools_layout.addWidget(self.variations_widget)
        self.set_current_color(self.replacement_color)
        self.update_tool_options_visibility()
        tools_layout.addStretch(1)
        self.tools_tab = tools
        return tools

    def _build_properties_panel(self):
        self.properties_label = QLabel("PROPRIÉTÉS DU CALQUE")
        self.properties_label.setObjectName("sectionTitle")
        self.properties_panel = QWidget()
        self.properties_panel.setObjectName("propertyCard")
        self.properties_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.property_form = QFormLayout(self.properties_panel)
        self.property_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.property_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.property_form.setVerticalSpacing(8)
        self.property_form.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.inputs = {}
        # Positions and angles are not bounded by the model (layers can be dragged
        # off the canvas, rotations add up): the ranges stay wide.
        for key, label, minimum, maximum, decimals, step in [
            ("x", "Position X", -2 * MAX_DIMENSION, 2 * MAX_DIMENSION, 1, 10),
            ("y", "Position Y", -2 * MAX_DIMENSION, 2 * MAX_DIMENSION, 1, 10),
            ("sx", "Échelle X", 0.05, 50, 2, .05),
            ("sy", "Échelle Y", 0.05, 50, 2, .05),
            ("rotation", "Rotation (°)", -36000, 36000, 1, 5),
            ("opacity", "Opacité (%)", 0, 100, 0, 5),
        ]:
            w = QDoubleSpinBox()
            w.setRange(minimum, maximum)
            w.setDecimals(decimals)
            w.setSingleStep(step)
            w.setKeyboardTracking(False)
            w.editingFinished.connect(lambda key=key: self.commit_property(key))
            self.property_form.addRow(label, w)
            self.inputs[key] = w
        self.name_input = QLineEdit()
        self.name_input.editingFinished.connect(lambda: self.commit_property("name"))
        self.property_form.insertRow(0, "Nom du calque", self.name_input)
        self.text_input = CommitPlainTextEdit()
        self.text_input.setMinimumHeight(76)
        self.text_input.setMaximumHeight(120)
        self.text_input.setPlaceholderText("Saisissez le texte…")
        self.text_input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.text_input.editingFinished.connect(lambda: self.commit_property("text"))
        self.property_form.addRow("Contenu texte", self.text_input)
        self.text_alignment_control = QWidget()
        alignment_layout = QHBoxLayout(self.text_alignment_control)
        alignment_layout.setContentsMargins(0, 0, 0, 0)
        alignment_layout.setSpacing(5)
        self.text_alignment_group = QButtonGroup(self)
        self.text_alignment_group.setExclusive(True)
        self.text_alignment_buttons = {}
        for alignment, tooltip in (
            ("left", "Aligner à gauche"),
            ("center", "Centrer"),
            ("right", "Aligner à droite"),
        ):
            button = QToolButton()
            button.setObjectName("textAlignment")
            button.setCheckable(True)
            button.setIcon(alignment_icon(alignment))
            button.setIconSize(QSize(20, 20))
            button.setToolTip(tooltip)
            button.clicked.connect(lambda _checked=False: self.commit_property("path_alignment"))
            self.text_alignment_group.addButton(button)
            self.text_alignment_buttons[alignment] = button
            alignment_layout.addWidget(button)
        alignment_layout.addStretch(1)
        self.text_alignment_buttons["center"].setChecked(True)
        self.property_form.addRow("Alignement", self.text_alignment_control)
        self.font_combo = QFontComboBox()
        self.font_combo.currentFontChanged.connect(self.on_font_changed)
        self.property_form.addRow("Police", self.font_combo)
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 300)
        self.font_size.setKeyboardTracking(False)
        self.font_size.editingFinished.connect(lambda: self.commit_property("font_size"))
        self.property_form.addRow("Taille du texte", self.font_size)
        self.text_color_swatch = QPushButton()
        self.text_color_swatch.setFixedSize(36, 28)
        self.text_color_swatch.setToolTip("Choisir la couleur du texte")
        self.text_color_swatch.clicked.connect(self.choose_color)
        self.color_btn = QPushButton("#000000")
        self.color_btn.clicked.connect(self.choose_color)
        self.text_color_control = QWidget()
        text_color_layout = QHBoxLayout(self.text_color_control)
        text_color_layout.setContentsMargins(0, 0, 0, 0)
        text_color_layout.setSpacing(6)
        text_preview_column = QWidget()
        text_preview_layout = QVBoxLayout(text_preview_column)
        text_preview_layout.setContentsMargins(0, 0, 0, 0)
        text_preview_layout.setSpacing(4)
        text_preview_layout.addWidget(self.text_color_swatch)
        self.text_picker_btn = QToolButton()
        self.text_picker_btn.setObjectName("colorTool")
        self.text_picker_btn.setCheckable(True)
        self.text_picker_btn.setIcon(color_tool_icon("picker"))
        self.text_picker_btn.setIconSize(QSize(18, 18))
        self.text_picker_btn.setToolTip("Prélever la couleur du texte sur le canvas")
        self.text_picker_btn.clicked.connect(
            lambda checked: self.activate_picker("text", checked)
        )
        text_preview_layout.addWidget(self.text_picker_btn)
        text_color_layout.addWidget(text_preview_column)
        text_color_layout.addWidget(self.color_btn, stretch=1)
        self.property_form.addRow("Couleur du texte", self.text_color_control)
        self.text_background_swatch = QPushButton()
        self.text_background_swatch.setFixedSize(36, 28)
        self.text_background_swatch.setToolTip("Choisir la couleur de fond du texte")
        self.text_background_swatch.clicked.connect(self.choose_text_background)
        self.text_background_btn = QPushButton("Transparent")
        self.text_background_btn.clicked.connect(self.choose_text_background)
        self.text_background_clear = QToolButton()
        self.text_background_clear.setObjectName("colorTool")
        self.text_background_clear.setText("×")
        self.text_background_clear.setToolTip("Rendre le fond transparent")
        self.text_background_clear.clicked.connect(self.clear_text_background)
        self.text_background_control = QWidget()
        background_layout = QHBoxLayout(self.text_background_control)
        background_layout.setContentsMargins(0, 0, 0, 0)
        background_layout.setSpacing(6)
        background_preview_column = QWidget()
        background_preview_layout = QVBoxLayout(background_preview_column)
        background_preview_layout.setContentsMargins(0, 0, 0, 0)
        background_preview_layout.setSpacing(4)
        background_preview_layout.addWidget(self.text_background_swatch)
        self.text_background_picker_btn = QToolButton()
        self.text_background_picker_btn.setObjectName("colorTool")
        self.text_background_picker_btn.setCheckable(True)
        self.text_background_picker_btn.setIcon(color_tool_icon("picker"))
        self.text_background_picker_btn.setIconSize(QSize(18, 18))
        self.text_background_picker_btn.setToolTip("Prélever la couleur de fond sur le canvas")
        self.text_background_picker_btn.clicked.connect(
            lambda checked: self.activate_picker("text_background", checked)
        )
        background_preview_layout.addWidget(self.text_background_picker_btn)
        background_layout.addWidget(background_preview_column)
        background_layout.addWidget(self.text_background_btn, stretch=1)
        background_layout.addWidget(self.text_background_clear)
        self.property_form.addRow("Couleur de fond", self.text_background_control)
        self.text_shape_control = QWidget()
        shape_layout = QHBoxLayout(self.text_shape_control)
        shape_layout.setContentsMargins(0, 0, 0, 0)
        shape_layout.setSpacing(6)
        self.text_shape_combo = QComboBox()
        for shape in TEXT_SHAPES:
            self.text_shape_combo.addItem(SHAPE_LABELS[shape], shape)
        self.text_shape_combo.setToolTip(
            "Trajectoire du texte ; les poignées cyan sur le canvas la déforment"
        )
        self.text_shape_combo.currentIndexChanged.connect(
            lambda _index: self.commit_property("text_deformation")
        )
        self.text_controls_reset_btn = QToolButton()
        self.text_controls_reset_btn.setText("↺")
        self.text_controls_reset_btn.setToolTip("Réinitialiser les points de la courbe personnalisée")
        self.text_controls_reset_btn.clicked.connect(self.reset_text_controls)
        shape_layout.addWidget(self.text_shape_combo, stretch=1)
        shape_layout.addWidget(self.text_controls_reset_btn)
        self.property_form.addRow("Forme", self.text_shape_control)
        self.curve_control = QWidget()
        curve_layout = QHBoxLayout(self.curve_control)
        curve_layout.setContentsMargins(0, 0, 0, 0)
        curve_layout.setSpacing(6)
        self.curve_intensity = QSlider(Qt.Orientation.Horizontal)
        self.curve_intensity.setRange(-100, 100)
        self.curve_intensity.setValue(0)
        self.curve_intensity.setToolTip("Courbure : négatif vers le bas, positif vers le haut")
        self.curve_intensity.valueChanged.connect(self.preview_curve_intensity)
        self.curve_intensity.sliderReleased.connect(lambda: self.commit_property("curve_intensity"))
        # Clavier, molette et clic sur la rainure ne passent pas par sliderReleased :
        # leur changement est validé après une courte pause, en une seule étape.
        self.curve_commit_timer = QTimer(self)
        self.curve_commit_timer.setSingleShot(True)
        self.curve_commit_timer.setInterval(350)
        self.curve_commit_timer.timeout.connect(lambda: self.commit_property("curve_intensity"))
        self.curve_value = QSpinBox()
        self.curve_value.setRange(-100, 100)
        self.curve_value.setFixedWidth(66)
        self.curve_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.curve_value.setToolTip("Valeur de courbure")
        self.curve_value.valueChanged.connect(self.set_curve_from_value)
        self.curve_value.editingFinished.connect(lambda: self.commit_property("curve_intensity"))
        self.curve_reset_btn = QToolButton()
        self.curve_reset_btn.setText("0")
        self.curve_reset_btn.setToolTip("Remettre le texte droit")
        self.curve_reset_btn.clicked.connect(self.reset_curve_only)
        curve_layout.addWidget(self.curve_intensity, stretch=1)
        curve_layout.addWidget(self.curve_value)
        curve_layout.addWidget(self.curve_reset_btn)
        self.property_form.addRow("Courbure", self.curve_control)
        self.character_spacing = QDoubleSpinBox()
        self.character_spacing.setRange(-50, 200)
        self.character_spacing.setDecimals(1)
        self.character_spacing.setSuffix(" px")
        self.character_spacing.setKeyboardTracking(False)
        self.character_spacing.editingFinished.connect(lambda: self.commit_property("character_spacing"))
        self.property_form.addRow("Espacement", self.character_spacing)
        self.upright_letters = QCheckBox("Lettres verticales")
        self.upright_letters.setToolTip(
            "Garder les lettres droites au lieu de les incliner le long de la trajectoire"
        )
        self.upright_letters.clicked.connect(lambda _checked: self.commit_property("path_orientation"))
        self.property_form.addRow("Orientation", self.upright_letters)
        self.lock_btn = QPushButton("Verrouiller / déverrouiller")
        self.lock_btn.clicked.connect(self.toggle_lock)
        self.property_form.addRow("Édition", self.lock_btn)
        self.shape_rows = ShapePropertyRows(self, self.property_form)
        self.text_property_widgets = (
            self.text_input, self.text_alignment_control, self.font_combo, self.font_size,
            self.text_color_control, self.text_background_control, self.text_shape_control,
            self.curve_control, self.character_spacing, self.upright_letters,
            self.lock_btn
        )

    def _action(self, menu, label: str, callback, shortcut=None, icon=None):
        act = QAction(label, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        if icon:
            act.setIcon(QIcon(str(icon)))
        act.triggered.connect(callback)
        menu.addAction(act)
        return act

    def _build_actions(self):
        f = self.menuBar().addMenu("Fichier")
        self._action(f, "Nouveau projet…", self.new_document, "Ctrl+N")
        self._action(f, "Ouvrir un projet…", self.open_document, "Ctrl+O")
        f.addSeparator()
        self._action(f, "Importer une image…", self.add_images, "Ctrl+I")
        self._action(f, "Ajouter du texte…", self.add_text, "Ctrl+T")
        self._action(f, "Importer une police…", self.import_fonts)
        f.addSeparator()
        self._action(f, "Sauvegarder l'image…", self.export_image, "Ctrl+S")
        self._action(f, "Sauvegarder le projet", self.save_document, "Ctrl+Shift+S")
        self._action(f, "Sauvegarder le projet sous…", self.save_as_document)
        self._action(f, "Enregistrer comme modèle…", self.save_as_template)
        f.addSeparator()
        self._action(f, "Quitter", self.close, "Alt+F4")

        e = self.menuBar().addMenu("Édition")
        self.undo_action = self.undo_stack.createUndoAction(self, "Annuler")
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        e.addAction(self.undo_action)
        self.redo_action = self.undo_stack.createRedoAction(self, "Rétablir")
        self.redo_action.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        e.addAction(self.redo_action)
        e.addSeparator()
        self.copy_action = self._action(e, "Copier le calque", self.copy_layer, "Ctrl+C")
        self.cut_action = self._action(e, "Couper le calque", self.cut_layer, "Ctrl+X")
        self.paste_action = self._action(e, "Coller l'image", self.paste_image, "Ctrl+V")
        e.addSeparator()
        self._action(e, "Dupliquer le calque", self.duplicate_layer, "Ctrl+D")
        self._action(e, "Retourner horizontalement", self.flip_layer_horizontal)
        self._action(e, "Retourner verticalement", self.flip_layer_vertical)
        self._action(e, "Verrouiller / déverrouiller", self.toggle_lock)
        self.delete_action = self._action(e, "Supprimer (sélection ou calque)", self.delete_selection_or_layer, "Delete")
        e.addSeparator()
        self._action(e, "Rogner les marges transparentes du calque", self.trim_layer_margins)
        self._action(e, "Recadrer le document sur son contenu", self.crop_document_to_content)
        tools_menu = self.menuBar().addMenu("Outils")
        self.eraser_action = QAction(color_tool_icon("eraser"), "Gomme (E)", self)
        self.eraser_action.setCheckable(True)
        self.eraser_action.triggered.connect(self.set_eraser_active)
        tools_menu.addAction(self.eraser_action)
        self.eraser_shortcut = QShortcut(QKeySequence("E"), self.canvas)
        self.eraser_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.eraser_shortcut.activated.connect(
            lambda: self.set_eraser_active(not self.eraser_active)
        )
        self.text_tool_action = QAction(color_tool_icon("text"), "Outil texte (T)", self)
        self.text_tool_action.setCheckable(True)
        self.text_tool_action.triggered.connect(self.set_text_tool_active)
        tools_menu.addAction(self.text_tool_action)
        tools_menu.addSeparator()
        self._action(tools_menu, "Supprimer l'arrière-plan…", self.remove_background)
        self._action(tools_menu, "Pipette écran (tout le bureau)", self.start_screen_picker)
        tools_menu.addSeparator()
        self._action(tools_menu, "Créateur de tokens…", self.open_token_creator)
        self._action(tools_menu, "Découper une spritesheet…", self.open_sprite_slicer)
        self.text_tool_shortcut = QShortcut(QKeySequence("T"), self.canvas)
        self.text_tool_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.text_tool_shortcut.activated.connect(
            lambda: self.set_text_tool_active(not self.text_tool_active)
        )
        for key, tool in (("M", "rect"), ("W", "wand"), ("L", "lasso")):
            shortcut = QShortcut(QKeySequence(key), self.canvas)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(
                lambda tool=tool: self.set_selection_tool(None if self.selection_tool == tool else tool)
            )
        s = self.menuBar().addMenu("Sélection")
        self._action(s, "Tout sélectionner", self.select_all, "Ctrl+A")
        deselect = self._action(s, "Désélectionner", self.deselect, "Ctrl+Shift+A")
        self._action(s, "Inverser la sélection", self.invert_selection, "Ctrl+Shift+I")
        show_mask = self._action(s, "Afficher le masque de sélection",
                                 lambda: self.show_selection_mask.toggle(), "Ctrl+M")
        show_mask.setCheckable(True)
        self.show_selection_mask.toggled.connect(show_mask.setChecked)
        s.addSeparator()
        copy_layer = self._action(s, "Copier vers un nouveau calque",
                                  lambda: self.selection_to_new_layer(False), "Ctrl+J")
        cut_layer = self._action(s, "Couper vers un nouveau calque",
                                 lambda: self.selection_to_new_layer(True), "Ctrl+Shift+J")
        clear = self._action(s, "Effacer le contenu sélectionné", self.clear_selection_content)
        s.addSeparator()
        hide = self._action(s, "Masque du calque : masquer la sélection", self.clear_selection_content)
        reveal = self._action(s, "Masque du calque : révéler la sélection", self.reveal_selection_in_mask)
        self._action(s, "Supprimer le masque du calque", self.remove_layer_mask)
        self.selection_actions = (deselect, copy_layer, cut_layer, clear, hide, reveal)
        self._update_selection_actions()
        QApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)
        insertion = self.menuBar().addMenu("Insertion")
        self._action(insertion, "Image…", self.add_images)
        self._action(insertion, "Texte…", self.add_text)
        self._action(insertion, "Bibliothèque de modèles…", self.open_template_library, "Ctrl+Shift+B")
        v = self.menuBar().addMenu("Affichage")
        self._action(v, "Afficher / masquer le panneau d'utilitaires", self.toggle_left_sidebar, "F9")
        self._action(v, "Ajuster à la fenêtre", self.canvas.fit_document, "Ctrl+0")
        self.snap_action = self._action(v, "Magnétisme des guides (Alt pour l'ignorer)", self.toggle_snap)
        self.snap_action.setCheckable(True)
        self.snap_action.setChecked(self.snap_enabled)
        self._action(v, "Zoom +", lambda: self.change_zoom(1.2), "Ctrl++")
        self._action(v, "Zoom -", lambda: self.change_zoom(1/1.2), "Ctrl+-")
        h = self.menuBar().addMenu("Aide")
        self._action(h, "À propos", self.about)
    def toggle_left_sidebar(self):
        self.left_sidebar_expanded = not self.left_sidebar_expanded
        if self.left_sidebar_expanded:
            sizes = self.main_splitter.sizes()
            self.left_panel.show()
            self.main_splitter.setSizes([
                self.left_sidebar_width,
                max(1, sizes[1] - self.left_sidebar_width), sizes[2],
            ])
            self.left_toggle.setIcon(sidebar_arrow_icon(False))
            self.left_toggle.setToolTip("Replier le panneau d'utilitaires")
        else:
            self.left_sidebar_width = max(220, self.main_splitter.sizes()[0])
            self.left_panel.hide()
            self.left_toggle.setIcon(sidebar_arrow_icon(True))
            self.left_toggle.setToolTip("Ouvrir le panneau d'utilitaires")

    def _load_demo(self):
        demo = ROOT / "exemples" / "Manta_Demo.manta"
        document = Document()
        if demo.exists():
            try:
                document = open_project(demo)
            except Exception:
                document = Document()
        try:
            self.install_document(document, document.layers[-1].id if document.layers else None)
        except Exception:
            self.install_document(Document(), None)
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self.canvas.fit_document()
        self.update_title()

    def install_document(self, doc: Document, selected: str | None):
        """Affiche un document. Si son rendu échoue, l'état courant reste intact."""
        scene = make_scene(doc, interactive=True)
        self._revision += 1
        # The scene is replaced: an editor typing into the old one is dropped,
        # and a drag in progress forgets the items about to be deleted.
        self._close_inline_editor()
        self.canvas.reset_interaction()
        for folder in doc.folders:
            folder.collapsed = self._collapsed_folders.get(folder.id, folder.collapsed)
        self.refreshing = True
        try:
            self.document = doc
            self.checked_ids &= {layer.id for layer in doc.layers}
            self.selected_id = selected if doc.layer(selected) else None
            if self.selected_id:
                self.last_selected_id = self.selected_id
            self.canvas_scene = scene
            self.canvas.setScene(self.canvas_scene)
            self.canvas_scene.selectionChanged.connect(self.on_scene_select)
            self._rebuild_layer_list(doc)
            for item in self.canvas_scene.items():
                if item.data(0) == self.selected_id:
                    item.setSelected(True)
                    break
            self.doc_info.setText(f"{doc.width} × {doc.height} px · {len(doc.layers)} calque(s)")
            if self.selection_mask is not None and self.selection_mask.size != (doc.width, doc.height):
                self.selection_mask = selection.resize_canvas(self.selection_mask, (doc.width, doc.height))
                self._refresh_selection_visual()
            self._refresh_properties()
            self.update_utility_buttons()
        finally:
            self.refreshing = False
        self.canvas.viewport().update()
        self.update_title()

    def _rebuild_layer_list(self, doc: Document):
        """Rows from top to bottom; a folder row precedes its (unless collapsed) layers."""
        scroll = self.layer_list.verticalScrollBar().value()
        self.layer_list.clear()
        self._layer_rows = {}
        shown_folders = set()
        for layer in reversed(doc.layers):
            folder = doc.folder(layer.folder)
            if folder is not None and folder.id not in shown_folders:
                shown_folders.add(folder.id)
                self._add_layer_list_row(folder.id, True, build_folder_row(
                    self, folder, self._folder_check_state(doc, folder.id)))
            if folder is not None and folder.collapsed:
                continue
            controls = build_layer_row(self, layer, layer.id in self.checked_ids)
            self._layer_rows[layer.id] = controls
            row = self._add_layer_list_row(layer.id, False, controls)
            if layer.id == self.selected_id:
                self.layer_list.setCurrentItem(row)
        self.layer_list.verticalScrollBar().setValue(scroll)

    def _add_layer_list_row(self, item_id: str, is_folder: bool, controls: QWidget) -> QListWidgetItem:
        row = QListWidgetItem()
        row.setData(Qt.ItemDataRole.UserRole, item_id)
        row.setData(FOLDER_ROLE, is_folder)
        self.layer_list.addItem(row)
        row.setSizeHint(QSize(row.sizeHint().width(), 34))
        self._name_icon_buttons(controls)
        self.layer_list.setItemWidget(row, controls)
        return row

    def _folder_check_state(self, doc: Document, folder_id: str) -> Qt.CheckState:
        members = {layer.id for layer in doc.folder_members(folder_id)}
        checked = len(members & self.checked_ids)
        if checked == 0:
            return Qt.CheckState.Unchecked
        return Qt.CheckState.Checked if checked == len(members) else Qt.CheckState.PartiallyChecked

    # --- Multiple selection and folders ----------------------------------------------------
    # Checked layers form the multiple selection: a view state, outside the
    # document and the history, used by the folder, merge, delete and template actions.

    def checked_layer_ids(self) -> list[str]:
        """Checked layers that still exist, bottom to top."""
        return [layer.id for layer in self.document.layers if layer.id in self.checked_ids]

    def set_layer_checked(self, layer_id: str, checked: bool):
        if self.refreshing or self.document.layer(layer_id) is None:
            return
        if checked:
            self.checked_ids.add(layer_id)
        else:
            self.checked_ids.discard(layer_id)
        self._refresh_checks()

    def set_checked_layers(self, layer_ids) -> None:
        self.checked_ids = {layer_id for layer_id in layer_ids if self.document.layer(layer_id)}
        self._refresh_checks()

    def set_folder_checked(self, folder_id: str, checked: bool):
        members = {layer.id for layer in self.document.folder_members(folder_id)}
        if checked:
            self.checked_ids |= members
        else:
            self.checked_ids -= members
        self._refresh_checks()

    def toggle_folder_checked(self, folder_id: str):
        """Check every layer of the folder, or none when they all are already."""
        state = self._folder_check_state(self.document, folder_id)
        self.set_folder_checked(folder_id, state != Qt.CheckState.Checked)

    def _refresh_checks(self):
        """Update check boxes and highlights in place (the list keeps its scroll position)."""
        self.refreshing = True
        try:
            for index in range(self.layer_list.count()):
                row = self.layer_list.item(index)
                controls = self.layer_list.itemWidget(row)
                item_id = row.data(Qt.ItemDataRole.UserRole)
                box = controls.findChild(QCheckBox, "layerCheck") if controls else None
                if box is None:
                    continue
                if row.data(FOLDER_ROLE):
                    state = self._folder_check_state(self.document, item_id)
                    box.setTristate(state == Qt.CheckState.PartiallyChecked)
                    box.setCheckState(state)
                    set_row_checked(controls, state == Qt.CheckState.Checked)
                else:
                    box.setChecked(item_id in self.checked_ids)
                    set_row_checked(controls, item_id in self.checked_ids)
        finally:
            self.refreshing = False
        self.statusBar().showMessage(f"{len(self.checked_ids)} calque(s) dans la sélection multiple", 2500)

    def layer_name_clicked(self, layer_id: str):
        """Click selects the layer; Ctrl+click adds it to (or removes it from) the multiple selection."""
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_layer_checked(layer_id, layer_id not in self.checked_ids)
            return
        self.select_layer(layer_id)

    def set_folder_visibility(self, folder_id: str, visible: bool):
        folder = self.document.folder(folder_id)
        if self.refreshing or folder is None or folder.visible == visible:
            return
        self.mutate("Afficher / masquer le dossier",
                    lambda doc: setattr(doc.folder(folder_id), "visible", visible))

    def toggle_folder_collapsed(self, folder_id: str):
        """Folding only changes the list: a view state saved with the project, outside the history."""
        folder = self.document.folder(folder_id)
        if folder is None:
            return
        folder.collapsed = not folder.collapsed
        # Outside the history, but kept by undo and redo (their snapshots predate
        # the fold) and saved with the project.
        self._collapsed_folders[folder_id] = folder.collapsed
        self._rebuild_layer_list(self.document)

    def _unique_folder_name(self) -> str:
        names = {folder.name for folder in self.document.folders}
        return next(f"Dossier {index}" for index in range(1, len(names) + 2) if f"Dossier {index}" not in names)

    def create_folder_from_checked(self) -> bool:
        layer_ids = self.checked_layer_ids()
        if not layer_ids:
            self.statusBar().showMessage("Cochez les calques à regrouper", 3000)
            return False
        name, accepted = QInputDialog.getText(self, "Créer un dossier de calques", "Nom du dossier :",
                                              text=self._unique_folder_name())
        if not accepted:
            return False
        return self.mutate("Créer un dossier de calques",
                           lambda doc: doc.create_folder(layer_ids, name.strip() or "Dossier"))

    def rename_folder(self, folder_id: str) -> bool:
        folder = self.document.folder(folder_id)
        if folder is None:
            return False
        name, accepted = QInputDialog.getText(self, "Renommer le dossier", "Nom du dossier :", text=folder.name)
        clean = " ".join(name.split())
        if not accepted or not clean or clean == folder.name:
            return False
        return self.mutate("Renommer le dossier", lambda doc: setattr(doc.folder(folder_id), "name", clean))

    def dissolve_folder(self, folder_id: str) -> bool:
        if self.document.folder(folder_id) is None:
            return False
        return self.mutate("Dissocier le dossier", lambda doc: doc.dissolve_folder(folder_id))

    def delete_checked_layers(self) -> bool:
        layers = [self.document.layer(layer_id) for layer_id in self.checked_layer_ids()]
        removable = [layer.id for layer in layers if not layer.locked]
        if not removable:
            self.statusBar().showMessage(
                "Déverrouillez les calques avant de les supprimer" if layers else "Aucun calque coché", 3000)
            return False
        if not self.mutate(f"Supprimer {len(removable)} calque(s)", lambda doc: doc.remove_layers(removable)):
            return False
        self.checked_ids -= set(removable)
        if self.selected_id in removable:
            self.select_layer(None)
        self._refresh_checks()
        if len(removable) < len(layers):
            self.statusBar().showMessage("Les calques verrouillés ont été conservés", 4000)
        return True

    def merge_checked_layers(self) -> bool:
        """Merge the checked visible layers into one image layer, at the place of the topmost."""
        layers = [self.document.layer(layer_id) for layer_id in self.checked_layer_ids()]
        sources = [layer for layer in layers if self.document.is_visible(layer)]
        if len(sources) < 2:
            self.statusBar().showMessage("Cochez au moins deux calques visibles à fusionner", 3500)
            return False
        if any(layer.locked for layer in sources):
            self.statusBar().showMessage("Déverrouillez les calques avant de les fusionner", 3500)
            return False
        if merge_changes_appearance(self.document, [layer.id for layer in sources]):
            answer = QMessageBox.question(
                self, "Fusionner les calques",
                "Des calques non cochés se trouvent entre les calques à fusionner et les recouvrent. "
                "Le calque fusionné sera placé au-dessus d'eux : l'image changera d'aspect.\n\n"
                "Fusionner quand même ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            merged = render_layers_region(self.document, [layer.id for layer in sources])
        except ValueError as exc:
            self._report_failure("Fusionner les calques", exc)
            return False
        if merged is None:
            self.statusBar().showMessage("Les calques à fusionner n'ont aucun pixel visible", 3500)
            return False
        image, (left, top) = merged
        output = BytesIO()
        image.save(output, format="PNG")
        data, source_ids, holder = output.getvalue(), [layer.id for layer in sources], {}

        def apply(doc):
            top_layer = max((doc.layer(layer_id) for layer_id in source_ids), key=doc.layers.index)
            position = sum(1 for layer in doc.layers[:doc.layers.index(top_layer)] if layer.id not in source_ids)
            new = doc.add_image_bytes(data, f"Fusion de {len(source_ids)} calques", center=False)
            doc.layers.remove(new)
            new.x, new.y, new.folder = float(left), float(top), top_layer.folder
            doc.layers = [layer for layer in doc.layers if layer.id not in source_ids]
            doc.layers.insert(position, new)
            doc.normalize_folders()
            holder["id"] = new.id

        if not self.mutate("Fusionner les calques", apply):
            return False
        self.checked_ids = {holder["id"]}
        self.select_layer(holder["id"])
        self._refresh_checks()
        if len(sources) < len(layers):
            self.statusBar().showMessage("Les calques masqués n'ont pas été fusionnés", 4000)
        return True

    def create_template_from_checked(self) -> Path | None:
        """Save the checked layers, their folders and images as a reusable element template."""
        layer_ids = self.checked_layer_ids()
        bounds = layers_bounds(self.document, layer_ids) if layer_ids else None
        if bounds is None:
            self.statusBar().showMessage("Cochez les calques qui composeront le modèle", 3000)
            return None
        default = self.document.layer(layer_ids[-1]).name if len(layer_ids) == 1 else "Nouveau modèle"
        name, accepted = QInputDialog.getText(self, "Créer un modèle", "Nom du modèle :", text=default)
        if not accepted or not name.strip():
            return None
        try:
            elements = extract_elements(self.document, layer_ids, bounds)
            destination = self._confirm_template_replacement(name, "elements")
            if destination is False:
                return None
            path = save_template(elements, name, self._template_thumbnail(elements),
                                 destination=destination, kind="elements")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Création du modèle impossible", str(exc))
            return None
        self.statusBar().showMessage(f"Modèle créé : {name.strip()} · Insertion > Bibliothèque de modèles", 6000)
        return path

    def _confirm_template_replacement(self, name: str, kind: str):
        """Path of a same-named template to replace, None for a new one, False if cancelled."""
        existing = next((info for info in list_templates(kind=kind)
                         if info.name.casefold() == name.strip().casefold()), None)
        if existing is None:
            return None
        answer = QMessageBox.question(
            self, "Remplacer le modèle",
            f"Un modèle nommé « {existing.name} » existe déjà. Le remplacer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        return existing.path if answer == QMessageBox.StandardButton.Yes else False

    @staticmethod
    def _template_thumbnail(document: Document) -> bytes:
        return qimage_png(render_document(document).scaled(
            320, 180, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def show_layer_context_menu(self, row: QListWidgetItem | None, global_position):
        self.layer_context_menu(row).exec(global_position)

    def layer_context_menu(self, row: QListWidgetItem | None) -> QMenu:
        """Menu of a panel row; right-clicking a layer applies the multiple selection rule first."""
        menu = QMenu(self)
        menu.setObjectName("canvasContextMenu")
        if row is not None and row.data(FOLDER_ROLE):
            folder_id = row.data(Qt.ItemDataRole.UserRole)
            menu.addAction("Renommer le dossier…").triggered.connect(lambda: self.rename_folder(folder_id))
            menu.addAction("Cocher les calques du dossier").triggered.connect(
                lambda: self.set_folder_checked(folder_id, True))
            menu.addAction("Dissocier le dossier").triggered.connect(lambda: self.dissolve_folder(folder_id))
            return menu
        if row is not None:
            layer_id = row.data(Qt.ItemDataRole.UserRole)
            # As in a file explorer: right-clicking outside the selection selects only that layer.
            if layer_id not in self.checked_ids:
                self.set_checked_layers([layer_id])
            self.select_layer(layer_id)
        count = len(self.checked_layer_ids())
        folder_action = menu.addAction("Créer un dossier de calques…")
        merge_action = menu.addAction("Fusionner les calques")
        delete_action = menu.addAction("Supprimer")
        template_action = menu.addAction("Créer un modèle…")
        folder_action.setEnabled(count >= 1)
        merge_action.setEnabled(count >= 2)
        delete_action.setEnabled(count >= 1)
        template_action.setEnabled(count >= 1)
        folder_action.triggered.connect(self.create_folder_from_checked)
        merge_action.triggered.connect(self.merge_checked_layers)
        delete_action.triggered.connect(self.delete_checked_layers)
        template_action.triggered.connect(self.create_template_from_checked)
        if self.checked_ids:
            menu.addSeparator()
            menu.addAction("Tout décocher").triggered.connect(lambda: self.set_checked_layers([]))
        return menu

    def drop_in_layer_list(self, kind: str, item_id: str, target: QListWidgetItem | None, upper: bool) -> bool:
        """Drop a dragged layer or folder on a row of the panel.

        On a layer row: above or below it, in its folder. On a folder row: its
        upper half places the item above the folder, its lower half inside it.
        Below the last row: at the bottom of the stack.
        """
        doc = self.document
        if target is None:
            anchor, above, folder = (doc.layers[0].id if doc.layers else None), False, None
        elif target.data(FOLDER_ROLE):
            members = doc.folder_members(target.data(Qt.ItemDataRole.UserRole))
            if not members:
                return False
            anchor, above = members[-1].id, True
            folder = None if upper else target.data(Qt.ItemDataRole.UserRole)
        else:
            anchor_layer = doc.layer(target.data(Qt.ItemDataRole.UserRole))
            if anchor_layer is None:
                return False
            anchor, above, folder = anchor_layer.id, upper, anchor_layer.folder
        if kind == "folder":
            if doc.folder(item_id) is None:
                return False
            return self._mutate_structure("Déplacer le dossier", lambda d: d.move_folder(item_id, anchor, above))
        layer = doc.layer(item_id)
        if layer is None:
            return False
        if layer.locked:
            self.statusBar().showMessage("Déverrouillez le calque avant de le déplacer", 3000)
            return False
        return self._mutate_structure("Déplacer le calque",
                                      lambda d: d.move_layer(item_id, anchor, above, folder), item_id)

    def _mutate_structure(self, description: str, fn, select_after: str | None = None) -> bool:
        """Run a stacking change only if it really changes the order or the folders (no empty history step)."""
        def structure(doc):
            return [(layer.id, layer.folder) for layer in doc.layers]

        probe = self.document.clone()
        if not fn(probe) or structure(probe) == structure(self.document):
            return False
        return self.mutate(description, fn, select_after)

    @staticmethod
    def _name_icon_buttons(root: QWidget) -> None:
        """Give screen readers a name for buttons that only show an icon or a symbol."""
        for button in root.findChildren(QAbstractButton):
            if (not button.accessibleName() and button.toolTip()
                    and not any(character.isalpha() for character in button.text())):
                button.setAccessibleName(button.toolTip())

    def update_utility_buttons(self):
        """N'affiche dans la colonne gauche que les actions actuellement possibles."""
        if not hasattr(self, "utility_buttons"):
            return
        layer = self.document.layer(self.selected_id)
        editable = bool(layer and not layer.locked)
        for key in ("duplicate", "flip_horizontal", "flip_vertical", "delete"):
            self.utility_buttons[key].setVisible(editable)
        self.utility_buttons["lock"].setVisible(layer is not None)
        if layer is not None:
            self.utility_buttons["lock"].setText(
                "▣ Déverrouiller le calque" if layer.locked
                else "▣ Verrouiller le calque"
            )

    def select_layer(self, layer_id: str | None):
        if self.refreshing:
            return
        self._flush_pending_curve()
        self.refreshing = True
        try:
            self.selected_id = layer_id if self.document.layer(layer_id) else None
            if self.selected_id:
                self.last_selected_id = self.selected_id
            for i in range(self.layer_list.count()):
                row = self.layer_list.item(i)
                if row.data(Qt.ItemDataRole.UserRole) == self.selected_id:
                    self.layer_list.setCurrentItem(row)
                    break
            else:
                self.layer_list.setCurrentRow(-1)
            scene = self.canvas.scene()
            if scene is not None:
                for item in scene.items():
                    if self.document.layer(item.data(0)):
                        item.setSelected(item.data(0) == self.selected_id)
            self._refresh_properties()
            self.update_utility_buttons()
        finally:
            self.refreshing = False
        self.canvas.viewport().update()

    def tool_target_id(self) -> str | None:
        """Calque visé par la gomme et les pots : la sélection, sinon le dernier calque choisi."""
        for candidate in (self.selected_id, self.last_selected_id):
            if candidate and self.document.layer(candidate):
                return candidate
        return None

    def _show_tool_target(self):
        """Resélectionne le dernier calque choisi quand un outil s'active sans sélection."""
        if self.selected_id is None and self.tool_target_id():
            self.select_layer(self.tool_target_id())

    def on_scene_select(self):
        if self.refreshing:
            return
        scene = self.canvas.scene()
        if scene is None:
            return
        selected = scene.selectedItems()
        if selected:
            self.select_layer(selected[0].data(0))
        else:
            self.select_layer(None)

    def on_layer_list_select(self, current, previous):
        if self.refreshing or (current is not None and current.data(FOLDER_ROLE)):
            return  # a folder row is not a layer: the current layer stays selected
        self.select_layer(current.data(Qt.ItemDataRole.UserRole) if current else None)

    def set_layer_visibility(self, layer_id: str, visible: bool):
        if self.refreshing:
            return
        layer = self.document.layer(layer_id)
        if layer and layer.visible != visible:
            self.mutate("Afficher / masquer le calque",
                        lambda doc: setattr(doc.layer(layer_id), "visible", visible), layer_id)

    def _refresh_properties(self):
        layer = self.document.layer(self.selected_id)
        is_text = bool(layer and layer.kind == "text")
        for widget in self.text_property_widgets:
            self.property_form.setRowVisible(widget, is_text)
        editable_widgets = [self.name_input, self.text_input, self.font_combo, self.font_size,
                            self.text_color_control, self.text_background_control,
                            self.text_alignment_control, self.curve_control,
                            self.character_spacing, *self.inputs.values()]
        widgets = [*editable_widgets, self.lock_btn]
        for w in widgets:
            w.setEnabled(layer is not None)
        if not layer:
            self.shape_rows.refresh(None)
            self.name_input.setText("")
            self.text_input.setPlainText("")
            self.paint_bucket_btn.setEnabled(False)
            self.paint_global_btn.setEnabled(False)
            self._schedule_right_panel_layout()
            return
        self.name_input.setText(layer.name)
        for w in editable_widgets:
            w.setEnabled(not layer.locked)
        for key, spin in self.inputs.items():
            spin.setValue(layer.opacity * 100 if key == "opacity" else getattr(layer, key))
        self.text_input.setPlainText(layer.text)
        for w in (self.text_input, self.font_combo, self.font_size,
                  self.text_color_control, self.text_background_control):
            w.setEnabled(is_text and not layer.locked)
        self.font_combo.setCurrentFont(QFont(layer.font_family))
        self.font_size.setValue(layer.font_size)
        shape = layer.text_deformation if layer.text_deformation in TEXT_SHAPES else "straight"
        self.text_shape_combo.setCurrentIndex(self.text_shape_combo.findData(shape))
        # U shapes use a magnitude only; the custom curve is driven by its handles.
        minimum = 0 if shape in ("u", "u_inverted") else -100
        self.curve_intensity.setRange(minimum, 100)
        self.curve_value.setRange(minimum, 100)
        editable_text = is_text and not layer.locked
        self.text_shape_control.setEnabled(editable_text)
        self.curve_control.setEnabled(editable_text and shape != "custom")
        self.text_controls_reset_btn.setEnabled(editable_text and shape == "custom")
        self.upright_letters.setEnabled(editable_text)
        self.upright_letters.setChecked(layer.path_orientation == "horizontal")
        self.curve_intensity.setValue(round(layer.curve_intensity))
        self.curve_value.setValue(round(layer.curve_intensity))
        self.character_spacing.setValue(layer.character_spacing)
        self.text_alignment_buttons.get(
            layer.path_alignment, self.text_alignment_buttons["center"]
        ).setChecked(True)
        muted = COLORS["muted"]
        self.color_btn.setText(layer.color.upper())
        self.text_color_swatch.setStyleSheet(
            f"background-color: {layer.color}; border: 1px solid {muted}; border-radius: 5px;"
        )
        background = layer.text_background if is_text else None
        self.text_background_btn.setText(background.upper() if background else "Transparent")
        self.text_background_swatch.setStyleSheet(
            f"background-color: {background}; border: 1px solid {muted}; border-radius: 5px;"
            if background else
            f"background-color: transparent; border: 1px dashed {muted}; border-radius: 5px;"
        )
        self.text_background_clear.setEnabled(bool(background) and not layer.locked)
        self.lock_btn.setText("Déverrouiller" if layer.locked else "Verrouiller")
        self.shape_rows.refresh(layer)
        can_paint = layer.kind == "image" and not layer.locked
        self.paint_bucket_btn.setEnabled(can_paint)
        self.paint_global_btn.setEnabled(can_paint)
        self._schedule_right_panel_layout()

    def mutate(self, description: str, fn, select_after: str | None = None) -> bool:
        before = self.document.clone()
        after = self.document.clone()
        try:
            fn(after)
            # Safety net: whatever the change, folders stay contiguous and never empty,
            # and images or masks no layer uses any more are not carried along.
            after.normalize_folders()
            after.prune_assets()
        except Exception as exc:
            self._report_failure(description, exc)
            return False
        return self._push(DocumentCommand(self, before, after, description,
                                          self.selected_id,
                                          select_after if select_after is not None else self.selected_id))

    def _push(self, command: DocumentCommand) -> bool:
        """Empile une commande ; si son application échoue, elle n'entre pas dans l'historique."""
        description = command.text()
        self._pushing_command = command
        self._push_error = None
        try:
            self.undo_stack.push(command)
        finally:
            self._pushing_command = None
        if self._push_error is not None:
            self._report_failure(description, self._push_error)
            return False
        self.statusBar().showMessage(description, 3000)
        return True

    def command_failed(self, command: DocumentCommand, exc: Exception):
        if command is self._pushing_command:
            self._push_error = exc
            # QUndoStack.push supprime une commande devenue obsolète au lieu de l'empiler.
            command.setObsolete(True)
        else:
            self._report_failure("Annuler / rétablir", exc)

    def _report_failure(self, description: str, exc: Exception):
        QMessageBox.warning(self, "Action impossible", f"{description} : {exc}")

    def commit_canvas_moves(self, before: Document, positions: dict[str, tuple[float, float]]) -> bool:
        """Record layers dragged together as one undoable step."""
        after = before.clone()
        for layer_id, (x, y) in positions.items():
            layer = after.layer(layer_id)
            if layer is not None:
                layer.x, layer.y = x, y
        return self._push(DocumentCommand(self, before, after, f"Déplacer {len(positions)} calques",
                                          self.selected_id, self.selected_id))

    def toggle_snap(self, enabled: bool):
        self.snap_enabled = bool(enabled)
        self.settings.setValue("canvas/snap", self.snap_enabled)
        self.statusBar().showMessage(
            "Magnétisme activé · maintenez Alt pour l'ignorer" if enabled else "Magnétisme désactivé", 3000)

    def commit_canvas_transform(self, before, layer_id, state, description):
        after = before.clone()
        layer = after.layer(layer_id)
        layer.x, layer.y, layer.sx, layer.sy, layer.rotation = state
        self._push(DocumentCommand(self, before, after, description, layer_id, layer_id))

    def commit_property(self, key: str):
        """Valide uniquement le champ modifié.

        Les autres champs affichent des valeurs arrondies : les réécrire
        déplacerait ou redimensionnerait le calque sans que l'utilisateur le veuille.
        """
        if key == "curve_intensity":
            self.curve_commit_timer.stop()
        if self.refreshing:
            return
        layer = self.document.layer(self.selected_id)
        if not layer or layer.locked:
            return
        if key in self.inputs:
            spin = self.inputs[key]
            current = layer.opacity * 100 if key == "opacity" else getattr(layer, key)
            if abs(spin.value() - current) <= 0.5 * 10 ** -spin.decimals() + 1e-9:
                return
            low, high = spin.minimum(), spin.maximum()
            if not low <= current <= high and spin.value() == min(high, max(low, current)):
                return  # the field only shows the clamped value: leaving it changes nothing
            value = spin.value() / 100 if key == "opacity" else spin.value()
        elif key == "name":
            value = self.name_input.text().strip()
            if not value:
                self.name_input.setText(layer.name)
                return
        elif layer.kind != "text":
            return
        elif key == "text":
            value = self.text_input.toPlainText()
        elif key == "font_family":
            value = self.font_combo.currentFont().family()
        elif key == "font_size":
            value = self.font_size.value()
        elif key == "curve_intensity":
            if self.curve_intensity.value() == round(layer.curve_intensity):
                return
            value = float(self.curve_intensity.value())
            # Bending a straight text turns it into an arc.
            shape = "arc" if layer.text_deformation == "straight" and value else layer.text_deformation
            self._set_text_shape(layer.id, shape, value, layer.path_controls, PROPERTY_LABELS[key])
            return
        elif key == "text_deformation":
            shape = self.text_shape_combo.currentData()
            if shape == layer.text_deformation:
                return
            self._set_text_shape(layer.id, shape, layer.curve_intensity, layer.path_controls,
                                 PROPERTY_LABELS[key])
            return
        elif key == "path_orientation":
            value = "horizontal" if self.upright_letters.isChecked() else "tangent"
        elif key == "character_spacing":
            if abs(self.character_spacing.value() - layer.character_spacing) <= 0.05 + 1e-9:
                return
            value = self.character_spacing.value()
        elif key == "path_alignment":
            value = self.current_text_alignment()
        else:
            return
        if getattr(layer, key) == value:
            return
        self.mutate(PROPERTY_LABELS[key], lambda doc: setattr(doc.layer(layer.id), key, value), layer.id)

    def _flush_pending_curve(self):
        if self.curve_commit_timer.isActive():
            self.commit_property("curve_intensity")

    def on_font_changed(self, font: QFont):
        if self.refreshing:
            return
        self.last_font_family = font.family()
        self.settings.setValue("text/last_font", self.last_font_family)
        self.commit_property("font_family")

    def preview_curve_intensity(self, value: int):
        self.curve_value.blockSignals(True)
        self.curve_value.setValue(value)
        self.curve_value.blockSignals(False)
        if self.refreshing:
            return
        item = self.canvas.selected_graphic()
        if hasattr(item, "set_curve_intensity"):
            item.set_curve_intensity(value)
            self.canvas.viewport().update()
        if not self.curve_intensity.isSliderDown():
            self.curve_commit_timer.start()

    def set_curve_from_value(self, value: int):
        self.curve_intensity.setValue(value)

    def reset_curve_only(self):
        self.curve_intensity.setValue(0)
        self.commit_property("curve_intensity")

    def current_text_alignment(self) -> str:
        for alignment, button in self.text_alignment_buttons.items():
            if button.isChecked():
                return alignment
        return "center"

    @staticmethod
    def _shape_values(shape: str, intensity: float, controls) -> tuple[str, float, list]:
        # U shapes only use the magnitude of the intensity.
        intensity = max(-100.0, min(100.0, float(intensity)))
        if shape in ("u", "u_inverted"):
            intensity = abs(intensity)
        return shape, intensity, normalize_controls(controls)

    def _set_text_shape(self, layer_id: str, shape: str, intensity: float, controls, description: str):
        shape, intensity, controls = self._shape_values(shape, intensity, controls)

        def apply(doc):
            target = doc.layer(layer_id)
            target.text_deformation, target.curve_intensity, target.path_controls = shape, intensity, controls

        self.mutate(description, apply, layer_id)

    def commit_text_shape(self, before: Document, layer_id: str, shape: str, intensity: float, controls):
        """Record a handle drag on the canvas as a single undoable step."""
        source = before.layer(layer_id)
        if not source:
            return
        shape, intensity, controls = self._shape_values(shape, intensity, controls)
        if (shape, controls) == (source.text_deformation, source.path_controls) \
                and abs(source.curve_intensity - intensity) < 0.01:
            return
        after = before.clone()
        target = after.layer(layer_id)
        target.text_deformation, target.curve_intensity, target.path_controls = shape, intensity, controls
        self._push(DocumentCommand(
            self, before, after, "Déformer le texte", layer_id, layer_id
        ))

    def show_text_shape(self, shape: str, intensity: float):
        """Mirror a live handle drag in the property panel without committing."""
        for widget, value in ((self.curve_intensity, round(intensity)), (self.curve_value, round(intensity))):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        index = self.text_shape_combo.findData(shape)
        if index >= 0 and index != self.text_shape_combo.currentIndex():
            self.text_shape_combo.blockSignals(True)
            self.text_shape_combo.setCurrentIndex(index)
            self.text_shape_combo.blockSignals(False)

    def reset_text_controls(self):
        layer = self.document.layer(self.selected_id)
        if layer and layer.kind == "text" and not layer.locked:
            self._set_text_shape(layer.id, "custom", layer.curve_intensity, DEFAULT_CONTROLS,
                                 "Réinitialiser la courbe du texte")

    # --- Text typed directly on the canvas -------------------------------------------

    def begin_inline_text_edit(self, layer_id: str):
        layer = self.document.layer(layer_id)
        item = self.canvas.graphic_for(layer_id)
        if not layer or layer.kind != "text" or layer.locked or item is None:
            return
        self.select_layer(layer_id)
        self._open_inline_editor(layer.text, item, layer_id, None)

    def begin_inline_text_create(self, scene_position: QPointF):
        """Text tool: preview a new text at the click and create it on validation."""
        if self.canvas.scene() is None:
            return
        layer = Layer(kind="text", name="Texte", text="Texte", font_family=resolve_font_family(self.last_font_family))
        item = CurvedTextGraphicItem(layer)
        # The click marks the start of the first baseline.
        layer.x = scene_position.x()
        layer.y = scene_position.y() - item.baseline
        item.setPos(layer.x, layer.y)
        item.setZValue(len(self.document.layers) + 1)
        self.canvas.scene().addItem(item)
        self._open_inline_editor("", item, None, layer)

    def _open_inline_editor(self, text: str, item, layer_id: str | None, new_layer: Layer | None):
        self._close_inline_editor()
        editor = InlineTextEditor(text, self.canvas.viewport())
        editor.setObjectName("inlineTextEditor")
        anchor = self.canvas.mapFromScene(item.mapToScene(item.boundingRect().bottomLeft()))
        viewport = self.canvas.viewport().rect()
        editor.resize(280, 96)
        editor.move(max(4, min(anchor.x(), viewport.width() - editor.width() - 4)),
                    max(4, min(anchor.y() + 6, viewport.height() - editor.height() - 4)))
        self._inline = {"editor": editor, "item": item, "layer_id": layer_id, "new_layer": new_layer}
        editor.textChanged.connect(lambda: self._preview_inline_text(editor.toPlainText()))
        editor.committed.connect(self._commit_inline_text)
        editor.cancelled.connect(self._cancel_inline_text)
        editor.show()
        editor.setFocus()

    def _preview_inline_text(self, text: str):
        if self._inline is None:
            return
        placeholder = "Texte" if self._inline["new_layer"] is not None else " "
        try:
            self._inline["item"].set_text_preview(text if text.strip() else placeholder)
        except RuntimeError:
            return  # the scene was rebuilt meanwhile
        self.canvas.viewport().update()

    def _close_inline_editor(self) -> dict | None:
        session, self._inline = self._inline, None
        if session is None:
            return None
        session["editor"].hide()
        session["editor"].deleteLater()
        if session["new_layer"] is not None:
            try:
                scene = session["item"].scene()
                if scene is not None:
                    scene.removeItem(session["item"])
            except RuntimeError:
                pass
        self.canvas.setFocus()
        self.canvas.viewport().update()
        return session

    def _commit_inline_text(self, text: str):
        session = self._close_inline_editor()
        if session is None or not text.strip():
            if session is not None and session["layer_id"]:
                self._restore_inline_item(session)
            return
        new_layer = session["new_layer"]
        if new_layer is not None:
            new_layer.text = text
            new_layer.name = f"Texte : {text.split(chr(10), 1)[0][:28]}"

            def add(doc):
                doc.layers.append(deepcopy(new_layer))

            if self.mutate("Ajouter un texte", add):
                self.select_layer(new_layer.id)
            return
        layer = self.document.layer(session["layer_id"])
        if layer is None or layer.text == text:
            self._restore_inline_item(session)
            return
        self.mutate("Contenu du texte", lambda doc: setattr(doc.layer(layer.id), "text", text), layer.id)

    def _cancel_inline_text(self):
        session = self._close_inline_editor()
        if session is not None and session["layer_id"]:
            self._restore_inline_item(session)

    def _restore_inline_item(self, session: dict):
        layer = self.document.layer(session["layer_id"])
        try:
            if layer is not None:
                session["item"].apply_layer(layer)
        except RuntimeError:
            pass
        self.canvas.viewport().update()

    def choose_color(self):
        old = self.document.layer(self.selected_id)
        if old and old.kind == "text":
            color = QColorDialog.getColor(QColor(old.color), self, "Couleur du texte")
            if color.isValid() and color.name().upper() != old.color.upper():
                self.mutate("Couleur du texte", lambda doc: setattr(doc.layer(old.id), "color", color.name().upper()), old.id)

    def choose_text_background(self):
        old = self.document.layer(self.selected_id)
        if not old or old.kind != "text" or old.locked:
            return
        initial = QColor(old.text_background or "#FFFFFF")
        color = QColorDialog.getColor(initial, self, "Couleur de fond du texte")
        if not color.isValid():
            return
        value = None if color.alpha() == 0 else color.name().upper()
        if value != old.text_background:
            self.mutate(
                "Couleur de fond du texte",
                lambda doc: setattr(doc.layer(old.id), "text_background", value),
                old.id,
            )

    def clear_text_background(self):
        old = self.document.layer(self.selected_id)
        if old and old.kind == "text" and not old.locked and old.text_background:
            self.mutate(
                "Fond du texte transparent",
                lambda doc: setattr(doc.layer(old.id), "text_background", None),
                old.id,
            )

    # --- Canvas tools ----------------------------------------------------------------
    # Only one tool is active at a time; every activation goes through _clear_tools.

    def any_tool_active(self) -> bool:
        return bool(self.eraser_active or self.picker_active or self.paint_mode
                    or self.text_tool_active or self.selection_tool or self.shape_tool)

    def _clear_tools(self, keep: str | None = None):
        if keep != "eraser" and self.eraser_active:
            self.canvas.cancel_eraser_preview()
            self.eraser_active = False
            self.canvas.eraser_cursor_local = None
        if keep != "picker":
            self.picker_active = False
            self.picker_text_layer_id = None
        if keep != "paint":
            self.paint_mode = None
        if keep != "text":
            self.text_tool_active = False
        if keep != "select":
            self.selection_tool = None
            self.canvas.cancel_selection_drag()
        if keep != "shape":
            self.shape_tool = None
            self.canvas.shape_drag = None

    def _sync_tool_buttons(self):
        """Reflect the tool flags on every button, then refresh options and cursor."""
        pairs = [
            (self.eraser_btn, self.eraser_active),
            (self.picker_btn, self.picker_active and self.picker_target == "tools"),
            (self.text_picker_btn, self.picker_active and self.picker_target == "text"),
            (self.text_background_picker_btn,
             self.picker_active and self.picker_target == "text_background"),
            (self.paint_bucket_btn, self.paint_mode == "contiguous"),
            (self.paint_global_btn, self.paint_mode == "global"),
            (self.text_tool_btn, self.text_tool_active),
        ]
        pairs += [(button, self.selection_tool == tool)
                  for tool, button in self.selection_tool_buttons.items()]
        pairs += [(button, self.shape_tool == kind) for kind, button in self.shape_tool_buttons.items()]
        for button, checked in pairs:
            button.blockSignals(True)
            button.setChecked(bool(checked))
            button.blockSignals(False)
        for action, checked in ((self.eraser_action, self.eraser_active),
                                (self.text_tool_action, self.text_tool_active)):
            action.blockSignals(True)
            action.setChecked(checked)
            action.blockSignals(False)
        self.update_tool_options_visibility()
        self._refresh_color_tool_cursor()
        self.canvas.viewport().update()

    def deactivate_active_tools(self):
        """Leaving the Tools tab always returns the canvas to its neutral state."""
        if not self.any_tool_active():
            return
        self._clear_tools()
        self._sync_tool_buttons()

    def activate_picker(self, target: str, active: bool):
        if not active:
            self.deactivate_picker()
            return
        if target in ("text", "text_background"):
            layer = self.document.layer(self.selected_id)
            if not layer or layer.kind != "text" or layer.locked:
                self._sync_tool_buttons()
                self.statusBar().showMessage(
                    "Sélectionnez un calque texte déverrouillé", 3000
                )
                return
        self._clear_tools("picker")
        self.picker_text_layer_id = self.selected_id if target != "tools" else None
        self.picker_target = target
        self.picker_active = True
        self._sync_tool_buttons()
        self.statusBar().showMessage("Cliquez sur un pixel d'un calque image", 3000)

    def deactivate_picker(self):
        self.picker_active = False
        self._sync_tool_buttons()

    def _refresh_color_tool_cursor(self):
        if self.eraser_active:
            cursor = Qt.CursorShape.BlankCursor
        elif self.text_tool_active:
            cursor = Qt.CursorShape.IBeamCursor
        else:
            active = self.picker_active or self.paint_mode is not None or self.selection_tool or self.shape_tool
            cursor = Qt.CursorShape.CrossCursor if active else Qt.CursorShape.ArrowCursor
        self.canvas.setCursor(cursor)

    def toggle_paint_mode(self, mode: str, active: bool):
        if active:
            self._clear_tools("paint")
            self.paint_mode = mode
            self._show_tool_target()
            self.statusBar().showMessage(
                "Cliquez dans une zone à remplir" if mode == "contiguous"
                else "Cliquez sur la couleur à remplacer dans tout le calque", 4000
            )
        elif self.paint_mode == mode:
            self.paint_mode = None
        self._sync_tool_buttons()

    def set_eraser_active(self, active: bool):
        self.canvas.cancel_eraser_preview()
        if active:
            self._clear_tools("eraser")
            self._show_tool_target()
            self.tabs.setCurrentWidget(self.tools_tab)
            self.statusBar().showMessage(
                "Gomme active · glisser pour effacer · [ et ] changent la taille", 4500
            )
        self.eraser_active = bool(active)
        self.canvas.eraser_cursor_local = None
        self._sync_tool_buttons()

    def set_text_tool_active(self, active: bool):
        if active:
            self._clear_tools("text")
            self.statusBar().showMessage(
                "Outil texte · cliquez sur le canvas pour écrire · double-clic sur un texte pour le modifier",
                5000,
            )
        self.text_tool_active = bool(active)
        self._sync_tool_buttons()

    def set_selection_tool(self, tool: str | None):
        if tool:
            self._clear_tools("select")
            self._show_tool_target()
            self.tabs.setCurrentWidget(self.tools_tab)
            self.statusBar().showMessage(
                "Maj : ajouter · Alt : soustraire · Maj+Alt : intersection", 4500
            )
        self.selection_tool = tool or None
        self._sync_tool_buttons()

    def set_shape_tool(self, kind: str | None):
        if kind:
            self._clear_tools("shape")
            self.tabs.setCurrentWidget(self.tools_tab)
            self.statusBar().showMessage(
                "Glissez sur le canvas pour tracer la forme · un clic crée une forme de taille standard · "
                "la couleur choisie ci-dessus sert de remplissage", 5000)
        self.shape_tool = kind or None
        self._sync_tool_buttons()

    def commit_shape_property(self, key: str) -> bool:
        if self.refreshing:
            return False
        return self.set_shape_property(key, self.shape_rows.value(key))

    def set_shape_property(self, key: str, value) -> bool:
        """Change one property of the selected shape as an undoable step (values are clamped)."""
        layer = self.document.layer(self.selected_id)
        if layer is None or layer.kind != "shape" or layer.locked:
            return False
        probe = deepcopy(layer)
        setattr(probe, key, value)
        if key == "stroke_color" and value and probe.stroke_width == 0:
            probe.stroke_width = 4.0  # a chosen outline colour must be visible
        probe.normalize_shape_fields()
        if probe == layer:
            return False

        def apply(doc):
            index = doc.layers.index(doc.layer(layer.id))
            doc.layers[index] = deepcopy(probe)

        return self.mutate("Modifier la forme", apply, layer.id)

    def choose_shape_color(self, key: str, title: str) -> bool:
        layer = self.document.layer(self.selected_id)
        if layer is None or layer.kind != "shape" or layer.locked:
            return False
        color = QColorDialog.getColor(QColor(getattr(layer, key) or "#FFFFFF"), self, title)
        return color.isValid() and self.set_shape_property(key, color.name().upper())

    def create_shape(self, start: QPointF, end: QPointF, modifiers) -> bool:
        """Add the shape drawn with the active shape tool, as an editable layer."""
        if not self.shape_tool:
            return False
        layer = shape_from_drag(self.shape_tool, (start.x(), start.y()), (end.x(), end.y()),
                                bool(modifiers & Qt.KeyboardModifier.ShiftModifier), self.replacement_color)

        def add(doc):
            doc.layers.append(deepcopy(layer))

        if not self.mutate(f"Ajouter : {layer.name}", add, layer.id):
            return False
        self.select_layer(layer.id)
        return True

    def update_tool_options_visibility(self):
        """Only show the settings of the active tool."""
        eraser = self.eraser_active
        bucket = self.paint_mode is not None and not eraser
        self.eraser_settings.setVisible(eraser)
        self.paint_settings.setVisible(bucket)
        self.selection_settings.setVisible(bool(self.selection_tool))
        self.wand_settings.setVisible(self.selection_tool == "wand")
        for widget in (
            self.color_tools_label, self.color_editor,
            self.alternative_label, self.variations_widget,
        ):
            widget.setVisible(not eraser and not self.selection_tool)
        self._schedule_right_panel_layout()

    # --- Selections ---------------------------------------------------------------------
    # The selection is a document-sized mask, outside the Document: it is not
    # saved in projects, but every change is an undoable SelectionCommand.

    def _combine_mode(self, modifiers) -> str:
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        if shift and alt:
            return "intersect"
        if shift:
            return "add"
        if alt:
            return "subtract"
        return self.selection_mode_combo.currentData()

    def _install_selection(self, data: bytes | None):
        self.selection_mask = selection.decode(data) if data else None
        self._refresh_selection_visual()

    def _refresh_selection_visual(self):
        self.canvas.update_selection_visual(self.selection_mask, self.show_selection_mask.isChecked())
        self._update_selection_actions()

    def _update_selection_actions(self):
        has_selection = self.selection_mask is not None
        for action in getattr(self, "selection_actions", ()):
            action.setEnabled(has_selection)
        self.separate_selection_btn.setEnabled(has_selection)

    def set_selection(self, mask, description: str):
        if mask is not None and selection.is_empty(mask):
            mask = None
        before = selection.encode(self.selection_mask) if self.selection_mask is not None else None
        after = selection.encode(mask) if mask is not None else None
        if before != after:
            self.undo_stack.push(SelectionCommand(self, before, after, description))

    def _finish_shape(self, shape):
        if self.selection_pixel_perfect.isChecked():
            return shape
        return selection.feather(shape, self.selection_feather.value())

    def apply_selection_shape(self, tool: str, rect: QRectF, modifiers):
        mode = self._combine_mode(modifiers)
        if rect.width() < 1 and rect.height() < 1:
            # A simple click with a new selection clears it, as in most editors.
            if mode == "replace":
                self.deselect()
            return
        size = (self.document.width, self.document.height)
        box = (rect.left(), rect.top(), rect.right(), rect.bottom())
        antialias = not self.selection_pixel_perfect.isChecked()
        draw = selection.ellipse if tool == "ellipse" else selection.rectangle
        shape = self._finish_shape(draw(size, box, antialias))
        label = "Sélection elliptique" if tool == "ellipse" else "Sélection rectangulaire"
        self.set_selection(selection.combine(self.selection_mask, shape, mode), label)

    def apply_selection_polygon(self, points, modifiers) -> bool:
        """Selection from a closed lasso outline (document coordinates)."""
        mode = self._combine_mode(modifiers)
        size = (self.document.width, self.document.height)
        antialias = not self.selection_pixel_perfect.isChecked()
        shape = selection.polygon(size, points, antialias)
        if selection.is_empty(shape):
            if mode == "replace" and len(points) < 3:
                self.deselect()  # a click without an outline clears, as with the other tools
            self.statusBar().showMessage("Contour trop petit : aucune sélection", 2500)
            return False
        self.set_selection(selection.combine(self.selection_mask, self._finish_shape(shape), mode), "Lasso")
        return True

    def apply_magic_wand(self, scene_position: QPointF, modifiers):
        x, y = int(scene_position.x() // 1), int(scene_position.y() // 1)
        if not (0 <= x < self.document.width and 0 <= y < self.document.height):
            self.statusBar().showMessage("Cliquez à l'intérieur du document", 3000)
            return
        if self.wand_all_layers.isChecked():
            image = render_layers(self.document, None, with_background=True)
        else:
            layer_id = self.tool_target_id()
            if layer_id is None:
                self.statusBar().showMessage("Sélectionnez le calque à analyser", 3000)
                return
            image = render_layers(self.document, [layer_id])
        wand = selection.magic_wand(image, (x, y), self.wand_tolerance.value(),
                                    self.wand_contiguous.isChecked())
        mode = self._combine_mode(modifiers)
        self.set_selection(selection.combine(self.selection_mask, self._finish_shape(wand), mode),
                           "Baguette magique")

    def select_all(self):
        self.set_selection(selection.full((self.document.width, self.document.height)), "Tout sélectionner")

    def deselect(self):
        self.set_selection(None, "Désélectionner")

    def invert_selection(self):
        size = (self.document.width, self.document.height)
        current = self.selection_mask if self.selection_mask is not None else selection.empty(size)
        self.set_selection(selection.invert(current), "Inverser la sélection")

    def _reset_selection(self):
        """New or opened document: start without selection (not an undoable step)."""
        self.selection_mask = None
        self._refresh_selection_visual()

    def _selection_layer(self, editable: bool):
        """Layer the selection acts on; pixel edits need an unlocked image layer."""
        layer = self.document.layer(self.tool_target_id())
        if self.selection_mask is None:
            self.statusBar().showMessage("Aucune sélection active", 3000)
            return None
        if layer is None:
            self.statusBar().showMessage("Sélectionnez un calque", 3000)
            return None
        if editable and layer.kind != "image":
            self.statusBar().showMessage(
                "Un calque texte reste vectoriel : copiez la sélection vers un nouveau calque", 4000
            )
            return None
        if editable and layer.locked:
            self.statusBar().showMessage("Déverrouillez le calque pour le modifier", 3000)
            return None
        return layer

    def selected_pixels(self, layer) -> tuple[Image.Image, tuple[int, int]] | None:
        """Visible pixels of a layer inside the selection, cropped, with their position."""
        rendered = render_layers(self.document, [layer.id])
        cut = selection.apply_alpha(rendered, self.selection_mask)
        box = cut.getchannel("A").getbbox()
        if box is None:
            self.statusBar().showMessage("Aucun pixel visible dans la sélection", 3000)
            return None
        return cut.crop(box), box[:2]

    def _source_size(self, layer) -> tuple[int, int]:
        with Image.open(BytesIO(self.document.assets[layer.asset]), formats=ASSET_FORMATS) as source:
            return source.size

    def _edit_layer_mask(self, doc: Document, layer_id: str, operation: str, area=None):
        """Change a layer mask inside a mutation: hide, reveal or follow ``area``."""
        layer = doc.layer(layer_id)
        if area is None:
            area = document_mask_to_layer(self.selection_mask, layer, self._source_size(layer),
                                          smooth=not self.selection_pixel_perfect.isChecked())
        current = selection.decode(doc.assets[layer.mask]) if layer.mask else None
        updated = (selection.hide if operation == "hide" else selection.reveal)(current, area)
        if updated.getextrema() == (255, 255):
            layer.mask = None  # fully visible: no mask needed
            return
        layer.mask = new_id()
        doc.assets[layer.mask] = selection.encode(updated)

    def clear_selection_content(self):
        layer = self._selection_layer(editable=True)
        if layer is not None:
            self.mutate("Effacer la sélection",
                        lambda doc: self._edit_layer_mask(doc, layer.id, "hide"), layer.id)

    def reveal_selection_in_mask(self):
        layer = self._selection_layer(editable=True)
        if layer is None:
            return
        if not layer.mask:
            self.statusBar().showMessage("Ce calque n'a pas de masque", 3000)
            return
        self.mutate("Révéler la sélection",
                    lambda doc: self._edit_layer_mask(doc, layer.id, "reveal"), layer.id)

    def remove_layer_mask(self):
        layer = self.document.layer(self.tool_target_id())
        if layer is None or not layer.mask or layer.locked:
            self.statusBar().showMessage("Aucun masque modifiable sur ce calque", 3000)
            return
        self.mutate("Supprimer le masque du calque",
                    lambda doc: setattr(doc.layer(layer.id), "mask", None), layer.id)

    def copy_selection(self) -> bool:
        layer = self._selection_layer(editable=False)
        pixels = self.selected_pixels(layer) if layer is not None else None
        if pixels is None:
            return False
        image, origin = pixels
        self._setting_clipboard = True
        QApplication.clipboard().setImage(pil_to_qimage(image))
        self._setting_clipboard = False
        # Pasting our own copy puts it back where it came from.
        self._clipboard_origin = (origin, image.size)
        self.statusBar().showMessage("Sélection copiée", 3000)
        return True

    def cut_selection(self) -> bool:
        if self._selection_layer(editable=True) is None or not self.copy_selection():
            return False
        self.clear_selection_content()
        return True

    def _on_clipboard_changed(self):
        if not self._setting_clipboard:
            self._clipboard_origin = None

    def selection_to_new_layer(self, cut: bool = False, offset: tuple[int, int] = (0, 0)) -> bool:
        layer = self._selection_layer(editable=cut)
        pixels = self.selected_pixels(layer) if layer is not None else None
        if pixels is None:
            return False
        image, (left, top) = pixels
        output = BytesIO()
        image.save(output, format="PNG")
        data, holder = output.getvalue(), {}

        def apply(doc):
            if cut:
                self._edit_layer_mask(doc, layer.id, "hide")
            new = doc.add_image_bytes(data, f"{layer.name} (sélection)", center=False)
            new.x, new.y = float(left + offset[0]), float(top + offset[1])
            doc.layers.remove(new)
            doc.layers.insert(doc.layers.index(doc.layer(layer.id)) + 1, new)
            new.folder = doc.layer(layer.id).folder  # stays next to its source, in its folder
            holder["id"] = new.id

        label = "Couper vers un nouveau calque" if cut else "Copier vers un nouveau calque"
        if not self.mutate(label, apply, layer.id):
            return False
        self.select_layer(holder["id"])
        return True

    def lift_selection(self, scene_position: QPointF):
        """Start a Ctrl+drag move: the selected pixels follow the mouse."""
        if self.selection_mask is None:
            return None
        x, y = int(scene_position.x() // 1), int(scene_position.y() // 1)
        width, height = self.selection_mask.size
        if not (0 <= x < width and 0 <= y < height) or self.selection_mask.getpixel((x, y)) == 0:
            return None
        layer = self._selection_layer(editable=True)
        pixels = self.selected_pixels(layer) if layer is not None else None
        if pixels is None:
            return None
        image, origin = pixels
        return {"pixmap": QPixmap.fromImage(pil_to_qimage(image)), "origin": QPointF(*origin)}

    def move_selection_content(self, dx: int, dy: int):
        """Move the selected pixels to a new layer, and the selection with them."""
        if dx == 0 and dy == 0 or self.selection_mask is None:
            return
        layer = self._selection_layer(editable=True)
        if layer is None or self.selected_pixels(layer) is None:
            return  # nothing to move: no empty step in the history
        moved = selection.translate(self.selection_mask, dx, dy)
        self.undo_stack.beginMacro("Déplacer la sélection")
        try:
            if self.selection_to_new_layer(cut=True, offset=(dx, dy)):
                self.set_selection(moved, "Déplacer la sélection")
        finally:
            self.undo_stack.endMacro()

    def remove_background(self):
        """Preview then apply a local background removal on the target image layer."""
        layer = self.document.layer(self.tool_target_id())
        if layer is None or layer.kind != "image":
            self.statusBar().showMessage("Sélectionnez un calque image à détourer", 3000)
            return
        if layer.locked:
            self.statusBar().showMessage("Déverrouillez le calque pour le détourer", 3000)
            return
        # Source pixels with their non-destructive edits, but without the current mask.
        image = render_layer_image(self.document.assets[layer.asset], layer.color_replacements,
                                   layer.color_fills, layer.eraser_strokes, cache_key=layer.asset)
        dialog = BackgroundRemovalDialog(image, layer.name, bool(layer.mask), self.models_dir, self)
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            mask = dialog.result_mask() if accepted else None
            keep_existing, as_mask = dialog.keep_existing.isChecked(), dialog.as_mask.isChecked()
        finally:
            dialog.dispose()
        if mask is None:
            return
        if keep_existing and layer.mask:
            current = selection.decode(self.document.assets[layer.mask])
            if current.size != mask.size:
                current = current.resize(mask.size, Image.Resampling.NEAREST)
            mask = selection.combine(current, mask, "intersect")
        if as_mask:
            def apply_mask(doc):
                target = doc.layer(layer.id)
                target.mask = new_id()
                doc.assets[target.mask] = selection.encode(mask)

            self.mutate("Supprimer l'arrière-plan", apply_mask, layer.id)
            return
        output = BytesIO()
        selection.apply_alpha(image, mask).save(output, format="PNG")
        data, holder = output.getvalue(), {}

        def add_layer(doc):
            source = doc.layer(layer.id)
            new = doc.add_image_bytes(data, f"{source.name} (détouré)", center=False)
            for key in ("x", "y", "sx", "sy", "rotation", "opacity", "flip_horizontal", "flip_vertical"):
                setattr(new, key, getattr(source, key))
            doc.layers.remove(new)
            doc.layers.insert(doc.layers.index(source) + 1, new)
            new.folder = source.folder
            source.visible = False
            holder["id"] = new.id

        if self.mutate("Supprimer l'arrière-plan (nouveau calque)", add_layer, layer.id):
            self.select_layer(holder["id"])

    def trim_layer_margins(self, layer_id: str | None = None) -> bool:
        """Crop an image layer to its visible pixels without moving them on the canvas."""
        layer = self.document.layer(layer_id or self.tool_target_id())
        if layer is None or layer.kind != "image":
            self.statusBar().showMessage("Sélectionnez un calque image à rogner", 3000)
            return False
        if layer.locked:
            self.statusBar().showMessage("Déverrouillez le calque pour le rogner", 3000)
            return False
        rendered = render_layer_with_mask(layer, self.document)
        box = alpha_bounds(rendered)
        if box is None:
            self.statusBar().showMessage("Le calque est entièrement transparent : rien à rogner", 3500)
            return False
        if box == (0, 0, *rendered.size):
            self.statusBar().showMessage("Ce calque n'a pas de marge transparente", 3000)
            return False
        try:
            trimmed, assets = crop_image_layer(layer, self.document, box)
        except ValueError as exc:
            self._report_failure("Rogner les marges transparentes", exc)
            return False

        def apply(doc):
            doc.assets.update(assets)
            doc.layers[doc.layers.index(doc.layer(layer.id))] = deepcopy(trimmed)

        return self.mutate("Rogner les marges transparentes", apply, layer.id)

    def crop_document_to_content(self) -> bool:
        """Shrink the document to the visible pixels of its layers; the layers keep their look."""
        box = alpha_bounds(render_layers(self.document))
        if box is None:
            self.statusBar().showMessage("Le document ne contient aucun pixel visible", 3500)
            return False
        left, top, right, bottom = box
        if box == (0, 0, self.document.width, self.document.height):
            self.statusBar().showMessage("Le document n'a pas de marge transparente", 3000)
            return False

        def apply(doc):
            doc.width, doc.height = right - left, bottom - top
            for layer in doc.layers:
                layer.x -= left
                layer.y -= top

        # The selection is tied to the old frame: it is cleared in the same undo step.
        self.undo_stack.beginMacro("Recadrer le document sur son contenu")
        try:
            self.deselect()
            done = self.mutate("Recadrer le document sur son contenu", apply, self.selected_id)
        finally:
            self.undo_stack.endMacro()
        if done:
            self.canvas.fit_document()
        return done

    def delete_selection_or_layer(self) -> bool:
        """Delete key: the selected pixels, else the checked layers, else the current layer.

        A text field or spin box being edited keeps the key for itself.
        """
        if self._focus_edits_text():
            return False
        if self.selection_mask is not None:
            self.clear_selection_content()
            return True
        if self.checked_layer_ids():
            return self.delete_checked_layers()
        self.delete_layer()
        return True

    @staticmethod
    def _focus_edits_text() -> bool:
        focused = QApplication.focusWidget()
        if isinstance(focused, QComboBox):
            return focused.isEditable()
        return isinstance(focused, (QLineEdit, QPlainTextEdit, QAbstractSpinBox))

    def update_eraser_size_preset(self, _index=None):
        size = self.eraser_size_preset.currentData()
        custom = size is None
        self.eraser_size.setEnabled(custom)
        if not custom:
            self.eraser_size.setValue(size)
        self.canvas.viewport().update()

    def update_eraser_mode_controls(self, pixel_art: bool):
        self.eraser_hardness.setEnabled(not pixel_art)
        if not pixel_art:
            circle_index = self.eraser_shape.findData("circle")
            self.eraser_shape.setCurrentIndex(circle_index)
        self.eraser_shape.setEnabled(pixel_art)
        self.canvas.viewport().update()

    def adjust_eraser_size(self, direction: int):
        presets = [1, 2, 4, 8, 16, 32]
        current = self.eraser_size.value()
        if current in presets:
            index = max(0, min(len(presets) - 1, presets.index(current) + direction))
            value = presets[index]
            self.eraser_size_preset.setCurrentIndex(index)
        else:
            value = max(1, min(2048, current + direction))
            self.eraser_size_preset.setCurrentIndex(self.eraser_size_preset.count() - 1)
            self.eraser_size.setValue(value)
        self.statusBar().showMessage(f"Taille de gomme : {value} px", 1800)
        self.canvas.viewport().update()

    def commit_eraser_stroke(self, layer_id: str, points: list[QPointF]):
        layer = self.document.layer(layer_id)
        item = self.canvas.graphic_for(layer_id)
        if not layer or layer.kind != "image" or layer.locked or not isinstance(item, QGraphicsPixmapItem):
            self.statusBar().showMessage("Trait de gomme ignoré : calque non modifiable", 3000)
            return
        width, height = item.pixmap().width(), item.pixmap().height()
        source_points = []
        for point in points:
            # Mirror of a position (not of a pixel index) in a flipped layer.
            x = width - point.x() if layer.flip_horizontal else point.x()
            y = height - point.y() if layer.flip_vertical else point.y()
            source_points.append([x, y])
        stroke = {
            "points": source_points,
            "size": self.eraser_size.value(),
            "shape": self.eraser_shape.currentData(),
            "pixel_art": self.eraser_pixel_art.isChecked(),
            "hardness": self.eraser_hardness.value(),
            "opacity": self.eraser_opacity.value(),
            "pixel_centered": True,
        }
        self.mutate(
            "Trait de gomme",
            lambda doc: doc.layer(layer_id).eraser_strokes.append(stroke),
            layer_id,
        )

    def sample_canvas_color(self, item, scene_position) -> bool:
        layer = self.document.layer(item.data(0)) if item is not None else None
        if not layer or layer.kind != "image" or not isinstance(item, QGraphicsPixmapItem):
            self.statusBar().showMessage("La pipette fonctionne sur les calques image", 3000)
            return False
        local = item.mapFromScene(scene_position)
        x, y = int(local.x()), int(local.y())
        image = item.pixmap().toImage()
        if not (0 <= x < image.width() and 0 <= y < image.height()):
            return False
        color = image.pixelColor(x, y)
        if color.alpha() == 0:
            self.statusBar().showMessage("Ce pixel est transparent", 3000)
            return False
        return self.apply_picked_color(color.name().upper(), self.picker_target, self.picker_text_layer_id)

    def apply_picked_color(self, sampled: str, target: str, text_layer_id: str | None) -> bool:
        """Give a picked colour to its tool: the tools colour, or a text colour (undoable)."""
        if target in ("text", "text_background"):
            text_layer = self.document.layer(text_layer_id)
            if not text_layer or text_layer.kind != "text" or text_layer.locked:
                self.deactivate_picker()
                self.statusBar().showMessage("Le calque texte n'est plus modifiable", 3000)
                return False
            attribute = "text_background" if target == "text_background" else "color"
            description = "Couleur de fond du texte" if attribute == "text_background" else "Couleur du texte"
            self.mutate(
                description,
                lambda doc: setattr(doc.layer(text_layer.id), attribute, sampled),
                text_layer.id,
            )
        else:
            # La couleur prélevée devient la couleur de remplissage ; la sélection
            # reste sur le calque que les outils doivent continuer de viser.
            self.set_current_color(sampled)
        self.deactivate_picker()
        self.statusBar().showMessage(f"Couleur prélevée : {sampled}", 4000)
        return True

    def start_screen_picker(self) -> bool:
        """Pick a colour anywhere on the desktop, for the active picker target (tools colour by default)."""
        if self._screen_picker is not None and self._screen_picker.active:
            return False
        target = self.picker_target if self.picker_active else "tools"
        text_layer_id = self.picker_text_layer_id if self.picker_active else None
        picker = ScreenColorPicker(self)
        picker.picked.connect(lambda color: self._screen_pick_done(color, target, text_layer_id))
        picker.cancelled.connect(lambda: self._screen_pick_done(None, target, text_layer_id))
        picker.failed.connect(lambda message: QMessageBox.warning(self, "Pipette écran", message))
        self._screen_picker = picker
        if not picker.start():
            self._screen_picker = None
            return False
        self.statusBar().showMessage(
            "Pipette écran : survolez n'importe quelle application et cliquez · Échap ou clic droit pour annuler")
        return True

    def _screen_pick_done(self, color: str | None, target: str, text_layer_id: str | None):
        self._screen_picker = None
        if color is None:
            self.statusBar().showMessage("Pipette écran annulée", 2500)
            return
        self.apply_picked_color(color, target, text_layer_id)

    def paint_canvas_color(self, scene_position) -> bool:
        layer_id = self.tool_target_id()
        layer = self.document.layer(layer_id)
        item = self.canvas.graphic_for(layer_id)
        if not layer or layer.kind != "image" or not isinstance(item, QGraphicsPixmapItem):
            self.statusBar().showMessage("Le pot nécessite un calque image sélectionné", 3000)
            return False
        if layer.locked:
            self.statusBar().showMessage("Déverrouillez le calque pour le modifier", 3000)
            return False
        local = item.mapFromScene(scene_position)
        x, y = int(local.x()), int(local.y())
        image = item.pixmap().toImage()
        if not (0 <= x < image.width() and 0 <= y < image.height()):
            self.statusBar().showMessage("Cliquez sur le calque sélectionné", 3000)
            return False
        color = image.pixelColor(x, y)
        if color.alpha() == 0:
            self.statusBar().showMessage("Ce pixel est transparent", 3000)
            return False
        # La zone à remplacer est toujours celle de la couleur cliquée ; la couleur
        # courante de l'onglet Outils (pipette, HEX, palette) est la couleur cible.
        source = color.name().upper()
        target = self.replacement_color.upper()
        if source == target:
            self.statusBar().showMessage("La couleur choisie est déjà appliquée", 3000)
            return False
        seed_x = image.width() - 1 - x if layer.flip_horizontal else x
        seed_y = image.height() - 1 - y if layer.flip_vertical else y
        fill = {
            "mode": self.paint_mode,
            "source": source,
            "target": target,
            "x": seed_x,
            "y": seed_y,
            "tolerance": self.paint_tolerance.value(),
            "preserve_shading": self.preserve_shading.isChecked(),
            "after_strokes": len(layer.eraser_strokes),
        }
        description = (
            "Recoloriser une zone" if self.preserve_shading.isChecked()
            else "Remplir une zone"
        ) if self.paint_mode == "contiguous" else (
            "Recoloriser le calque" if self.preserve_shading.isChecked()
            else "Remplacer une couleur sur le calque"
        )
        return self.mutate(
            description,
            lambda doc: doc.layer(layer.id).color_fills.append(fill),
            layer.id,
        )

    def set_current_color(self, color: str, skip_field: str | None = None):
        selected = QColor(color)
        if not selected.isValid():
            return
        self.replacement_color = selected.name().upper()
        self.color_preview.setStyleSheet(
            f"background-color: {self.replacement_color}; border: 1px solid {COLORS['muted']}; border-radius: 6px;"
        )
        hue = selected.hslHue() if selected.hslHue() >= 0 else 0
        saturation = round(selected.hslSaturationF() * 100)
        lightness = round(selected.lightnessF() * 100)
        values = {
            "hex": self.replacement_color,
            "rgb": f"{selected.red()}, {selected.green()}, {selected.blue()}",
            "hsl": f"{hue}, {saturation} %, {lightness} %",
        }
        fields = {
            "hex": self.sampled_color_input,
            "rgb": self.sampled_rgb_input,
            "hsl": self.sampled_hsl_input,
        }
        self._updating_color_fields = True
        for name, field in fields.items():
            if name != skip_field:
                field.setText(values[name])
        self._updating_color_fields = False
        self.refresh_color_variations(selected)

    def update_color_from_hex(self, value: str):
        if self._updating_color_fields:
            return
        value = value.strip()
        if len(value) == 7 and value.startswith("#") and QColor(value).isValid():
            self.set_current_color(value, "hex")

    def update_color_from_rgb(self, value: str):
        if self._updating_color_fields:
            return
        try:
            parts = [int(part.strip()) for part in value.replace("RGB", "").replace("(", "").replace(")", "").split(",")]
        except ValueError:
            return
        if len(parts) == 3 and all(0 <= part <= 255 for part in parts):
            self.set_current_color(QColor(*parts).name(), "rgb")

    def update_color_from_hsl(self, value: str):
        if self._updating_color_fields:
            return
        cleaned = value.replace("HSL", "").replace("°", "").replace("%", "").replace("(", "").replace(")", "")
        try:
            hue, saturation, lightness = [float(part.strip()) for part in cleaned.split(",")]
        except (ValueError, TypeError):
            return
        if 0 <= hue <= 360 and 0 <= saturation <= 100 and 0 <= lightness <= 100:
            color = QColor.fromHslF((hue % 360) / 360, saturation / 100, lightness / 100)
            self.set_current_color(color.name(), "hsl")

    def refresh_color_variations(self, color: QColor):
        hue = color.hslHueF() if color.hslHueF() >= 0 else 0.0
        saturation = color.hslSaturationF()
        base_lightness = color.lightnessF()
        self.variation_colors = []
        for index, button in enumerate(self.variation_buttons):
            delta = (index - 4) * 0.10
            variation = QColor.fromHslF(hue, saturation, max(0.0, min(1.0, base_lightness + delta)))
            value = variation.name().upper()
            self.variation_colors.append(value)
            button.setToolTip(f"{delta * 100:+.0f} % · {value}")
            button.setStyleSheet(
                f"background: {value}; border: 1px solid {COLORS['muted']}; border-radius: 5px; padding: 0;"
            )

    def choose_variation(self, index: int):
        if 0 <= index < len(self.variation_colors):
            self.set_current_color(self.variation_colors[index])

    def choose_replacement_color(self):
        color = QColorDialog.getColor(QColor(self.replacement_color), self, "Couleur de remplacement")
        if color.isValid():
            self.set_current_color(color.name())

    def toggle_lock(self, layer_id: str | None = None):
        layer = self.document.layer(layer_id or self.selected_id)
        if layer:
            description = "Déverrouiller le calque" if layer.locked else "Verrouiller le calque"
            self.mutate(description, lambda doc: setattr(doc.layer(layer.id), "locked", not layer.locked), layer.id)

    def selected_image_item(self):
        scene = self.canvas.scene()
        if scene is None:
            return None
        return next((item for item in scene.items()
                     if item.data(0) == self.selected_id and isinstance(item, QGraphicsPixmapItem)), None)

    def copy_layer(self) -> bool:
        focused = QApplication.focusWidget()
        if isinstance(focused, QLineEdit) and focused.hasSelectedText():
            focused.copy()
            return True
        if isinstance(focused, QPlainTextEdit) and focused.textCursor().hasSelection():
            focused.copy()
            return True
        if self.selection_mask is not None:
            return self.copy_selection()
        layer = self.document.layer(self.selected_id)
        item = self.selected_image_item()
        if not layer or layer.kind != "image" or item is None:
            self.statusBar().showMessage("Sélectionnez un calque image à copier", 3000)
            return False
        QApplication.clipboard().setImage(item.pixmap().toImage())
        self.statusBar().showMessage(f"Calque copié : {layer.name}", 3000)
        return True

    def cut_layer(self) -> bool:
        focused = QApplication.focusWidget()
        if isinstance(focused, QLineEdit) and focused.hasSelectedText() and not focused.isReadOnly():
            focused.cut()
            return True
        if isinstance(focused, QPlainTextEdit) and focused.textCursor().hasSelection() and not focused.isReadOnly():
            focused.cut()
            return True
        if self.selection_mask is not None:
            return self.cut_selection()
        layer = self.document.layer(self.selected_id)
        if not layer:
            self.statusBar().showMessage("Sélectionnez un calque image à couper", 3000)
            return False
        if layer.locked:
            self.statusBar().showMessage("Déverrouillez le calque avant de le couper", 3000)
            return False
        if self.copy_layer():
            self.delete_layer()
            return True
        return False

    def paste_image(self) -> bool:
        clipboard = QApplication.clipboard()
        image: QImage = clipboard.image()
        if image.isNull():
            focused = QApplication.focusWidget()
            if isinstance(focused, QLineEdit) and clipboard.mimeData().hasText() and not focused.isReadOnly():
                focused.paste()
                return True
            if isinstance(focused, QPlainTextEdit) and clipboard.mimeData().hasText() and not focused.isReadOnly():
                focused.paste()
                return True
            self.statusBar().showMessage("Le presse-papiers ne contient pas d'image", 3000)
            return False
        data = qimage_png(image)
        holder = {}
        origin = None
        if self._clipboard_origin and self._clipboard_origin[1] == (image.width(), image.height()):
            origin = self._clipboard_origin[0]

        def add(doc):
            layer = doc.add_image_bytes(data, "Image collée", center=origin is None)
            if origin is not None:
                layer.x, layer.y = float(origin[0]), float(origin[1])
            holder["id"] = layer.id

        if not self.mutate("Coller une image", add):
            return False
        self.select_layer(holder["id"])
        self.tabs.setCurrentIndex(0)
        return True

    def flip_layer_horizontal(self):
        self._flip_selected_layer("flip_horizontal", "Retourner horizontalement")

    def flip_layer_vertical(self):
        self._flip_selected_layer("flip_vertical", "Retourner verticalement")

    def _flip_selected_layer(self, attribute: str, description: str):
        layer = self.document.layer(self.selected_id)
        if not layer:
            self.statusBar().showMessage("Sélectionnez un calque", 3000)
            return
        if layer.locked:
            self.statusBar().showMessage("Déverrouillez le calque avant de le retourner", 3000)
            return
        self.mutate(description,
                    lambda doc: setattr(doc.layer(layer.id), attribute,
                                        not getattr(doc.layer(layer.id), attribute)), layer.id)

    def show_canvas_context_menu(self, global_position):
        layer = self.document.layer(self.selected_id)
        is_image = bool(layer and layer.kind == "image")
        editable_image = bool(is_image and not layer.locked)
        editable_layer = bool(layer and not layer.locked)
        menu = QMenu(self)
        menu.setObjectName("canvasContextMenu")
        copy_action = menu.addAction("Copier\tCtrl+C")
        cut_action = menu.addAction("Couper\tCtrl+X")
        paste_action = menu.addAction("Coller\tCtrl+V")
        copy_action.setEnabled(is_image)
        cut_action.setEnabled(editable_image)
        paste_action.setEnabled(not QApplication.clipboard().image().isNull())
        copy_action.triggered.connect(self.copy_layer)
        cut_action.triggered.connect(self.cut_layer)
        paste_action.triggered.connect(self.paste_image)
        duplicate_action = menu.addAction("Dupliquer\tCtrl+D")
        duplicate_action.setEnabled(bool(layer and not layer.locked))
        duplicate_action.triggered.connect(self.duplicate_layer)
        menu.addSeparator()
        lock_action = menu.addAction("Déverrouiller" if layer and layer.locked else "Verrouiller")
        lock_action.setEnabled(layer is not None)
        lock_action.triggered.connect(self.toggle_lock)
        horizontal = menu.addAction("Retourner horizontalement")
        vertical = menu.addAction("Retourner verticalement")
        horizontal.setEnabled(editable_layer)
        vertical.setEnabled(editable_layer)
        horizontal.triggered.connect(self.flip_layer_horizontal)
        vertical.triggered.connect(self.flip_layer_vertical)
        if self.selection_mask is not None:
            menu.addSeparator()
            menu.addAction("Copier vers un nouveau calque	Ctrl+J").triggered.connect(
                lambda: self.selection_to_new_layer(False))
            menu.addAction("Couper vers un nouveau calque	Ctrl+Maj+J").triggered.connect(
                lambda: self.selection_to_new_layer(True))
            menu.addAction("Effacer le contenu sélectionné	Suppr").triggered.connect(
                self.clear_selection_content)
            menu.addAction("Désélectionner	Ctrl+Maj+A").triggered.connect(self.deselect)
        menu.addSeparator()
        background_action = menu.addAction("Supprimer l'arrière-plan…")
        background_action.setEnabled(editable_image)
        background_action.triggered.connect(self.remove_background)
        trim_action = menu.addAction("Rogner les marges transparentes")
        trim_action.setEnabled(editable_image)
        trim_action.triggered.connect(lambda: self.trim_layer_margins())
        save_layer_action = menu.addAction("Enregistrer le calque sous…")
        save_layer_action.setEnabled(is_image)
        save_layer_action.triggered.connect(self.export_selected_layer)
        menu.addSeparator()
        delete_action = menu.addAction("Supprimer")
        delete_action.setEnabled(bool(layer and not layer.locked))
        delete_action.triggered.connect(self.delete_layer)
        menu.exec(global_position)

    def add_images(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Importer des images", self.initial_path("import"),
                     "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;Tous les fichiers (*)")
        if paths:
            self.remember_directory("import", Path(paths[0]).parent)
        self._import_paths(paths)

    def _import_paths(self, paths):
        for raw_path in paths or []:
            path = Path(raw_path)
            try:
                data = path.read_bytes()
            except OSError as exc:
                QMessageBox.warning(self, "Import impossible", f"{raw_path}\n{exc}")
                continue
            holder = {}

            def add(doc, data=data, name=path.stem, holder=holder):
                holder["id"] = doc.add_image_bytes(data, name).id

            # Un fichier illisible ou trop grand est signalé par mutate et
            # n'ajoute aucune étape à l'historique.
            if self.mutate(f"Importer {path.stem}", add):
                self.select_layer(holder["id"])

    def add_text(self):
        content, ok = QInputDialog.getText(self, "Nouveau calque texte", "Votre texte :")
        if not ok or not content.strip():
            return
        holder = {}
        def add(doc):
            layer = doc.add_text(content)
            layer.font_family = resolve_font_family(self.last_font_family)
            holder['id'] = layer.id
        if self.mutate("Ajouter un texte", add):
            self.select_layer(holder['id'])
            self.tabs.setCurrentIndex(0)

    def delete_layer(self):
        layer = self.document.layer(self.selected_id)
        if layer and not layer.locked:
            if self.mutate("Supprimer le calque", lambda doc: doc.layers.remove(doc.layer(layer.id))):
                self.select_layer(None)
        elif layer:
            self.statusBar().showMessage("Déverrouillez le calque avant de le supprimer", 3000)

    def duplicate_layer(self):
        layer = self.document.layer(self.selected_id)
        if layer and not layer.locked:
            result = {}
            if self.mutate("Dupliquer le calque", lambda doc: result.update(id=doc.duplicate_layer(layer.id).id)):
                self.select_layer(result['id'])
        elif layer:
            self.statusBar().showMessage("Déverrouillez le calque avant de le dupliquer", 3000)

    def reorder_layer(self, direction: int, layer_id: str | None = None):
        layer = self.document.layer(layer_id or self.selected_id)
        if layer:
            idx = self.document.layers.index(layer)
            if 0 <= idx + direction < len(self.document.layers):
                self.mutate("Changer l'ordre des calques", lambda doc: doc.reorder_layer(layer.id, direction), layer.id)

    def move_layer_to_display_position(self, layer_id: str, insertion: int):
        """Convertit une position visuelle haut->bas vers l'ordre interne bas->haut."""
        layer = self.document.layer(layer_id)
        if layer is None:
            return
        if layer.locked:
            self.statusBar().showMessage("Déverrouillez le calque avant de le déplacer", 3000)
            return
        display_ids = [layer.id for layer in reversed(self.document.layers)]
        current = display_ids.index(layer_id)
        insertion = max(0, min(insertion, len(display_ids)))
        display_ids.pop(current)
        if insertion > current:
            insertion -= 1
        insertion = max(0, min(insertion, len(display_ids)))
        display_ids.insert(insertion, layer_id)
        if display_ids == [layer.id for layer in reversed(self.document.layers)]:
            return

        def apply_order(doc):
            by_id = {layer.id: layer for layer in doc.layers}
            doc.layers = [by_id[id_] for id_ in reversed(display_ids)]
            doc.normalize_folders()

        self.mutate("Réordonner le calque par glisser-déposer", apply_order, layer_id)

    def new_document(self):
        if not self.maybe_save():
            return
        dialog = NewProjectDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            document = dialog.document()
            self._collapsed_folders = {}
            self.install_document(document, None)
        except Exception as exc:
            QMessageBox.critical(self, "Création impossible", str(exc))
            return
        self.project_path = None
        self.editing_template = None
        template = dialog.selected_template() if dialog.tabs.currentIndex() == 1 else None
        self.template_origin = template.stem if template is not None else None
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self._reset_selection()
        self.canvas.fit_document()
        self.update_title()
        self._warn_missing_fonts(document)

    def resize_document(self):
        dialog = ResizeDocumentDialog(self.document.width, self.document.height, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        width, height = dialog.dimensions()
        if (width, height) == (self.document.width, self.document.height):
            return

        def resize(doc):
            doc.width = width
            doc.height = height

        if self.mutate(f"Redimensionner le document en {width} × {height} px", resize, self.selected_id):
            self.canvas.fit_document()

    def maybe_save(self) -> bool:
        self._flush_pending_curve()
        if not self.is_modified():
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Modifications non enregistrées")
        box.setText("Enregistrer les modifications du document ?")
        box.setStandardButtons(
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel
        )
        box.button(QMessageBox.StandardButton.Save).setStyleSheet(dialog_button_style("primary"))
        box.button(QMessageBox.StandardButton.Discard).setStyleSheet(dialog_button_style("danger"))
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        box.setEscapeButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        result = box.standardButton(box.clickedButton())
        if result == QMessageBox.StandardButton.Cancel:
            return False
        if result == QMessageBox.StandardButton.Save:
            return self.save_document()
        return True

    def open_document(self):
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir un projet", self.initial_path("project"),
            "Projet Manta Layers (*.manta);;Ancien projet Manta Layers (*.mcrab)"
        )
        if not path:
            return
        try:
            doc = open_project(path)
            self._collapsed_folders = {}
            self.install_document(doc, None)
        except Exception as exc:
            QMessageBox.critical(self, "Projet illisible", str(exc))
            return
        opened_path = Path(path)
        self.editing_template = self.template_origin = None
        self.remember_directory("project", opened_path.parent)
        self.project_path = opened_path if opened_path.suffix.lower() == ".manta" else None
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self._reset_selection()
        self.canvas.fit_document()
        self.update_title()
        self.statusBar().showMessage(f"Projet chargé : {opened_path.name}", 5000)
        self._warn_missing_fonts(doc)

    def _warn_missing_fonts(self, doc: Document):
        missing = sorted({layer.font_family for layer in doc.layers
                          if layer.kind == "text" and not font_is_installed(layer.font_family)})
        if not missing:
            return
        QMessageBox.information(
            self, "Polices absentes",
            "Ces polices ne sont pas disponibles sur cet ordinateur :\n\n"
            + "\n".join(f"• {name}" for name in missing)
            + "\n\nLe texte s'affiche avec une police de remplacement. Le nom d'origine reste "
            "enregistré dans le projet tant que vous ne choisissez pas une autre police. "
            "Pour retrouver le rendu exact, utilisez Fichier > Importer une police…",
        )

    def save_document(self) -> bool:
        if self.editing_template is not None:
            return self._write_template_back()
        if self.project_path is None:
            return self.save_as_document()
        return self._write_project(self.project_path)

    def save_as_document(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self, "Sauvegarder le projet", self.initial_path("project", f"{self._file_stem()}.manta"),
            "Projet Manta Layers (*.manta)"
        )
        if not path:
            return False
        destination = Path(path)
        if destination.suffix.lower() != ".manta":
            destination = destination.with_name(destination.name + ".manta")
        # Le chemin du projet ne change qu'après un enregistrement réussi.
        if not self._write_project(destination):
            return False
        self.remember_directory("project", destination.parent)
        self.project_path = destination
        self.editing_template = None  # "save as" turns an edited template into a project
        self.update_title()
        return True

    def _write_template_back(self) -> bool:
        """Save the element template being edited, with a fresh thumbnail."""
        self._flush_pending_curve()
        template = self.editing_template
        try:
            save_template(self.document, template["name"], self._template_thumbnail(self.document),
                          destination=template["path"], kind="elements")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Enregistrement du modèle impossible", str(exc))
            return False
        self.undo_stack.setClean()
        self.recovery.discard(self.recovery.session_id)
        self.statusBar().showMessage(f"Modèle enregistré : {template['name']}", 5000)
        return True

    # --- Element template library ----------------------------------------------------------

    def add_image_layer(self, data: bytes, name: str) -> bool:
        """Add PNG bytes as a centred image layer (tokens, imports from tools)."""
        holder = {}

        def add(doc):
            holder["id"] = doc.add_image_bytes(data, name).id

        if not self.mutate(f"Ajouter : {name}", add):
            return False
        self.select_layer(holder["id"])
        return True

    def add_sprite_layers(self, sprites, sheet_name: str) -> bool:
        """Add extracted sprites as image layers grouped in a folder, laid out in their grid order."""
        images = []
        for row, column, image in sprites:
            output = BytesIO()
            image.save(output, format="PNG")
            images.append((row, column, image.size, output.getvalue()))

        def add(doc):
            ids, x, y, line = [], 0.0, 0.0, 0
            for row, column, (width, height), data in images:
                layer = doc.add_image_bytes(data, f"{sheet_name} {row + 1}·{column + 1}", center=False)
                if x and x + width > doc.width:
                    x, y, line = 0.0, y + line, 0
                layer.x, layer.y = x, y
                x += width
                line = max(line, height)
                ids.append(layer.id)
            doc.create_folder(ids, sheet_name)

        if not self.mutate(f"Ajouter {len(images)} sprite(s)", add):
            return False
        self.statusBar().showMessage(f"{len(images)} sprite(s) ajouté(s) dans le dossier « {sheet_name} »", 5000)
        return True

    # Tool dialogs are deleted after use: each one keeps its source images in memory.

    def open_token_creator(self) -> None:
        dialog = TokenDialog(self)
        try:
            layer = self.document.layer(self.selected_id)
            if layer is not None and layer.kind == "image":
                dialog.use_selected_layer()
            dialog.exec()
        finally:
            dialog.deleteLater()

    def open_sprite_slicer(self) -> None:
        dialog = SpriteSheetDialog(self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def open_template_library(self) -> bool:
        dialog = TemplateLibraryDialog(self)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted or dialog.selected_entry() is None:
                return False
            name, (kind, value), action = dialog.selected_name(), dialog.selected_entry(), dialog.action
            elements = dialog.load_selected()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Modèle illisible", f"{dialog.selected_name()}\n{exc}")
            return False
        finally:
            dialog.deleteLater()
        if action == "edit" and kind == "user":
            return self.edit_element_template(Path(value), name, elements)
        return self.insert_template_elements(elements, name)

    def insert_template_elements(self, elements: Document, name: str) -> bool:
        """Insert a template's layers, centred and on top, as separate editable layers."""
        offset = ((self.document.width - elements.width) / 2, (self.document.height - elements.height) / 2)
        holder = {}

        def apply(doc):
            holder["ids"] = insert_elements(doc, elements, offset)

        if not self.mutate(f"Insérer le modèle « {name} »", apply):
            return False
        self.set_checked_layers(holder["ids"])
        if holder["ids"]:
            self.select_layer(holder["ids"][-1])
        self.statusBar().showMessage("Modèle inséré · ses calques sont cochés : glissez-en un pour tout déplacer", 5000)
        return True

    def edit_element_template(self, path: Path, name: str, elements: Document) -> bool:
        """Open an element template as the document; Save writes it back to the library."""
        if not self.maybe_save():
            return False
        try:
            self._collapsed_folders = {}
            self.install_document(elements, None)
        except Exception as exc:
            QMessageBox.critical(self, "Modèle illisible", str(exc))
            return False
        self.project_path = None
        self.editing_template = {"path": path, "name": name}
        self.template_origin = path.stem
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self._reset_selection()
        self.canvas.fit_document()
        self.update_title()
        self.statusBar().showMessage("Modification du modèle · Sauvegarder le projet l'enregistre", 6000)
        return True

    # --- Remembered folders ----------------------------------------------------------------
    # The last folder of each kind of operation (project, export, import, token,
    # sprites) is kept in QSettings. A document created from a template also
    # keeps its own folders, so that templates never overwrite each other's.

    def _setting_keys(self, kind: str) -> list[str]:
        keys = [f"paths/templates/{self.template_origin}/{kind}"] if self.template_origin else []
        return keys + [f"paths/{kind}"]

    def initial_path(self, kind: str, filename: str = "") -> str:
        """Folder (optionally with a file name) where a file dialog of this kind should open."""
        directory = None
        for key in self._setting_keys(kind):
            value = str(self.settings.value(key, "") or "")
            if value and Path(value).is_dir():
                directory = value
                break
        if directory is None:
            location = (QStandardPaths.StandardLocation.DocumentsLocation if kind == "project"
                        else QStandardPaths.StandardLocation.PicturesLocation)
            directory = QStandardPaths.writableLocation(location) or str(Path.home())
        return str(Path(directory) / filename) if filename else directory

    def remember_directory(self, kind: str, directory) -> None:
        for key in self._setting_keys(kind):
            self.settings.setValue(key, str(directory))

    def _file_stem(self) -> str:
        if self.editing_template is not None:
            return self.editing_template["name"]
        return self.project_path.stem if self.project_path else "MantaLayers"

    def _write_project(self, destination: Path) -> bool:
        self._flush_pending_curve()
        try:
            save_project(self.document, destination)
        except Exception as exc:
            QMessageBox.critical(self, "Enregistrement impossible", str(exc))
            return False
        self.undo_stack.setClean()
        self.recovery.discard(self.recovery.session_id)  # the project file is now up to date
        self.statusBar().showMessage(f"Enregistré : {destination.name}", 5000)
        return True

    def save_as_template(self):
        default_name = self.project_path.stem if self.project_path else "Nouveau modèle"
        name, accepted = QInputDialog.getText(
            self, "Enregistrer comme modèle", "Nom du modèle :", text=default_name
        )
        if not accepted or not name.strip():
            return
        try:
            destination = self._confirm_template_replacement(name, "preset")
            if destination is False:
                return
            path = save_template(self.document, name, self._template_thumbnail(self.document),
                                 destination=destination)
            self.statusBar().showMessage(
                f"Modèle enregistré : {name.strip()} · {path.parent}", 6000
            )
        except Exception as exc:
            QMessageBox.critical(self, "Enregistrement du modèle impossible", str(exc))

    def export_image(self):
        if self.document.width * self.document.height > MAX_DOCUMENT_PIXELS:
            QMessageBox.critical(self, "Export impossible",
                                 f"Document trop grand pour l'export (> {MAX_DOCUMENT_PIXELS // 1_000_000} "
                                 "millions de pixels). Réduisez ses dimensions.")
            return
        self._export(f"{self._file_stem()}.png", "Exporter l'image",
                     lambda: qimage_to_pil(render_document(self.document)), "Export terminé", "Export impossible")

    def export_selected_layer(self):
        layer = self.document.layer(self.selected_id)
        item = self.selected_image_item()
        if not layer or layer.kind != "image" or item is None:
            self.statusBar().showMessage("Sélectionnez un calque image à enregistrer", 3000)
            return
        self._export(f"{safe_file_stem(layer.name, 'Calque')}.png", "Enregistrer le calque sous",
                     lambda: qimage_to_pil(item.pixmap().toImage()), "Calque enregistré",
                     "Enregistrement du calque impossible")

    def _export(self, filename: str, title: str, render, done: str, failed: str) -> Path | None:
        """Ask where to save, then write the rendered image; the folder is remembered."""
        path, chosen_filter = QFileDialog.getSaveFileName(
            self, title, self.initial_path("export", filename), export.FILE_FILTERS)
        if not path:
            return None
        chosen = Path(path)
        self.remember_directory("export", chosen.parent)
        destination = export.with_image_suffix(chosen, chosen_filter)
        # The file dialog only confirmed overwriting the name typed, not the completed one.
        if destination != chosen and destination.exists():
            answer = QMessageBox.question(
                self, title, f"{destination.name} existe déjà. Le remplacer ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return None
        try:
            export.save_image(render(), destination)
        except Exception as exc:
            QMessageBox.critical(self, failed, str(exc))
            return None
        self.statusBar().showMessage(f"{done} : {destination}", 6000)
        return destination

    @staticmethod
    def _changes_document(command) -> bool:
        """True for a document edit, or a macro containing one; False for selections."""
        if isinstance(command, DocumentCommand):
            return True
        return any(MainWindow._changes_document(command.child(index))
                   for index in range(command.childCount()))

    def is_modified(self) -> bool:
        """Unsaved document edits; selection changes alone never count.

        The undo stack's clean index marks the saved state; the document is
        modified when a document edit lies between that state and the current one.
        """
        clean, current = self.undo_stack.cleanIndex(), self.undo_stack.index()
        if clean < 0:
            return True  # the saved state left the history, or restored unsaved work
        return any(self._changes_document(self.undo_stack.command(index))
                   for index in range(min(clean, current), max(clean, current)))

    def update_title(self, *_):
        if self.editing_template is not None:
            name = f"Modèle : {self.editing_template['name']}"
        else:
            name = self.project_path.name if self.project_path else "Sans titre"
        modified = " *" if self.is_modified() else ""
        self.setWindowTitle(f"{name}{modified} — Manta Layers {__version__} | ReefKit")

    def update_zoom(self):
        self.zoom_label.setText(f"{self.canvas.transform().m11() * 100:.0f} %")

    def change_zoom(self, factor):
        self.canvas.zoom_by(factor)

    def about(self):
        QMessageBox.about(self, "À propos de Manta Layers", f"""<h3>Manta Layers {__version__}</h3>
        <p>Éditeur d'images local à calques · Univers Blue Shrimp / ReefKit.</p>
        <p>Images, textes multilignes courbés sur trajectoire, calques, transformations,
        gomme et remplissages non destructifs, sélections et masques de calque, suppression
        locale de l'arrière-plan, modèles, historique, projets natifs et exports.</p>
        <p>Code source sous licence MIT ; illustrations et mascottes : tous droits réservés.</p>
        <p>La déformation Warp des lettres et le recadrage sont prévus pour les prochaines versions.</p>""")

    def dragEnterEvent(self, event):
        if self.image_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.image_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = self.image_paths_from_mime(event.mimeData())
        if paths:
            self._import_paths(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    @staticmethod
    def image_paths_from_mime(mime_data) -> list[str]:
        if not mime_data.hasUrls():
            return []
        return [url.toLocalFile() for url in mime_data.urls()
                if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in IMAGE_SUFFIXES]

    # --- Keyboard nudging ---------------------------------------------------------------

    def nudge_layer(self, dx: float, dy: float) -> bool:
        """Move the selected layer with the arrow keys; a burst of presses is one undo step."""
        layer = self.document.layer(self.selected_id)
        if layer is None or layer.locked:
            return False
        before = self.document.clone()
        after = before.clone()
        target = after.layer(layer.id)
        target.x += dx
        target.y += dy
        self._push(DocumentCommand(self, before, after, "Déplacer au clavier", layer.id, layer.id,
                                   merge_key=("nudge", layer.id)))
        return True

    # --- Session recovery ------------------------------------------------------------
    # While the document has unsaved changes, a copy is written every minute (see
    # app/recovery.py); at start-up, the copies of crashed sessions are offered.

    def _setup_recovery(self):
        self.recovery = SessionRecovery(self.recovery_dir, self)
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(RECOVERY_INTERVAL_MS)
        self.autosave_timer.timeout.connect(lambda: self.autosave_now(background=True))
        self.autosave_timer.start()
        QTimer.singleShot(0, self.offer_session_recovery)

    def autosave_now(self, background: bool = False) -> bool:
        """Write the recovery copy if the document has unsaved changes; True when written (or started)."""
        if not self.is_modified():
            return False
        return self.recovery.write(self.document, self._revision, self.project_path, background)

    def offer_session_recovery(self) -> bool:
        """Offer the copies left by crashed sessions, newest first; True when one was restored.

        Each copy is restored, deleted or kept for the next start, as the user
        chooses: a copy is never deleted without having been shown. Only one
        copy can be restored (the window holds one document); the others stay.
        """
        candidates = self.recovery.candidates()
        restored = False
        try:
            for index, candidate in enumerate(candidates):
                choice = self._ask_recovery(candidate, index, len(candidates))
                if choice == "later":
                    break
                if choice == "discard":
                    self.recovery.discard(candidate["id"])
                    continue
                restored = self._restore_recovery(candidate)
                break
        finally:
            for candidate in candidates:
                candidate["lock"].unlock()
        return restored

    def _ask_recovery(self, candidate: dict, index: int, count: int) -> str:
        """Ask what to do with one recovery copy: "restore", "discard" or "later"."""
        text, details = recovery_text(candidate, index, count)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Restaurer la session")
        box.setText(text)
        box.setInformativeText(details)
        restore = box.addButton("Restaurer", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Supprimer", QMessageBox.ButtonRole.DestructiveRole)
        later = box.addButton("Plus tard", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(restore)
        box.setEscapeButton(later)
        box.exec()
        clicked = box.clickedButton()
        box.deleteLater()
        if clicked is restore:
            return "restore"
        return "discard" if clicked is discard else "later"

    def _restore_recovery(self, candidate: dict) -> bool:
        try:
            document = open_project(candidate["project"])
            self._collapsed_folders = {}
            self.install_document(document, None)
        except Exception as exc:
            QMessageBox.warning(self, "Restauration impossible",
                                f"{exc}\n\nLa copie reste disponible : {candidate['project']}")
            return False
        original = candidate["meta"].get("project_path")
        self.project_path = Path(original) if original and Path(original).suffix == ".manta" else None
        self.undo_stack.clear()
        self.undo_stack.resetClean()  # restored work is unsaved
        self._reset_selection()
        self.canvas.fit_document()
        self.update_title()
        # The restored work now belongs to this session: its own copies take over.
        self.recovery.discard(candidate["id"])
        return True

    def _wait_for_background_work(self):
        """A background removal or download closed mid-way must end before the window is destroyed."""
        if not background_dialog.orphan_workers_running():
            return
        self.statusBar().showMessage("Fin du détourage en cours avant la fermeture…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            QApplication.processEvents()
            background_dialog.wait_for_orphan_workers()
        finally:
            QApplication.restoreOverrideCursor()

    def closeEvent(self, event):
        if self.maybe_save():
            self.refreshing = True
            self._wait_for_background_work()
            self.autosave_timer.stop()
            self.recovery.close()
            event.accept()
        else:
            event.ignore()
