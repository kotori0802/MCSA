"""Apple-inspired light/dark themes for the Qt shell."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QFont

# System fonts only; JhengHei covers Traditional Chinese glyphs on Windows.
UI_FONT_FAMILIES: tuple[str, ...] = (
    "Segoe UI Variable",
    "Segoe UI",
    "Microsoft JhengHei UI",
    "Microsoft JhengHei",
    "PingFang TC",
    "SF Pro Text",
)
UI_FONT_STACK = ", ".join(f'"{name}"' for name in UI_FONT_FAMILIES) + ", sans-serif"
MONO_FONT_STACK = 'Consolas, "Cascadia Mono", monospace'

DENSITY_NORMAL = "normal"
DENSITY_COMPACT = "compact"
DENSITIES: tuple[str, ...] = (DENSITY_NORMAL, DENSITY_COMPACT)
# Windows below 800 px tall (the 1280×720 and 1366×768 presets) or 1100 px wide use the compact tier.
COMPACT_MAX_HEIGHT = 800
COMPACT_MAX_WIDTH = 1100

# Pixel sizes per typography role. Compact trims headings and metrics; body text stays readable.
TYPE_SCALE: dict[str, dict[str, int]] = {
    DENSITY_NORMAL: {
        "page_title": 24,
        "section_title": 20,
        "metric": 17,
        "emphasis": 15,
        "hint": 14,
        "body": 13,
        "label": 12,
        "caption": 11,
        "micro": 10,
    },
    DENSITY_COMPACT: {
        "page_title": 20,
        "section_title": 18,
        "metric": 15,
        "emphasis": 14,
        "hint": 13,
        "body": 13,
        "label": 12,
        "caption": 11,
        "micro": 10,
    },
}

CONTROL_PADDING: dict[str, dict[str, str]] = {
    DENSITY_NORMAL: {
        "button": "10px 14px",
        "secondary": "10px 16px",
        "segment": "8px 14px",
        "tool": "10px 22px 10px 16px",
        "input": "8px 10px",
        "combo": "8px 32px 8px 12px",
    },
    DENSITY_COMPACT: {
        "button": "6px 12px",
        "secondary": "6px 12px",
        "segment": "5px 10px",
        "tool": "6px 20px 6px 12px",
        "input": "5px 8px",
        "combo": "5px 30px 5px 10px",
    },
}

# Layout spacing applied in code (QSS cannot set layout margins).
LAYOUT_METRICS: dict[str, dict[str, object]] = {
    DENSITY_NORMAL: {
        "workspace_gap": 12,
        "header_margins": (0, 2, 0, 6),
        "header_gap": 4,
        "capture_gap": 12,
        "actions_margins": (16, 12, 16, 12),
        "live_margins": (16, 14, 16, 14),
        "card_gap": 8,
        "toolbar_margins": (8, 4, 8, 4),
        "action_button_min_h": 38,
        "toolbar_button_min_h": 28,
        "stat_cell_min_h": 48,
        "test_area_margins": None,
        "test_area_min_h": 320,
        "chart_min_h": 220,
    },
    DENSITY_COMPACT: {
        "workspace_gap": 6,
        "header_margins": (0, 0, 0, 2),
        "header_gap": 0,
        "capture_gap": 6,
        "actions_margins": (12, 6, 12, 6),
        "live_margins": (12, 6, 12, 6),
        "card_gap": 4,
        "toolbar_margins": (6, 2, 6, 2),
        "action_button_min_h": 30,
        "toolbar_button_min_h": 24,
        "stat_cell_min_h": 40,
        "test_area_margins": (8, 4, 8, 6),
        "test_area_min_h": 300,
        "chart_min_h": 180,
    },
}

CHART_FONT_PT: dict[str, int] = {
    "title": 10,
    "subtitle": 8,
    "tick": 8,
    "placeholder": 11,
}


def density_for_size(width: int, height: int) -> str:
    """Deterministic two-tier density from the window's client size."""
    if int(height) < COMPACT_MAX_HEIGHT or int(width) < COMPACT_MAX_WIDTH:
        return DENSITY_COMPACT
    return DENSITY_NORMAL


