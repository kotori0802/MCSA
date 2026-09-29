"""Apple-inspired light/dark themes for the Qt shell."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChartPalette:
    bg: str
    plot_bg: str
    border: str
    grid: str
    text: str
    muted: str
    accent: str
    on_cadence: str
    extra: str
    chatter: str
    miss: str
    rebound: str
    overlay: str
    target_line: str
    interval_line: str
    interval_fill: str


LIGHT_PALETTE = ChartPalette(
    bg="#ffffff",
    plot_bg="#fbfbfd",
    border="#e5e5ea",
    grid="#d2d2d7",
    text="#1d1d1f",
    muted="#6e6e73",
    accent="#007aff",
    on_cadence="#007aff",
    extra="#ff3b30",
    chatter="#ff9500",
    miss="#1d1d1f",
    rebound="#af52de",
    overlay="#8e8e93",
    target_line="#34c759",
    interval_line="#007aff",
    interval_fill="#007aff22",
)

DARK_PALETTE = ChartPalette(
    bg="#1c1c1e",
    plot_bg="#2c2c2e",
    border="#3a3a3c",
    grid="#48484a",
    text="#f5f5f7",
    muted="#98989d",
    accent="#0a84ff",
    on_cadence="#0a84ff",
    extra="#ff453a",
    chatter="#ff9f0a",
    miss="#f5f5f7",
    rebound="#bf5af2",
    overlay="#636366",
    target_line="#30d158",
    interval_line="#0a84ff",
    interval_fill="#0a84ff33",
)

LIGHT_STYLE = """
QWidget {
    font-family: "Segoe UI Variable", "Segoe UI", "SF Pro Text", sans-serif;
    font-size: 13px;
    color: #1d1d1f;
    background: #f5f5f7;
}
QMainWindow, QDialog {
    background: #f5f5f7;
}
QFrame#Card, QFrame#TestArea, QFrame#SideCard, QFrame#NavRail {
    background: #ffffff;
    border: 1px solid #e5e5ea;
    border-radius: 16px;
}
QFrame#NavRail {
    border-radius: 18px;
}
QWidget#Workspace {
    background: transparent;
}
QScrollArea#PageScroll {
    background: transparent;
    border: none;
}
QScrollArea#PageScroll > QWidget > QWidget {
    background: transparent;
}
QLabel#PageTitle {
    font-size: 28px;
    font-weight: 700;
    color: #1d1d1f;
    background: transparent;
}
QLabel#PageSubtitle {
    font-size: 13px;
    color: #6e6e73;
    background: transparent;
}
QPushButton#NavButton {
    text-align: left;
    border: none;
    border-radius: 10px;
    padding: 10px 14px;
    background: transparent;
    font-weight: 600;
}
QPushButton#NavButton:hover {
    background: #f2f2f7;
}
QPushButton#NavButton:checked {
    background: #007aff;
    color: white;
}
QSplitter::handle:vertical {
    background: #e5e5ea;
    height: 6px;
    margin: 4px 0;
    border-radius: 3px;
}
QFrame#TestArea {
    border: 2px dashed #007aff;
    border-radius: 20px;
}
QFrame#TestArea[active="true"] {
    border: 2px solid #34c759;
    background: #f7fff9;
}
QLabel#Title {
    font-size: 22px;
    font-weight: 700;
    color: #1d1d1f;
    background: transparent;
}
QLabel#Subtitle {
    font-size: 13px;
    color: #007aff;
    font-weight: 600;
    background: transparent;
}
QLabel#Muted {
    color: #6e6e73;
    background: transparent;
    font-size: 12px;
}
QLabel#StatLabel {
    color: #6e6e73;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.4px;
    background: transparent;
}
QLabel#StatValue {
    font-size: 17px;
    font-weight: 700;
    color: #1d1d1f;
    background: transparent;
}
QLabel#Alert {
    color: #c0392b;
    font-weight: 600;
    font-size: 12px;
    background: transparent;
}
QLabel#Hint {
    color: #6e6e73;
    font-size: 14px;
    font-weight: 600;
    background: transparent;
}
QLabel#OverlayDelta {
    color: #5856d6;
    font-size: 11px;
    font-weight: 600;
    background: transparent;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #d2d2d7;
    border-radius: 12px;
    padding: 10px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background: #fbfbfd;
}
QPushButton:pressed {
    background: #ececef;
}
QPushButton:disabled {
    color: #a1a1a6;
    background: #f2f2f7;
}
QPushButton#Primary {
    background: #007aff;
    color: white;
    border: none;
}
QPushButton#Primary:hover {
    background: #0066d6;
}
QPushButton#Primary:disabled {
    background: #9ec9ff;
    color: #f5f5f7;
}
QPushButton#Danger {
    background: #ff3b30;
    color: white;
    border: none;
}
QPushButton#Secondary {
    background: #f2f2f7;
    border: 1px solid #d2d2d7;
}
QRadioButton, QCheckBox {
    background: transparent;
    spacing: 8px;
}
QComboBox, QLineEdit, QSpinBox {
    background: #ffffff;
    border: 1px solid #d2d2d7;
    border-radius: 10px;
    padding: 8px 10px;
    min-height: 18px;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QTextEdit {
    background: #fbfbfd;
    border: 1px solid #e5e5ea;
    border-radius: 12px;
    padding: 8px;
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 11px;
}
QListWidget {
    background: #ffffff;
    border: 1px solid #e5e5ea;
    border-radius: 10px;
    padding: 4px;
}
"""

DARK_STYLE = """
QWidget {
    font-family: "Segoe UI Variable", "Segoe UI", "SF Pro Text", sans-serif;
    font-size: 13px;
    color: #f5f5f7;
    background: #000000;
}
QMainWindow, QDialog {
    background: #000000;
}
QFrame#Card, QFrame#TestArea, QFrame#SideCard, QFrame#NavRail {
    background: #1c1c1e;
    border: 1px solid #3a3a3c;
    border-radius: 16px;
}
QFrame#NavRail {
    border-radius: 18px;
}
QWidget#Workspace {
    background: transparent;
}
QScrollArea#PageScroll {
    background: transparent;
    border: none;
}
QScrollArea#PageScroll > QWidget > QWidget {
    background: transparent;
}
QLabel#PageTitle {
    font-size: 28px;
    font-weight: 700;
    color: #f5f5f7;
    background: transparent;
}
QLabel#PageSubtitle {
    font-size: 13px;
    color: #98989d;
    background: transparent;
}
QPushButton#NavButton {
    text-align: left;
    border: none;
    border-radius: 10px;
    padding: 10px 14px;
    background: transparent;
    font-weight: 600;
    color: #f5f5f7;
}
QPushButton#NavButton:hover {
    background: #2c2c2e;
}
QPushButton#NavButton:checked {
    background: #0a84ff;
    color: white;
}
QSplitter::handle:vertical {
    background: #3a3a3c;
    height: 6px;
    margin: 4px 0;
    border-radius: 3px;
}
QFrame#TestArea {
    border: 2px dashed #0a84ff;
    border-radius: 20px;
}
QFrame#TestArea[active="true"] {
    border: 2px solid #30d158;
    background: #1a2e1f;
}
QLabel#Title {
    font-size: 22px;
    font-weight: 700;
    color: #f5f5f7;
    background: transparent;
}
QLabel#Subtitle {
    font-size: 13px;
    color: #0a84ff;
    font-weight: 600;
    background: transparent;
}
QLabel#Muted {
    color: #98989d;
    background: transparent;
    font-size: 12px;
}
QLabel#StatLabel {
    color: #98989d;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.4px;
    background: transparent;
}
QLabel#StatValue {
    font-size: 17px;
    font-weight: 700;
    color: #f5f5f7;
    background: transparent;
}
QLabel#Alert {
    color: #ff6961;
    font-weight: 600;
    font-size: 12px;
    background: transparent;
}
QLabel#Hint {
    color: #98989d;
    font-size: 14px;
    font-weight: 600;
    background: transparent;
}
QLabel#OverlayDelta {
    color: #5e5ce6;
    font-size: 11px;
    font-weight: 600;
    background: transparent;
}
QPushButton {
    background: #2c2c2e;
    border: 1px solid #48484a;
    border-radius: 12px;
    padding: 10px 14px;
    font-weight: 600;
    color: #f5f5f7;
}
QPushButton:hover {
    background: #3a3a3c;
}
QPushButton:pressed {
    background: #48484a;
}
QPushButton:disabled {
    color: #636366;
    background: #1c1c1e;
}
QPushButton#Primary {
    background: #0a84ff;
    color: white;
    border: none;
}
QPushButton#Primary:hover {
    background: #409cff;
}
QPushButton#Primary:disabled {
    background: #1a3a5c;
    color: #636366;
}
QPushButton#Danger {
    background: #ff453a;
    color: white;
    border: none;
}
QPushButton#Secondary {
    background: #2c2c2e;
    border: 1px solid #48484a;
}
QRadioButton, QCheckBox {
    background: transparent;
    color: #f5f5f7;
}
QComboBox, QLineEdit, QSpinBox {
    background: #2c2c2e;
    border: 1px solid #48484a;
    border-radius: 10px;
    padding: 8px 10px;
    min-height: 18px;
    color: #f5f5f7;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QTextEdit {
    background: #2c2c2e;
    border: 1px solid #3a3a3c;
    border-radius: 12px;
    padding: 8px;
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 11px;
    color: #f5f5f7;
}
QListWidget {
    background: #2c2c2e;
    border: 1px solid #3a3a3c;
    border-radius: 10px;
    padding: 4px;
    color: #f5f5f7;
}
"""

APP_STYLE = LIGHT_STYLE  # backward compat


def get_style(theme: str) -> str:
    return DARK_STYLE if theme == "dark" else LIGHT_STYLE


def get_palette(theme: str) -> ChartPalette:
    return DARK_PALETTE if theme == "dark" else LIGHT_PALETTE
