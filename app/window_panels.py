"""Construction of the main window's panels, menus and tool options.

A mixin of MainWindow: it only builds widgets and connects them to the
window's methods, which own the document and every undoable change.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
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

from .canvas import CanvasView
from .icons import alignment_icon, color_tool_icon, history_arrow_icon, sidebar_arrow_icon
from .model import MAX_DIMENSION
from .selection import COMBINE_LABELS, COMBINE_MODES
from .shape_panel import ShapePropertyRows
from .textpath import SHAPE_LABELS, TEXT_SHAPES
from .theme import COLORS
from .widgets import CommitPlainTextEdit, LayerListWidget, SidebarBackground

ASSETS = Path(__file__).resolve().parent.parent / "assets"


# A mixin of MainWindow: type checkers see the window it is mixed into.
if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow as _WindowBase
else:
    _WindowBase = object


class WindowPanelsMixin(_WindowBase):
    """Layout, tool tabs, property panel and menu actions of the main window."""

    if TYPE_CHECKING:
        # Attributes set by MainWindow; everything else comes from it too.

        def __getattr__(self, name: str) -> Any: ...

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
        subtitle.setObjectName("brandSubtitle")
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
            ("resize", "⇲ Redimensionner le projet", self.resize_document),
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
        self.pencil_btn = QToolButton()
        self.pencil_btn.setObjectName("colorTool")
        self.pencil_btn.setCheckable(True)
        self.pencil_btn.setIcon(color_tool_icon("pencil"))
        self.pencil_btn.setIconSize(QSize(20, 20))
        self.pencil_btn.setText("Crayon")
        self.pencil_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.pencil_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.pencil_btn.setToolTip("Crayon (B) : dessiner avec la couleur choisie, aux tailles de la gomme")
        self.pencil_btn.clicked.connect(self.set_pencil_active)
        paint_tools_layout.addWidget(self.pencil_btn)
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
        eraser_layout.addRow("Taille", self.eraser_size_preset)
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
        self.pencil_action = QAction(color_tool_icon("pencil"), "Crayon (B)", self)
        self.pencil_action.setCheckable(True)
        self.pencil_action.triggered.connect(self.set_pencil_active)
        tools_menu.addAction(self.pencil_action)
        self.pencil_shortcut = QShortcut(QKeySequence("B"), self.canvas)
        self.pencil_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.pencil_shortcut.activated.connect(
            lambda: self.set_pencil_active(not self.pencil_active)
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