def type_px(role: str, density: str = DENSITY_NORMAL) -> int:
    return TYPE_SCALE[density if density in DENSITIES else DENSITY_NORMAL][role]


def layout_metric(name: str, density: str = DENSITY_NORMAL):
    return LAYOUT_METRICS[density if density in DENSITIES else DENSITY_NORMAL][name]


def chart_font(role: str, *, bold: bool = False) -> QFont:
    font = QFont()
    font.setFamilies(list(UI_FONT_FAMILIES))
    font.setPointSize(CHART_FONT_PT[role])
    if bold:
        font.setWeight(QFont.Weight.DemiBold)
    return font


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
    range_band: str
    range_edge: str


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
    range_band="#6f9a7b",
    range_edge="#7f9c88",
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
    range_band="#9cc4a8",
    range_edge="#7d9a86",
)

LIGHT_STYLE = """
QWidget {
    font-family: @FONT_UI@;
    font-size: @FS_BODY@px;
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
    font-size: @FS_PAGE_TITLE@px;
    font-weight: 700;
    color: #1d1d1f;
    background: transparent;
}
QLabel#PageSubtitle {
    font-size: @FS_BODY@px;
    color: #6e6e73;
    background: transparent;
}
QPushButton#NavButton {
    text-align: left;
    border: none;
    border-radius: 10px;
    padding: @PAD_BUTTON@;
    min-height: 20px;
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
    font-size: @FS_SECTION_TITLE@px;
    font-weight: 700;
    color: #1d1d1f;
    background: transparent;
}
QLabel#Subtitle {
    font-size: @FS_BODY@px;
    color: #007aff;
    font-weight: 600;
    background: transparent;
}
QLabel#Muted {
    color: #6e6e73;
    background: transparent;
    font-size: @FS_LABEL@px;
}
QLabel#StatLabel {
    color: #6e6e73;
    font-size: @FS_MICRO@px;
    font-weight: 600;
    letter-spacing: 0.4px;
    background: transparent;
}
QLabel#StatValue {
    font-size: @FS_METRIC@px;
    font-weight: 700;
    color: #1d1d1f;
    background: transparent;
}
QLabel#Alert {
    color: #c0392b;
    font-weight: 600;
    font-size: @FS_LABEL@px;
    background: transparent;
}
QLabel#Hint {
    color: #6e6e73;
    font-size: @FS_HINT@px;
    font-weight: 600;
    background: transparent;
}
QLabel#OverlayDelta {
    color: #5856d6;
    font-size: @FS_CAPTION@px;
    font-weight: 600;
    background: transparent;
}
QLabel#DerivedValue {
    color: #6e6e73;
    font-size: @FS_LABEL@px;
    background: transparent;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #d2d2d7;
    border-radius: 12px;
    padding: @PAD_BUTTON@;
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
QPushButton#Secondary, QToolButton#Secondary {
    background: #ffffff;
    border: 1px solid #c7c7cc;
    min-height: 20px;
    padding: @PAD_SECONDARY@;
}
QPushButton#Secondary:hover, QToolButton#Secondary:hover {
    background: #f2f2f7;
    border-color: #8e8e93;
}
QPushButton#Secondary:pressed, QToolButton#Secondary:pressed {
    background: #e5e5ea;
}
QPushButton#Secondary:focus, QToolButton#Secondary:focus {
    border: 2px solid #007aff;
}
QPushButton#Secondary:disabled, QToolButton#Secondary:disabled {
    color: #a1a1a6;
    background: #f2f2f7;
    border-color: #d2d2d7;
}
QPushButton#Segment {
    background: #ffffff;
    border: 1px solid #c7c7cc;
    min-height: 20px;
    padding: @PAD_SEGMENT@;
    font-weight: 600;
}
QPushButton#Segment:hover {
    background: #f2f2f7;
    border-color: #8e8e93;
}
QPushButton#Segment:checked {
    background: #007aff;
    color: #ffffff;
    border: none;
}
QToolButton#Secondary {
    border-radius: 12px;
    font-weight: 600;
    padding: @PAD_TOOL@;
}
QToolButton#Secondary::menu-indicator {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 12px;
    height: 8px;
    image: url("@CHEVRON_ICON@");
}
QToolButton#ChartNav {
    background: #ffffff;
    border: 1px solid #c7c7cc;
    min-width: 28px;
    max-width: 32px;
    min-height: 28px;
    max-height: 32px;
    padding: 4px;
    border-radius: 8px;
}
QToolButton#ChartNav:hover {
    background: #f2f2f7;
    border-color: #8e8e93;
}
QToolButton#ChartNav:pressed {
    background: #e5e5ea;
}
QToolButton#ChartNav:focus {
    border: 2px solid #007aff;
}
QRadioButton, QCheckBox {
    background: transparent;
    spacing: 10px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #8e8e93;
    border-radius: 4px;
    background: #ffffff;
}
QCheckBox::indicator:hover {
    border-color: #007aff;
}
QCheckBox::indicator:checked {
    border-color: #007aff;
    background: #007aff;
    image: url("@CHECK_ICON@");
}
QCheckBox::indicator:checked:hover {
    border-color: #0066d6;
    background: #0066d6;
}
QCheckBox::indicator:disabled {
    border-color: #d2d2d7;
    background: #f2f2f7;
}
QCheckBox::indicator:checked:disabled {
    border-color: #c7c7cc;
    background: #c7c7cc;
}
QCheckBox:focus {
    outline: none;
}
QCheckBox::indicator:focus {
    border-color: #007aff;
}
QComboBox, QLineEdit, QSpinBox {
    background: #ffffff;
    border: 1px solid #d2d2d7;
    border-radius: 10px;
    padding: @PAD_INPUT@;
    min-height: 18px;
}
QComboBox {
    padding: @PAD_COMBO@;
}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover {
    border-color: #8e8e93;
}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {
    border: 2px solid #007aff;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 28px;
    border: none;
    background: transparent;
}
QComboBox::down-arrow {
    width: 12px;
    height: 8px;
    image: url("@CHEVRON_ICON@");
}
QTextEdit {
    background: #fbfbfd;
    border: 1px solid #e5e5ea;
    border-radius: 12px;
    padding: 8px;
    font-family: @FONT_MONO@;
    font-size: @FS_CAPTION@px;
}
QTextEdit#ResultsEvidence {
    font-size: @FS_LABEL@px;
}
QListWidget {
    background: #ffffff;
    border: 1px solid #e5e5ea;
    border-radius: 10px;
    padding: 4px;
}
QTabWidget#ResultsTabs::pane {
    border: none;
    background: transparent;
    top: 8px;
}
QTabWidget#ResultsTabs QTabBar::tab {
    background: #f2f2f7;
    color: #3a3a3c;
    border: 1px solid #d2d2d7;
    border-bottom: none;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    padding: @PAD_SEGMENT@;
    margin-right: 4px;
    font-weight: 600;
}
QTabWidget#ResultsTabs QTabBar::tab:selected {
    background: #ffffff;
    color: #007aff;
}
QTableWidget#ResultsClickTable {
    background: #ffffff;
    border: 1px solid #e5e5ea;
    border-radius: 10px;
    gridline-color: #e5e5ea;
    font-size: @FS_LABEL@px;
}
QTableWidget#ResultsClickTable::item:selected {
    background: #e8f1ff;
    color: #1d1d1f;
}
QTableWidget#ResultsClickTable QHeaderView::section {
    background: #f5f5f7;
    color: #6e6e73;
    border: none;
    border-bottom: 1px solid #e5e5ea;
    padding: 6px 8px;
    font-weight: 600;
}
QLabel#RailBrand {
    font-size: @FS_SECTION_TITLE@px;
    font-weight: 700;
    letter-spacing: 1px;
    color: #007aff;
    background: transparent;
}
QLabel#RailProduct {
    font-size: @FS_CAPTION@px;
    color: #6e6e73;
    background: transparent;
}
QLabel#CardTitle {
    font-size: @FS_LABEL@px;
    font-weight: 700;
    letter-spacing: 0.6px;
    color: #3a3a3c;
    background: transparent;
}
QLabel#FieldLabel {
    font-size: @FS_LABEL@px;
    font-weight: 600;
    color: #48484a;
    background: transparent;
}
QLabel#ProfileStatus {
    font-size: @FS_BODY@px;
    color: #6e6e73;
    background: transparent;
}
QLabel#ProfileStatus[state="error"] {
    color: #c0392b;
    font-weight: 600;
}
QLabel#ProfileStatus[state="locked"] {
    color: #248a3d;
    font-weight: 600;
}
QLabel#PreviewValue {
    font-size: @FS_EMPHASIS@px;
    font-weight: 600;
    color: #1d1d1f;
    background: transparent;
}
QWidget#SetupPage QLineEdit, QWidget#SetupPage QComboBox, QWidget#PreferencesPage QComboBox,
QWidget#PreferencesPage QSpinBox {
    min-height: 20px;
}
QWidget#SetupPage QLineEdit:disabled, QWidget#SetupPage QComboBox:disabled {
    background: #f2f2f7;
    color: #8e8e93;
}
"""

