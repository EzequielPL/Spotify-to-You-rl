"""Tema claro/oscuro: paletas y hoja de estilos (hoja: no importa otros módulos de gui)."""

import sys
from string import Template

from PySide6.QtWidgets import QApplication, QWidget

from ..models import Status


# ── Tema ─────────────────────────────────────────────────────────────────────

PALETAS = {
    "dark": dict(bg="#0f1115", card="#171a21", alt="#1b1f27", input="#20242d", border="#2a2f3a",
                 text="#e8eaed", muted="#8a8f98", btn="#232833", btn_hover="#2c3240",
                 sel="#25402f", accent="#1db954", accent_hover="#1ed760", danger="#f04461",
                 # Estados (contraste ≥ 4.5:1 sobre card/alt/input)
                 st_pending="#9aa0a9", st_searching="#60a5fa", st_ok="#1db954",
                 st_doubtful="#f5a524", st_failed="#ff6b81", st_manual="#b78cff"),
    "light": dict(bg="#f4f5f7", card="#ffffff", alt="#f8f9fb", input="#f1f3f5", border="#dde1e6",
                  text="#15181d", muted="#6b7280", btn="#ffffff", btn_hover="#eef0f3",
                  sel="#d9f5e3", accent="#1db954", accent_hover="#17a34a", danger="#e11d48",
                  # Variantes oscuras: el verde/ámbar de Spotify no se leen sobre blanco
                  st_pending="#5b616b", st_searching="#1d4ed8", st_ok="#147a3a",
                  st_doubtful="#a84c08", st_failed="#be123c", st_manual="#7e22ce"),
}

_CLAVE_ESTADO = {
    Status.PENDING: "st_pending", Status.SEARCHING: "st_searching", Status.OK: "st_ok",
    Status.DOUBTFUL: "st_doubtful", Status.FAILED: "st_failed", Status.MANUAL: "st_manual",
}


def colores_estado(tema: str) -> dict[Status, str]:
    """Color de cada estado en el tema dado (tema desconocido → oscuro)."""
    paleta = PALETAS.get(tema, PALETAS["dark"])
    return {estado: paleta[clave] for estado, clave in _CLAVE_ESTADO.items()}


QSS = Template("""
* { font-family: $font; font-size: 13px; }
QMainWindow, QDialog, QWidget#root { background: $bg; }
QWidget { color: $text; }
QToolTip { background: $card; color: $text; border: 1px solid $border; padding: 6px; }
QFrame#card { background: $card; border: 1px solid $border; border-radius: 12px; }
QFrame#card[drop="true"] { border: 2px dashed $accent; }   /* arrastrando un enlace o un .txt */
QFrame#aviso { background: $alt; border: 1px solid $st_doubtful; border-radius: 8px; }   /* yt-dlp antiguo */
QLabel#title { font-size: 22px; font-weight: 600; }
QLabel#subtitle, QLabel#muted { color: $muted; }
QLabel#empty { color: $muted; font-size: 15px; }
QLabel#chip { background: $input; border-radius: 11px; padding: 3px 11px; }
QLabel#chip:hover { background: $btn_hover; }   /* los chips filtran la tabla al pulsarlos */
QLabel#chip[activo="true"] { border: 1px solid $accent; padding: 2px 10px; }

QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: $input; border: 1px solid $border; border-radius: 8px; padding: 6px 10px;
    selection-background-color: $accent; selection-color: #0b0b0b;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: $accent; }
QAbstractSpinBox QLineEdit { background: transparent; border: none; padding: 0 0 0 10px; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {
    subcontrol-origin: border; width: 0px; border: none;   /* sin flechas: rueda o teclado */
}
QLineEdit[state="invalid"] { border-color: $danger; }
QLineEdit[state="valid"] { border-color: $accent; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: $card; border: 1px solid $border; selection-background-color: $sel; }

QPushButton, QToolButton {
    background: $btn; border: 1px solid $border; border-radius: 8px; padding: 7px 14px;
}
QPushButton:hover, QToolButton:hover { background: $btn_hover; }
QPushButton:disabled, QToolButton:disabled { color: $muted; }
QToolButton::menu-indicator { image: none; }
QPushButton#primary { background: $accent; color: #0b0b0b; border: none; font-weight: 600; padding: 9px 26px; }
QPushButton#primary:hover { background: $accent_hover; }
QPushButton#primary:disabled { background: $btn; color: $muted; }
QPushButton#ghost { background: transparent; border: none; padding: 6px 10px; }
QPushButton#cancelar { color: $danger; padding: 4px 12px; }
QPushButton#ghost:hover { background: $btn_hover; }
QPushButton#segment { border-radius: 0; padding: 6px 16px; background: $input; }
QPushButton#segment[pos="left"] { border-top-left-radius: 8px; border-bottom-left-radius: 8px; }
QPushButton#segment[pos="right"] { border-top-right-radius: 8px; border-bottom-right-radius: 8px; border-left: none; }
QPushButton#segment:checked { background: $accent; color: #0b0b0b; border-color: $accent; }

QTableView {
    background: $card; alternate-background-color: $alt; border: 1px solid $border; border-radius: 12px;
    gridline-color: transparent; selection-background-color: $sel; selection-color: $text; outline: 0;
}
QTableView::item { padding: 4px 8px; border: none; }
QHeaderView::section {
    background: $card; color: $muted; border: none; border-bottom: 1px solid $border;
    padding: 8px; font-weight: 600;
}
QTableCornerButton::section { background: $card; border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 4px; }
QScrollBar::handle:vertical { background: $border; border-radius: 3px; min-height: 30px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 4px; }
QScrollBar::handle:horizontal { background: $border; border-radius: 3px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QGroupBox { border: 1px solid $border; border-radius: 10px; margin-top: 14px; padding: 12px 10px 8px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: $muted; }

QProgressBar { background: $input; border: none; border-radius: 4px; max-height: 8px; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid $border; background: $input; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }
QMenu { background: $card; border: 1px solid $border; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background: $sel; }
QMenu::separator { height: 1px; background: $border; margin: 4px 8px; }
""")


# Fuente del sistema en cada plataforma (tamaños en px para que se vean igual en Windows y macOS)
if sys.platform == "win32":
    FUENTE = '"Segoe UI Variable Text", "Segoe UI", sans-serif'
elif sys.platform == "darwin":
    FUENTE = '".AppleSystemUIFont", "Helvetica Neue", sans-serif'
else:
    FUENTE = "sans-serif"


def aplicar_tema(app: QApplication, tema: str):
    app.setStyleSheet(QSS.substitute(PALETAS.get(tema, PALETAS["dark"]), font=FUENTE))


def repolish(w: QWidget):
    w.style().unpolish(w)
    w.style().polish(w)
