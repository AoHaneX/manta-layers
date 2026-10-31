"""Tokens visuels et feuille de style ReefKit pour Manta Layers."""

COLORS = {
    "background": "#00192D",
    "panel": "#092B40",
    "field": "#10384E",
    "border": "#2F6072",
    "primary": "#4DD6E7",
    "primary_hover": "#7CE6F0",
    "primary_pressed": "#27AEBF",
    "text": "#EDF9FE",
    "muted": "#ACC9D4",
    "copper": "#D6A06A",
    "danger": "#F07178",
    "danger_pressed": "#C95760",
    "disabled": "#587887",
    # Zone de travail du canvas et accessoires d'édition.
    "canvas": "#071221",
    "canvas_border": "#4A6883",
    "rotation_handle": "#FFD86B",
    "checker_light": "#F9FCFF",
    "checker_dark": "#DDE4EC",
}

RADIUS = {"control": 8, "panel": 12}

STYLE = f"""
QMainWindow {{
    background-color: {COLORS['background']};
}}
QWidget {{
    background-color: transparent;
    color: {COLORS['text']};
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 12px;
}}
QWidget#sidePanel {{
    background-color: {COLORS['panel']};
    border: none;
}}
QWidget#propertyCard {{
    background-color: transparent;
    border: none;
}}
QWidget#colorEditor {{
    background-color: {COLORS['field']};
    border: 1px solid {COLORS['border']};
    border-radius: {RADIUS['control']}px;
}}
QScrollArea#rightPanelScroll {{
    background: {COLORS['panel']};
    border: none;
}}
QScrollArea#rightPanelScroll QScrollBar:vertical {{
    background: {COLORS['panel']};
    width: 12px;
    margin: 2px;
}}
QScrollArea#rightPanelScroll QScrollBar::handle:vertical {{
    background: {COLORS['primary']};
    min-height: 34px;
    border-radius: 4px;
}}
QScrollArea#rightPanelScroll QScrollBar::handle:vertical:hover {{
    background: {COLORS['primary_hover']};
}}
QScrollArea#rightPanelScroll QScrollBar::add-line:vertical,
QScrollArea#rightPanelScroll QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollArea#rightPanelScroll QScrollBar::add-page:vertical,
QScrollArea#rightPanelScroll QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollArea#leftPanelScroll {{
    background: transparent;
    border: none;
}}
QScrollArea#leftPanelScroll QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollArea#leftPanelScroll QScrollBar::handle:vertical {{
    background: {COLORS['primary']};
    min-height: 34px;
    border-radius: 3px;
}}
QScrollArea#leftPanelScroll QScrollBar::add-line:vertical,
QScrollArea#leftPanelScroll QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollArea#leftPanelScroll QScrollBar::add-page:vertical,
QScrollArea#leftPanelScroll QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QMenuBar, QMenu, QToolBar, QStatusBar {{
    background-color: {COLORS['panel']};
    color: {COLORS['text']};
}}
QMenuBar {{ border-bottom: 1px solid {COLORS['border']}; }}
QMenuBar::item, QMenu::item {{ padding: 7px 10px; }}
QMenuBar::item:selected, QMenu::item:selected {{
    background: {COLORS['field']};
    color: {COLORS['primary_hover']};
}}
QMenu#canvasContextMenu {{
    background-color: {COLORS['field']};
    border: 1px solid {COLORS['primary']};
    border-radius: 8px;
    padding: 6px;
}}
QMenu#canvasContextMenu::item {{ padding: 8px 28px 8px 12px; border-radius: 5px; }}
QMenu#canvasContextMenu::item:selected {{
    background-color: {COLORS['primary']};
    color: {COLORS['background']};
}}
QMenu#canvasContextMenu::item:disabled {{ color: {COLORS['disabled']}; }}
QToolBar {{
    border: none;
    border-bottom: 1px solid {COLORS['border']};
    spacing: 8px;
    padding: 6px 8px;
}}
QToolButton, QPushButton {{
    background-color: {COLORS['panel']};
    border: 1px solid {COLORS['border']};
    color: {COLORS['text']};
    min-height: 22px;
    padding: 7px 14px;
    border-radius: {RADIUS['control']}px;
}}
QToolButton:hover, QPushButton:hover {{
    background-color: {COLORS['field']};
    border-color: {COLORS['primary_hover']};
}}
QToolButton:pressed, QPushButton:pressed {{
    background-color: {COLORS['primary_pressed']};
    color: {COLORS['background']};
}}
QToolButton:focus, QPushButton:focus {{
    border: 2px solid {COLORS['primary']};
    padding: 6px 13px;
}}
QToolButton:checked {{
    background-color: {COLORS['primary']};
    border-color: {COLORS['primary_hover']};
    color: {COLORS['background']};
}}
QToolButton#layerAction {{
    background-color: transparent;
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    min-height: 0;
    padding: 0;
    font-size: 14px;
    font-weight: 700;
}}
QToolButton#layerAction:hover {{
    background-color: {COLORS['field']};
    border-color: {COLORS['primary_hover']};
}}
QToolButton#layerAction:checked {{
    background-color: {COLORS['primary']};
    color: {COLORS['background']};
}}
QToolButton#colorTool {{
    background-color: transparent;
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    min-width: 24px;
    min-height: 24px;
    padding: 3px;
}}
QToolButton#colorTool:hover {{
    background-color: {COLORS['panel']};
    border-color: {COLORS['primary_hover']};
}}
QToolButton#colorTool:checked {{
    background-color: {COLORS['primary']};
    border-color: {COLORS['primary_hover']};
}}
QToolButton#layerDragHandle {{
    background: transparent;
    border: none;
    color: {COLORS['muted']};
    min-height: 0;
    padding: 0;
    font-size: 20px;
    font-weight: 700;
}}
QToolButton#layerDragHandle:hover {{ color: {COLORS['primary_hover']}; }}
QPushButton#layerName {{
    background-color: transparent;
    border: none;
    border-radius: 0;
    min-height: 0;
    padding: 2px;
    text-align: left;
}}
QPushButton#layerName:hover {{ color: {COLORS['primary_hover']}; }}
QPushButton#sidebarToggle {{
    background: {COLORS['primary']};
    border: 1px solid {COLORS['primary']};
    color: {COLORS['background']};
    min-height: 24px;
    padding: 0;
}}
QPushButton#sidebarToggle:focus {{ padding: 0; }}
QPushButton#sidebarToggle:hover {{
    background: {COLORS['primary_hover']};
    border-color: {COLORS['primary_hover']};
    color: {COLORS['background']};
}}
QPushButton#sidebarToggle:pressed {{ background: {COLORS['primary_pressed']}; }}
QPushButton#docInfo {{
    background: transparent;
    border: 1px solid transparent;
    color: {COLORS['muted']};
    min-height: 0;
    padding: 4px 6px;
}}
QPushButton#docInfo:hover {{
    border-color: {COLORS['primary']};
    color: {COLORS['primary_hover']};
}}
QPushButton[variant="primary"] {{
    background-color: {COLORS['primary']};
    border-color: {COLORS['primary']};
    color: {COLORS['background']};
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background-color: {COLORS['primary_hover']}; }}
QPushButton[variant="primary"]:pressed {{ background-color: {COLORS['primary_pressed']}; }}
QPushButton[variant="danger"] {{
    background-color: transparent;
    border-color: {COLORS['danger']};
    color: {COLORS['danger']};
}}
QPushButton[variant="danger"]:hover {{
    background-color: {COLORS['danger']};
    color: {COLORS['background']};
}}
QToolButton:disabled, QPushButton:disabled {{
    background-color: {COLORS['background']};
    border-color: {COLORS['border']};
    color: {COLORS['disabled']};
}}
QLineEdit, QPlainTextEdit, QDoubleSpinBox, QSpinBox, QComboBox, QFontComboBox {{
    background: {COLORS['field']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    border-radius: {RADIUS['control']}px;
    padding: 6px 8px;
    min-height: 24px;
    selection-background-color: {COLORS['primary_pressed']};
}}
QLineEdit:hover, QPlainTextEdit:hover, QDoubleSpinBox:hover, QSpinBox:hover, QComboBox:hover, QFontComboBox:hover {{
    border-color: {COLORS['primary_hover']};
}}
QLineEdit:focus, QPlainTextEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus, QFontComboBox:focus {{
    border: 2px solid {COLORS['primary']};
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled, QComboBox:disabled, QFontComboBox:disabled {{
    background: {COLORS['background']};
    color: {COLORS['disabled']};
}}
QListWidget, QUndoView {{
    background: {COLORS['field']};
    border: 1px solid {COLORS['border']};
    border-radius: {RADIUS['control']}px;
    padding: 4px;
    outline: none;
}}
QListWidget::item, QUndoView::item {{ padding: 7px 5px; border-radius: 6px; }}
QListWidget::item:hover, QUndoView::item:hover {{ background: {COLORS['panel']}; }}
QListWidget::item:selected, QUndoView::item:selected {{
    background: {COLORS['primary_pressed']};
    color: {COLORS['text']};
}}
QListWidget:focus, QUndoView:focus {{ border: 2px solid {COLORS['primary']}; }}
QTabWidget::pane {{
    background: transparent;
    border: 1px solid {COLORS['border']};
    border-radius: {RADIUS['control']}px;
    top: -1px;
}}
QTabBar::tab {{
    background: {COLORS['panel']};
    color: {COLORS['muted']};
    border: 1px solid {COLORS['border']};
    padding: 9px 16px;
    margin-right: 3px;
    border-top-left-radius: {RADIUS['control']}px;
    border-top-right-radius: {RADIUS['control']}px;
}}
QTabBar::tab:hover {{ color: {COLORS['primary_hover']}; }}
QTabBar::tab:selected {{
    background: {COLORS['primary']};
    border-color: {COLORS['primary']};
    color: {COLORS['background']};
    font-weight: 600;
}}
QTabBar::tab:focus {{ border: 2px solid {COLORS['primary_hover']}; }}
QCheckBox::indicator {{
    width: 17px;
    height: 17px;
    border: 1px solid {COLORS['border']};
    border-radius: 5px;
    background: {COLORS['background']};
}}
QCheckBox::indicator:hover {{ border-color: {COLORS['primary_hover']}; }}
QCheckBox::indicator:checked {{
    background: {COLORS['primary']};
    border-color: {COLORS['primary_hover']};
}}
QSplitter::handle {{ background: {COLORS['border']}; width: 1px; }}
QLabel#brandTitle {{
    font-family: 'Chakra Petch', 'Segoe UI', sans-serif;
    font-size: 21px;
    font-weight: 700;
    color: {COLORS['text']};
}}
QLabel#sectionTitle {{
    font-family: 'Chakra Petch', 'Segoe UI', sans-serif;
    font-weight: 600;
    font-size: 13px;
    color: {COLORS['primary']};
    margin-top: 8px;
}}
QLabel#muted {{ color: {COLORS['muted']}; }}
QStatusBar {{ border-top: 1px solid {COLORS['border']}; color: {COLORS['muted']}; }}
QScrollBar:vertical {{ background: {COLORS['background']}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {COLORS['border']}; min-height: 28px; border-radius: 5px; }}
QScrollBar::handle:vertical:hover {{ background: {COLORS['primary_pressed']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


def dialog_button_style(variant: str) -> str:
    """Style posé directement sur un bouton de QMessageBox.

    Sous Windows, le style natif de la boîte ignore la feuille globale : les
    boutons Enregistrer (primary) et Ignorer (danger) reçoivent donc le leur.
    """
    danger = variant == "danger"
    base = COLORS["danger"] if danger else COLORS["primary"]
    hover = f"color: {COLORS['text']};" if danger else f"background-color: {COLORS['primary_hover']};"
    pressed = COLORS["danger_pressed"] if danger else COLORS["primary_pressed"]
    return f"""
QPushButton {{
    background-color: {base};
    border: 1px solid {base};
    border-radius: {RADIUS['control']}px;
    color: {COLORS['background']};
    font-weight: 600;
    min-width: 72px;
    padding: 8px 14px;
}}
QPushButton:hover {{ {hover} }}
QPushButton:pressed {{ background-color: {pressed}; }}
"""