DARK_STYLE = """
QWidget {
    font-family: @FONT_UI@;
    font-size: @FS_BODY@px;
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
    font-size: @FS_PAGE_TITLE@px;
    font-weight: 700;
    color: #f5f5f7;
    background: transparent;
}
QLabel#PageSubtitle {
    font-size: @FS_BODY@px;
    color: #98989d;
    background: transparent;
}
QPushButton#NavButton {
    text-align: left;
    border: none;
    border-radius: 10px;
    padding: @PAD_BUTTON@;
    min-height: 20px;
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
    font-size: @FS_SECTION_TITLE@px;
    font-weight: 700;
    color: #f5f5f7;
    background: transparent;
}
QLabel#Subtitle {
    font-size: @FS_BODY@px;
    color: #0a84ff;
    font-weight: 600;
    background: transparent;
}
QLabel#Muted {
    color: #98989d;
    background: transparent;
    font-size: @FS_LABEL@px;
}
QLabel#StatLabel {
    color: #98989d;
    font-size: @FS_MICRO@px;
    font-weight: 600;
    letter-spacing: 0.4px;
    background: transparent;
}
QLabel#StatValue {
    font-size: @FS_METRIC@px;
    font-weight: 700;
    color: #f5f5f7;
    background: transparent;
}
QLabel#Alert {
    color: #ff6961;
    font-weight: 600;
    font-size: @FS_LABEL@px;
    background: transparent;
}
QLabel#Hint {
    color: #98989d;
    font-size: @FS_HINT@px;
    font-weight: 600;
    background: transparent;
}
QLabel#OverlayDelta {
    color: #5e5ce6;
    font-size: @FS_CAPTION@px;
    font-weight: 600;
    background: transparent;
}
QLabel#DerivedValue {
    color: #98989d;
    font-size: @FS_LABEL@px;
    background: transparent;
}
QPushButton {
    background: #2c2c2e;
    border: 1px solid #48484a;
    border-radius: 12px;
    padding: @PAD_BUTTON@;
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
QPushButton#Secondary, QToolButton#Secondary {
    background: #2c2c2e;
    border: 1px solid #636366;
    min-height: 20px;
    padding: @PAD_SECONDARY@;
    color: #f5f5f7;
}
QPushButton#Secondary:hover, QToolButton#Secondary:hover {
    background: #3a3a3c;
    border-color: #8e8e93;
}
QPushButton#Secondary:pressed, QToolButton#Secondary:pressed {
    background: #48484a;
}
QPushButton#Secondary:focus, QToolButton#Secondary:focus {
    border: 2px solid #0a84ff;
}
QPushButton#Secondary:disabled, QToolButton#Secondary:disabled {
    color: #636366;
    background: #1c1c1e;
    border-color: #3a3a3c;
}
QPushButton#Segment {
    background: #2c2c2e;
    border: 1px solid #636366;
    min-height: 20px;
    padding: @PAD_SEGMENT@;
    font-weight: 600;
    color: #f5f5f7;
}
QPushButton#Segment:hover {
    background: #3a3a3c;
    border-color: #8e8e93;
}
QPushButton#Segment:checked {
    background: #0a84ff;
    color: #ffffff;
    border: none;
}
QToolButton#Secondary {
    border-radius: 12px;
    font-weight: 600;
    padding: @PAD_TOOL@;
}
QToolButton#Secondary::menu-indicator {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 12px;
    height: 8px;
    image: url("@CHEVRON_ICON@");
}
QToolButton#ChartNav {
    background: #2c2c2e;
    border: 1px solid #636366;
    color: #f5f5f7;
    min-width: 28px;
    max-width: 32px;
    min-height: 28px;
    max-height: 32px;
    padding: 4px;
    border-radius: 8px;
}
QToolButton#ChartNav:hover {
    background: #3a3a3c;
    border-color: #8e8e93;
}
QToolButton#ChartNav:pressed {
    background: #48484a;
}
QToolButton#ChartNav:focus {
    border: 2px solid #0a84ff;
}
QRadioButton, QCheckBox {
    background: transparent;
    color: #f5f5f7;
    spacing: 10px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #8e8e93;
    border-radius: 4px;
    background: #2c2c2e;
}
QCheckBox::indicator:hover {
    border-color: #0a84ff;
}
QCheckBox::indicator:checked {
    border-color: #0a84ff;
    background: #0a84ff;
    image: url("@CHECK_ICON@");
}
QCheckBox::indicator:checked:hover {
    border-color: #409cff;
    background: #409cff;
}
QCheckBox::indicator:disabled {
    border-color: #48484a;
    background: #1c1c1e;
}
QCheckBox::indicator:checked:disabled {
    border-color: #48484a;
    background: #48484a;
}
QCheckBox:focus {
    outline: none;
}
QCheckBox::indicator:focus {
    border-color: #0a84ff;
}
QComboBox, QLineEdit, QSpinBox {
    background: #2c2c2e;
    border: 1px solid #48484a;
    border-radius: 10px;
    padding: @PAD_INPUT@;
    min-height: 18px;
    color: #f5f5f7;
}
QComboBox {
    padding: @PAD_COMBO@;
}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover {
    border-color: #8e8e93;
}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {
    border: 2px solid #0a84ff;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 28px;
    border: none;
    background: transparent;
}
QComboBox::down-arrow {
    width: 12px;
    height: 8px;
    image: url("@CHEVRON_ICON@");
}
QTextEdit {
    background: #2c2c2e;
    border: 1px solid #3a3a3c;
    border-radius: 12px;
    padding: 8px;
    font-family: @FONT_MONO@;
    font-size: @FS_CAPTION@px;
    color: #f5f5f7;
}
QTextEdit#ResultsEvidence {
    font-size: @FS_LABEL@px;
}
QListWidget {
    background: #2c2c2e;
    border: 1px solid #3a3a3c;
    border-radius: 10px;
    padding: 4px;
    color: #f5f5f7;
}
QTabWidget#ResultsTabs::pane {
    border: none;
    background: transparent;
    top: 8px;
}
QTabWidget#ResultsTabs QTabBar::tab {
    background: #1c1c1e;
    color: #98989d;
    border: 1px solid #3a3a3c;
    border-bottom: none;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    padding: @PAD_SEGMENT@;
    margin-right: 4px;
    font-weight: 600;
}
QTabWidget#ResultsTabs QTabBar::tab:selected {
    background: #2c2c2e;
    color: #0a84ff;
}
QTableWidget#ResultsClickTable {
    background: #1c1c1e;
    border: 1px solid #3a3a3c;
    border-radius: 10px;
    gridline-color: #3a3a3c;
    color: #f5f5f7;
    font-size: @FS_LABEL@px;
}
QTableWidget#ResultsClickTable::item:selected {
    background: #1a3a5c;
    color: #f5f5f7;
}
QTableWidget#ResultsClickTable QHeaderView::section {
    background: #2c2c2e;
    color: #98989d;
    border: none;
    border-bottom: 1px solid #3a3a3c;
    padding: 6px 8px;
    font-weight: 600;
}
QLabel#RailBrand {
    font-size: @FS_SECTION_TITLE@px;
    font-weight: 700;
    letter-spacing: 1px;
    color: #0a84ff;
    background: transparent;
}
QLabel#RailProduct {
    font-size: @FS_CAPTION@px;
    color: #98989d;
    background: transparent;
}
QLabel#CardTitle {
    font-size: @FS_LABEL@px;
    font-weight: 700;
    letter-spacing: 0.6px;
    color: #d1d1d6;
    background: transparent;
}
QLabel#FieldLabel {
    font-size: @FS_LABEL@px;
    font-weight: 600;
    color: #c7c7cc;
    background: transparent;
}
QLabel#ProfileStatus {
    font-size: @FS_BODY@px;
    color: #98989d;
    background: transparent;
}
QLabel#ProfileStatus[state="error"] {
    color: #ff6961;
    font-weight: 600;
}
QLabel#ProfileStatus[state="locked"] {
    color: #30d158;
    font-weight: 600;
}
QLabel#PreviewValue {
    font-size: @FS_EMPHASIS@px;
    font-weight: 600;
    color: #f5f5f7;
    background: transparent;
}
QWidget#SetupPage QLineEdit, QWidget#SetupPage QComboBox, QWidget#PreferencesPage QComboBox,
QWidget#PreferencesPage QSpinBox {
    min-height: 20px;
}
QWidget#SetupPage QLineEdit:disabled, QWidget#SetupPage QComboBox:disabled {
    background: #1c1c1e;
    color: #636366;
}
"""

ASSET_DIR = Path(__file__).resolve().parent / "assets"
# Qt style sheets cannot load data: URIs, so indicator images come from package files.
STYLE_ASSETS: dict[str, dict[str, str]] = {
    "light": {"@CHECK_ICON@": "check_white.svg", "@CHEVRON_ICON@": "chevron_down_light.svg"},
    "dark": {"@CHECK_ICON@": "check_white.svg", "@CHEVRON_ICON@": "chevron_down_dark.svg"},
}


def style_asset_path(name: str) -> Path:
    return ASSET_DIR / name


CHART_NAV_ICONS = {
    "fit": "chart_fit.svg",
    "zoom_in": "chart_zoom_in.svg",
    "zoom_out": "chart_zoom_out.svg",
    "reset": "chart_reset.svg",
}


def chart_nav_icon(name: str, *, dark: bool = False, size: int = 18):
    """Monochrome SVG icon. Returns an empty QIcon if the asset cannot load."""
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QIcon, QPainter, QPixmap

    path = style_asset_path(CHART_NAV_ICONS.get(name, name))
    icon = QIcon()
    if not path.is_file():
        return icon
    try:
        from PySide6.QtSvg import QSvgRenderer
    except Exception:
        return icon
    try:
        color = "#f5f5f7" if dark else "#1d1d1f"
        data = path.read_text(encoding="utf-8").replace("currentColor", color)
        renderer = QSvgRenderer(QByteArray(data.encode("utf-8")))
        if not renderer.isValid():
            return icon
        pix = QPixmap(size * 2, size * 2)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pix)
    except Exception:
        return QIcon()
    return icon


def density_tokens(density: str = DENSITY_NORMAL) -> dict[str, str]:
    key = density if density in DENSITIES else DENSITY_NORMAL
    tokens = {"@FONT_UI@": UI_FONT_STACK, "@FONT_MONO@": MONO_FONT_STACK}
    for role, px in TYPE_SCALE[key].items():
        tokens[f"@FS_{role.upper()}@"] = str(px)
    for role, value in CONTROL_PADDING[key].items():
        tokens[f"@PAD_{role.upper()}@"] = value
    return tokens


def get_style(theme: str, density: str = DENSITY_NORMAL) -> str:
    key = "dark" if theme == "dark" else "light"
    sheet = DARK_STYLE if key == "dark" else LIGHT_STYLE
    for token, name in STYLE_ASSETS[key].items():
        sheet = sheet.replace(token, style_asset_path(name).as_posix())
    for token, value in density_tokens(density).items():
        sheet = sheet.replace(token, value)
    return sheet


def get_palette(theme: str) -> ChartPalette:
    return DARK_PALETTE if theme == "dark" else LIGHT_PALETTE


APP_STYLE = get_style("light")  # backward compat
