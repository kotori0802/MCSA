"""PySide6 MainWindow — Apple-inspired shell over existing MCSA core."""
from __future__ import annotations

import copy
import json
import logging
import math
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QButtonGroup,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from ..adapters.raw_input_subprocess import WindowsRawInputSubprocess
from ..app import (
    ARMING_SEC,
    RULE_PRESETS,
    annotate_events,
    build_payload,
    normalize_auto_settings,
    write_reports,
    _is_manual_profile,
    _metrics_issue_tags,
    _now_run_id,
    _result_from_tags,
    _verify_artifacts,
)
from ..cadence import cadence_ms, delta_cards, ranking_metrics
from ..core import now_iso
from ..host_evidence import HostEvidenceError, build_fixture_host_evidence
from ..i18n import LANG_LABELS, SUPPORTED_LANGS, t
from ..overlay_io import OverlayLoadError, extract_overlay_events, load_overlay_payload
from ..schema import TOOL_NAME
from .charts import IntervalChart, ScatterChart
from .styles import get_palette, get_style

_log = logging.getLogger(__name__)


def _finite_raw_time_perf(event: dict[str, Any]) -> float | None:
    """Return the Raw Input perf stamp only if present, numeric, and finite."""
    raw = event.get("time_perf")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def parse_auto_stop_seconds(enabled: bool, raw: Any) -> float | None:
    """Return auto-stop offset in seconds, or None if auto-stop is off.

    When auto-stop is disabled the seconds field is ignored, including
    invalid text. When enabled, the field must be a finite positive number.
    """
    if not enabled:
        return None
    if raw is None:
        raise ValueError("Auto Stop seconds must be a finite positive number")
    text = str(raw).strip()
    try:
        sec = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("Auto Stop seconds must be a finite positive number") from exc
    if not math.isfinite(sec) or sec <= 0.0:
        raise ValueError("Auto Stop seconds must be a finite positive number")
    return sec


def parse_reference_rate_hz(raw: Any) -> float:
    """Parse a tester-configured Reference Rate in Hz.

    Accepts finite numbers greater than zero. Does not snap to presets
    and does not substitute a default for invalid input.
    """
    if raw is None or isinstance(raw, bool):
        raise ValueError("Reference Rate must be a finite positive number")
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ValueError("Reference Rate must be a finite positive number")
        try:
            hz = float(text)
        except ValueError as exc:
            raise ValueError("Reference Rate must be a finite positive number") from exc
    else:
        try:
            hz = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("Reference Rate must be a finite positive number") from exc
    if not math.isfinite(hz) or hz <= 0.0:
        raise ValueError("Reference Rate must be a finite positive number")
    return hz


def stamp_qt_reference_rate(
    settings: dict[str, Any],
    *,
    manual: bool,
    reference_rate_hz: float,
) -> dict[str, Any]:
    """Map Qt Reference Rate onto temporary legacy fixture_hz fields."""
    out = dict(settings)
    if manual:
        out["fixture_hz"] = 0.0
        out["fixture_reference_hz"] = 0.0
    else:
        out["fixture_hz"] = reference_rate_hz
        out["fixture_reference_hz"] = reference_rate_hz
        out["profile_name"] = "Fixture_Custom"
    return out


def contain_qt_runtime_click_expectation(
    settings: dict[str, Any],
    auto_stop_sec: float | None,
) -> dict[str, Any]:
    """Neutralize duration-derived click counts for the Qt live/runtime path.

    Auto Stop seconds only control when recording stops. They must not create
    an expected click count. Auto Stop OFF must not expose a fake 60 s duration.
    """
    out = dict(settings)
    out["target_clicks"] = 0
    out["expected_clicks"] = 0
    out["expected_clicks_auto"] = 0
    if auto_stop_sec is None:
        out["duration_sec"] = 0
    else:
        out["duration_sec"] = auto_stop_sec
    return out


def qt_button_label(text: Any) -> str:
    """Escape '&' so QPushButton shows a literal ampersand."""
    return str(text).replace("&", "&&")


def setup_controls_editable(*, running: bool, completed: bool, profile_locked: bool = False) -> bool:
    """Setup is editable only in Draft: not locked, not running, not completed."""
    return (not running) and (not completed) and (not profile_locked)


class ProfileValidationError(ValueError):
    """Setup profile failed validation. ``key`` is an i18n message key."""

    def __init__(self, key: str):
        super().__init__(key)
        self.key = key


QT_CUSTOM_LIMIT_KEYS: tuple[str, ...] = (
    "chatter_threshold_ms",
    "duplicate_click_threshold_ms",
    "fixture_actuation_too_short_ms",
    "low_hold_warning_ms",
    "interval_cv_limit_pct",
)

_QT_CUSTOM_LIMIT_LABEL_KEYS: dict[str, str] = {
    "chatter_threshold_ms": "limit_chatter_ms",
    "duplicate_click_threshold_ms": "limit_double_click_ms",
    "fixture_actuation_too_short_ms": "limit_actuation_short_ms",
    "low_hold_warning_ms": "limit_low_hold_ms",
    "interval_cv_limit_pct": "limit_interval_cv_pct",
}


class QtCustomLimitsError(ValueError):
    """Invalid Custom Limits input. code is 'numeric' or 'order'."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def qt_custom_limit_defaults() -> dict[str, float]:
    """Copy of RULE_PRESETS['Strict'] numeric keys. Migration default only."""
    src = dict(RULE_PRESETS.get("Strict") or {})
    return {key: float(src[key]) for key in QT_CUSTOM_LIMIT_KEYS}


def _parse_positive_custom_limit(raw: Any) -> float:
    if raw is None or isinstance(raw, bool):
        raise QtCustomLimitsError("numeric", "Custom Limits must be finite positive numbers.")
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise QtCustomLimitsError("numeric", "Custom Limits must be finite positive numbers.")
        try:
            value = float(text)
        except ValueError as exc:
            raise QtCustomLimitsError("numeric", "Custom Limits must be finite positive numbers.") from exc
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise QtCustomLimitsError("numeric", "Custom Limits must be finite positive numbers.") from exc
    if not math.isfinite(value) or value <= 0.0:
        raise QtCustomLimitsError("numeric", "Custom Limits must be finite positive numbers.")
    return value


def parse_qt_custom_limits(raw_values: Any) -> dict[str, float]:
    """Parse tester-configured Custom Limits. Does not snap or default invalid input."""
    if not isinstance(raw_values, dict):
        raise QtCustomLimitsError("numeric", "Custom Limits must be finite positive numbers.")
    out: dict[str, float] = {}
    for key in QT_CUSTOM_LIMIT_KEYS:
        if key not in raw_values:
            raise QtCustomLimitsError("numeric", "Custom Limits must be finite positive numbers.")
        out[key] = _parse_positive_custom_limit(raw_values[key])
    if not (out["chatter_threshold_ms"] < out["duplicate_click_threshold_ms"]):
        raise QtCustomLimitsError(
            "order",
            "Chatter must be below double-click, and actuation-too-short must be below low-hold warning.",
        )
    if not (out["fixture_actuation_too_short_ms"] < out["low_hold_warning_ms"]):
        raise QtCustomLimitsError(
            "order",
            "Chatter must be below double-click, and actuation-too-short must be below low-hold warning.",
        )
    return out


def stamp_qt_custom_limit_metadata(
    settings: dict[str, Any],
    *,
    manual: bool,
) -> dict[str, Any]:
    """Neutral Custom Limits metadata after legacy normalize_auto_settings."""
    out = dict(settings)
    out["judgement_mode"] = "Custom"
    if not manual:
        out["test_profile"] = "Fixture Custom"
    return out


def qt_explicit_limit_snapshot(settings: dict[str, Any] | None) -> dict[str, float]:
    """Copy only the five visible Custom Limit values. No cadence transform, no defaults."""
    src = settings or {}
    out: dict[str, float] = {}
    for key in QT_CUSTOM_LIMIT_KEYS:
        if key not in src or src.get(key) is None:
            continue
        out[key] = float(src[key])
    return out


def stamp_qt_explicit_limits(
    settings: dict[str, Any],
    limits: dict[str, float],
) -> dict[str, Any]:
    """Re-apply tester-configured Custom Limits after legacy normalize."""
    out = dict(settings)
    for key in QT_CUSTOM_LIMIT_KEYS:
        if key in limits:
            out[key] = float(limits[key])
    return out


FIXTURE_TIMING_TOLERANCE_KEY = "fixture_timing_tolerance_ms"


def parse_fixture_timing_tolerance_ms(raw: Any) -> float:
    """Parse the tester-configured Fixture Timing Tolerance (± ms).

    Accepts 0 and any finite positive number. No default, clamp, rounding,
    maximum, or frequency-derived value. Distinct from legacy
    ``fixture_match_tolerance_ms``.
    """
    message = "Fixture Timing Tolerance must be a finite number >= 0"
    if raw is None or isinstance(raw, bool):
        raise ValueError(message)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ValueError(message)
        try:
            value = float(text)
        except ValueError as exc:
            raise ValueError(message) from exc
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(message) from exc
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(message)
    return value


def stamp_qt_fixture_timing_tolerance(
    settings: dict[str, Any],
    *,
    manual: bool,
    tolerance_ms: float | None,
) -> dict[str, Any]:
    """Stamp the V2 Fixture Timing Tolerance after legacy normalize.

    None means not applicable (Manual) or not configured; 0.0 is a real
    configured tolerance and is never used as a placeholder.
    """
    out = dict(settings)
    out[FIXTURE_TIMING_TOLERANCE_KEY] = None if manual or tolerance_ms is None else float(tolerance_ms)
    return out


_HOST_EVIDENCE_NONE_TEXT = "—"


def _fmt_signed_ms(value: Any) -> str:
    if value is None:
        return _HOST_EVIDENCE_NONE_TEXT
    number = float(value)
    return "0.000" if number == 0.0 else f"{number:+.3f}"


def _fmt_unsigned_ms(value: Any) -> str:
    if value is None:
        return _HOST_EVIDENCE_NONE_TEXT
    return f"{float(value):.3f}"


def _fmt_signed_count(value: int) -> str:
    return "0" if value == 0 else f"{value:+d}"


def format_host_evidence_review_lines(snapshot: dict[str, Any] | None, tr) -> list[str]:
    """Display lines for a frozen Host Evidence snapshot. Formatting only.

    ``tr(key, **kwargs)`` returns translated text. No snapshot → no lines, so
    Manual / Auto Stop OFF runs never show schedule or count placeholders.
    """
    if not snapshot:
        return []
    config = snapshot["configuration"]
    counts = snapshot["counts"]
    matching = snapshot["matching"]
    delta = snapshot["timing"]["matched_delta_stats"]
    abs_delta = snapshot["timing"]["matched_absolute_delta_stats"]
    lines = [
        tr("he_title"),
        tr(
            "he_config",
            hz=f"{float(config['fixture_frequency_hz']):g}",
            duration=f"{float(config['capture_duration_s']):.3f}",
            tol=f"{float(config['timing_tolerance_ms']):.3f}",
            ref=f"{float(config['reference_interval_ms']):.3f}",
        ),
        tr(
            "he_counts",
            expected=counts["expected_slot_count"],
            in_window=counts["in_window_host_press_count"],
            delta=_fmt_signed_count(int(counts["host_count_delta_vs_expected_slots"])),
            raw=counts["raw_host_press_count"],
        ),
        tr(
            "he_windows",
            empty=matching["empty_expected_slot_count"],
            single=matching["single_occupancy_slot_count"],
            multi=matching["multi_occupancy_slot_count"],
        ),
        tr(
            "he_observations",
            matched=matching["matched_host_observation_count"],
            unmatched=matching["unmatched_host_observation_count"],
            ambiguous=matching["ambiguous_host_observation_count"],
            outside=matching["outside_capture_window_observation_count"],
        ),
        tr(
            "he_timing",
            avg=_fmt_signed_ms(delta["average"]),
            min=_fmt_signed_ms(delta["minimum"]),
            max=_fmt_signed_ms(delta["maximum"]),
            sd=_fmt_unsigned_ms(delta["stdev"]),
            abs_avg=_fmt_unsigned_ms(abs_delta["average"]),
        ),
    ]
    if config.get("matching_windows_can_overlap"):
        lines.append(tr("he_overlap"))
    return lines


_QT_ALERT_TAGS = (
    "FIXTURE_HZ_MISMATCH",
    "HIGH_PROBABILITY_DOUBLE_CLICK",
    "CHATTER_HARD",
)


_QT_HIDDEN_PRESENTATION_TAGS = frozenset({"OPERATOR_FATIGUE", "HOLD_VARIATION_WARN"})

# Exact prefix from core.compute_metrics hold_cv_limit_pct reason strings.
_HOLD_CV_HEALTH_REASON_PREFIX = "hold_cv_pct "


def _reason_is_hidden_hold_cv(reason: Any) -> bool:
    return str(reason or "").startswith(_HOLD_CV_HEALTH_REASON_PREFIX)


def _legacy_health_is_exclusively_hidden_hold_cv(metrics: dict[str, Any]) -> bool:
    """True only when structured core reasons exist and every one is hold-CV.

    core.compute_metrics health is aggregate. Mixed or missing reasons cannot
    be rewritten without inventing a reconstruction formula.
    """
    fail = [str(r) for r in (metrics.get("fail_reasons") or []) if str(r or "").strip()]
    warn = [str(r) for r in (metrics.get("warn_reasons") or []) if str(r or "").strip()]
    if not fail and not warn:
        return False
    return all(_reason_is_hidden_hold_cv(r) for r in fail + warn)


def qt_present_issue_tags(tags: Any) -> list[str]:
    """Primary Qt live/review tag list.

    Hides OPERATOR_FATIGUE (retired Segment inference) and HOLD_VARIATION_WARN
    (driven by unexposed hold_cv_limit_pct). Does not mutate the input list.
    """
    out: list[str] = []
    for tag in tags or []:
        name = str(tag or "").strip()
        if not name or name in _QT_HIDDEN_PRESENTATION_TAGS:
            continue
        out.append(name)
    return out


def qt_visible_verdict(
    tags: Any,
    metrics: dict[str, Any] | None,
    settings: dict[str, Any] | None = None,
) -> str:
    """Primary Qt live/review verdict from presentation tags.

    Does not mutate the legacy tag list or metrics. OPERATOR_FATIGUE and
    HOLD_VARIATION_WARN cannot drive the visible VERDICT. metrics.health is
    kept unless structured fail/warn reasons prove it is exclusively hidden
    hold-CV.
    """
    m = dict(metrics or {})
    if int(m.get("click_count") or m.get("actual_clicks") or 0) <= 0:
        return "IDLE"
    if _legacy_health_is_exclusively_hidden_hold_cv(m):
        m.pop("health", None)
    return _result_from_tags(qt_present_issue_tags(tags), m, settings)


class CaptureBridge(QObject):
    """Marshals Raw Input callbacks onto the Qt UI thread."""

    event_received = Signal(dict)


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        report_root: Path,
        target: str = "",
        operator: str = "",
        run_id: str = "",
        lang: str = "en",
        theme: str = "light",
    ):
        super().__init__()
        self.lang = lang if lang in SUPPORTED_LANGS else "en"
        self.theme = theme if theme in ("light", "dark") else "light"
        self.setWindowTitle(t(self.lang, "app_title"))
        self.setMinimumSize(1024, 640)
        self.resize(1280, 840)
        self.report_root = Path(report_root)
        self.report_root.mkdir(parents=True, exist_ok=True)
        self.target = target or ""
        self.operator = operator or ""
        self.run_id = run_id or _now_run_id()

        self.events: list[dict[str, Any]] = []
        self.raw_events: list[dict[str, Any]] = []
        self.device_press_queues: dict[tuple[str, str], deque] = defaultdict(deque)
        self.listening = False
        self.running = False
        self.completed = False
        self.report_written = False
        self.report_paths: dict[str, str] = {}
        self.raw_input: WindowsRawInputSubprocess | None = None
        self.start_time: float | None = None
        self.end_time: float | None = None
        self.stop_time: float | None = None
        self.first_press_time = None
        self.last_press_time = None
        self.first_release_time = None
        self.last_release_time = None
        self.locked: dict[str, Any] | None = None
        self.profile_locked_settings: dict[str, Any] | None = None
        self.profile_locked_target: str = ""
        self._profile_validation_error_key: str | None = None
        self.capture_armed = False
        self.host_evidence_snapshot: dict[str, Any] | None = None
        self._arming_scheduled = False
        self._ignore_arm_until = 0.0
        # Same Windows QPC domain as Raw Input event["time_perf"] (child stamps; parent Auto Stop already compares).
        self._arm_boundary_perf: float | None = None
        self._locked_button = "Left"
        self._last_metric_ts = 0.0
        self.bridge = CaptureBridge()
        self.bridge.event_received.connect(self._on_raw_event_ui)

        self.overlay_events: list[dict[str, Any]] = []
        self.overlay_metrics: dict[str, Any] = {}
        self.overlay_path = ""
        self.session_runs: list[dict[str, Any]] = []
        self._stat_name_labels: dict[str, QLabel] = {}
        self._section_labels: list[QLabel] = []
        self._field_labels: list[QLabel] = []

        self._build_ui()
        self._apply_theme()
        self._retranslate_ui()
        self._apply_mode_fields()
        self._update_controls()
        QShortcut(QKeySequence("F5"), self, activated=self.stop_run)
        QShortcut(QKeySequence("Esc"), self, activated=self.stop_run)

        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(100)
        self.ui_timer.timeout.connect(self._tick)
        self.ui_timer.start()
        self._listen_start_timer = QTimer(self)
        self._listen_start_timer.setSingleShot(True)
        self._listen_start_timer.timeout.connect(self.enter_listen)
        self._listen_start_timer.start(150)

    def _tr(self, key: str, **kwargs) -> str:
        return t(self.lang, key, **kwargs)

    def _chart_labels(self) -> dict[str, str]:
        keys = (
            "waiting_data", "axis_interval_ms", "axis_hold_ms", "axis_elapsed_s",
            "legend_on_cadence", "legend_extra", "legend_chatter", "legend_miss",
            "legend_overlay", "legend_target", "chart_interval",
        )
        return {k: self._tr(k) for k in keys}

    def _report_lang(self) -> str:
        return "zh" if self.lang == "zh" else "en"

    # ── UI ──────────────────────────────────────────────────────────
    def _card(self) -> QFrame:
        f = QFrame()
        f.setObjectName("Card")
        return f

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(16)
        outer.addWidget(self._build_nav_rail())

        workspace = QWidget()
        workspace.setObjectName("Workspace")
        work_l = QVBoxLayout(workspace)
        work_l.setContentsMargins(4, 4, 8, 4)
        work_l.setSpacing(12)
        work_l.addLayout(self._build_workspace_header())

        self._workflow_pages = ("setup", "capture", "results", "preferences")
        self._current_page = "setup"
        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("WorkflowStack")
        self.page_setup = self._build_setup_page()
        self.page_capture = self._build_capture_page()
        self.page_results = self._build_results_page()
        self.page_preferences = self._build_preferences_page()
        for page in (self.page_setup, self.page_capture, self.page_results, self.page_preferences):
            self.page_stack.addWidget(page)
        work_l.addWidget(self.page_stack, 1)
        outer.addWidget(workspace, 1)
        self._show_workflow_page("setup")

    def _build_nav_rail(self) -> QFrame:
        rail = QFrame()
        rail.setObjectName("NavRail")
        rail.setFixedWidth(188)
        self.nav_rail = rail
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(8)

        self.title_label = QLabel(TOOL_NAME)
        self.title_label.setObjectName("Title")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addSpacing(12)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self._nav_buttons: dict[str, QPushButton] = {}
        for name, text in (
            ("setup", "Setup"),
            ("capture", "Capture"),
            ("results", "Results"),
            ("preferences", "Preferences"),
        ):
            btn = QPushButton(text)
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, page=name: self._show_workflow_page(page))
            self.nav_group.addButton(btn)
            self._nav_buttons[name] = btn
            layout.addWidget(btn)
        self.nav_setup = self._nav_buttons["setup"]
        self.nav_capture = self._nav_buttons["capture"]
        self.nav_results = self._nav_buttons["results"]
        self.nav_preferences = self._nav_buttons["preferences"]
        self.nav_setup.setChecked(True)
        layout.addStretch(1)

        self.btn_help = QPushButton("Quick Start")
        self.btn_help.setObjectName("Secondary")
        self.btn_help.clicked.connect(self.show_guide)
        layout.addWidget(self.btn_help)
        return rail

    def _build_workspace_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.page_title = QLabel("Setup")
        self.page_title.setObjectName("PageTitle")
        self.page_subtitle = QLabel("")
        self.page_subtitle.setObjectName("PageSubtitle")
        self.page_subtitle.setWordWrap(True)
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        header.addLayout(titles, 1)

        self.lbl_theme = QLabel("Theme")
        self._field_labels.append(self.lbl_theme)
        header.addWidget(self.lbl_theme)
        self.theme_combo = QComboBox()
        self.theme_combo.setMaximumWidth(120)
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.setCurrentIndex(0 if self.theme == "light" else 1)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        header.addWidget(self.theme_combo)

        self.lbl_lang = QLabel("Language")
        self._field_labels.append(self.lbl_lang)
        header.addWidget(self.lbl_lang)
        self.lang_combo = QComboBox()
        self.lang_combo.setMaximumWidth(150)
        for code in SUPPORTED_LANGS:
            self.lang_combo.addItem(LANG_LABELS.get(code, code), code)
        idx = SUPPORTED_LANGS.index(self.lang) if self.lang in SUPPORTED_LANGS else 0
        self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        header.addWidget(self.lang_combo)
        return header

    def _constrain_setup_field(self, widget: QWidget, width: int = 280) -> None:
        widget.setMaximumWidth(width)
        widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def _build_setup_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("SetupPage")
        page_l = QVBoxLayout(page)
        page_l.setContentsMargins(0, 0, 0, 0)

        inner = QWidget()
        inner.setMaximumWidth(1120)
        inner_l = QVBoxLayout(inner)
        inner_l.setContentsMargins(0, 0, 0, 0)
        inner_l.setSpacing(20)

        cards = QHBoxLayout()
        cards.setSpacing(16)

        device_card = self._card()
        device_l = QVBoxLayout(device_card)
        device_l.setContentsMargins(20, 18, 20, 18)
        device_l.setSpacing(8)
        self.lbl_setup = self._section("Device / DUT")
        device_l.addWidget(self.lbl_setup)
        self.lbl_device = QLabel("Device")
        self._field_labels.append(self.lbl_device)
        device_l.addWidget(self.lbl_device)
        self.device_edit = QLineEdit(self.target)
        self.device_edit.setPlaceholderText("Device name (optional)")
        self._constrain_setup_field(self.device_edit)
        device_l.addWidget(self.device_edit)
        self.lbl_button = QLabel("Button")
        self._field_labels.append(self.lbl_button)
        device_l.addWidget(self.lbl_button)
        self.button_combo = QComboBox()
        self.button_combo.addItems(["Left", "Right", "Middle", "X1", "X2"])
        self._constrain_setup_field(self.button_combo)
        device_l.addWidget(self.button_combo)
        device_l.addStretch(1)
        cards.addWidget(device_card, 1)

        config_card = self._card()
        config_l = QVBoxLayout(config_card)
        config_l.setContentsMargins(20, 18, 20, 18)
        config_l.setSpacing(8)
        self.lbl_setup_config = self._section("Test Configuration")
        config_l.addWidget(self.lbl_setup_config)
        mode_row = QHBoxLayout()
        self.radio_manual = QRadioButton("Manual")
        self.radio_fixture = QRadioButton("Fixture")
        self.radio_manual.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.radio_manual)
        self.mode_group.addButton(self.radio_fixture)
        mode_row.addWidget(self.radio_manual)
        mode_row.addWidget(self.radio_fixture)
        mode_row.addStretch(1)
        config_l.addLayout(mode_row)
        self.radio_manual.toggled.connect(self._apply_mode_fields)

        self.hz_label = QLabel("Reference Rate (Hz)")
        self._field_labels.append(self.hz_label)
        config_l.addWidget(self.hz_label)
        self.hz_combo = QComboBox()
        self.hz_combo.setEditable(True)
        self.hz_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.hz_combo.setCompleter(None)
        self.hz_combo.addItems(["5", "10", "20", "40"])
        self.hz_combo.setCurrentText("10")
        self._constrain_setup_field(self.hz_combo)
        config_l.addWidget(self.hz_combo)
        self.hz_combo.currentTextChanged.connect(self._refresh_fixture_mode_label)

        self.timing_tol_label = QLabel("Fixture Timing Tolerance (± ms)")
        self.timing_tol_label.setWordWrap(True)
        self._field_labels.append(self.timing_tol_label)
        config_l.addWidget(self.timing_tol_label)
        self.timing_tol_edit = QLineEdit()
        self.timing_tol_edit.setPlaceholderText("e.g. 2")
        self._constrain_setup_field(self.timing_tol_edit)
        config_l.addWidget(self.timing_tol_edit)

        self.auto_stop_label = QLabel("Auto Stop")
        self._field_labels.append(self.auto_stop_label)
        config_l.addWidget(self.auto_stop_label)
        auto_stop_row = QHBoxLayout()
        auto_stop_row.setSpacing(6)
        self.auto_stop_off = QPushButton("OFF")
        self.auto_stop_on = QPushButton("ON")
        for btn in (self.auto_stop_off, self.auto_stop_on):
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(32)
            auto_stop_row.addWidget(btn)
        self.auto_stop_off.setChecked(True)
        self.auto_stop_on.setChecked(False)
        self.auto_stop_group = QButtonGroup(self)
        self.auto_stop_group.setExclusive(True)
        self.auto_stop_group.addButton(self.auto_stop_off)
        self.auto_stop_group.addButton(self.auto_stop_on)
        self.auto_stop_on.toggled.connect(self._sync_auto_stop_widgets)
        auto_stop_row.addStretch(1)
        config_l.addLayout(auto_stop_row)
        self.auto_stop_sec_label = QLabel("Auto Stop After (s)")
        self._field_labels.append(self.auto_stop_sec_label)
        config_l.addWidget(self.auto_stop_sec_label)
        self.auto_stop_sec_combo = QComboBox()
        self.auto_stop_sec_combo.setEditable(True)
        self.auto_stop_sec_combo.addItems(["30", "60", "120", "300"])
        self.auto_stop_sec_combo.setCurrentText("60")
        self._constrain_setup_field(self.auto_stop_sec_combo)
        config_l.addWidget(self.auto_stop_sec_combo)
        config_l.addStretch(1)
        cards.addWidget(config_card, 1)
        inner_l.addLayout(cards)

        limits_card = self._card()
        limits_l = QVBoxLayout(limits_card)
        limits_l.setContentsMargins(20, 18, 20, 18)
        limits_l.setSpacing(8)
        self.lbl_custom_limits = self._section("CUSTOM LIMITS")
        limits_l.addWidget(self.lbl_custom_limits)
        limits_grid = QGridLayout()
        limits_grid.setContentsMargins(0, 0, 0, 0)
        limits_grid.setHorizontalSpacing(16)
        limits_grid.setVerticalSpacing(8)
        self._limit_edits: dict[str, QLineEdit] = {}
        self._limit_labels: dict[str, QLabel] = {}
        defaults = qt_custom_limit_defaults()
        for index, key in enumerate(QT_CUSTOM_LIMIT_KEYS):
            lab = QLabel({
                "chatter_threshold_ms": "Chatter (ms)",
                "duplicate_click_threshold_ms": "Double-click (ms)",
                "fixture_actuation_too_short_ms": "Actuation short (ms)",
                "low_hold_warning_ms": "Low hold (ms)",
                "interval_cv_limit_pct": "Interval CV (%)",
            }[key])
            lab.setWordWrap(True)
            lab.setObjectName("StatLabel")
            edit = QLineEdit()
            edit.setText(f"{defaults[key]:g}")
            edit.setAlignment(Qt.AlignmentFlag.AlignRight)
            self._constrain_setup_field(edit, 200)
            self._limit_labels[key] = lab
            self._limit_edits[key] = edit
            row, col = divmod(index, 2)
            cell = QVBoxLayout()
            cell.setSpacing(4)
            cell.addWidget(lab)
            cell.addWidget(edit)
            cell_w = QWidget()
            cell_w.setLayout(cell)
            limits_grid.addWidget(cell_w, row, col)
        limits_l.addLayout(limits_grid)
        inner_l.addWidget(limits_card)
        self.lbl_profile_status = QLabel("")
        self.lbl_profile_status.setObjectName("Muted")
        self.lbl_profile_status.setWordWrap(True)
        inner_l.addWidget(self.lbl_profile_status)
        self.btn_lock_profile = QPushButton("Lock Profile & Continue")
        self.btn_lock_profile.setObjectName("Primary")
        self.btn_lock_profile.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lock_profile.clicked.connect(self.lock_profile)
        inner_l.addWidget(self.btn_lock_profile)
        inner_l.addStretch(1)

        wrap = QWidget()
        wrap_l = QHBoxLayout(wrap)
        wrap_l.setContentsMargins(0, 0, 0, 0)
        wrap_l.addWidget(inner)
        wrap_l.addStretch(1)

        self.setup_scroll = QScrollArea()
        self.setup_scroll.setObjectName("PageScroll")
        self.setup_scroll.setWidgetResizable(True)
        self.setup_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setup_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setup_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.setup_scroll.setWidget(wrap)
        page_l.addWidget(self.setup_scroll)
        return page

    def _build_capture_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("CapturePage")
        page_l = QVBoxLayout(page)
        page_l.setContentsMargins(0, 0, 0, 0)
        page_l.setSpacing(12)

        actions = self._card()
        actions_l = QVBoxLayout(actions)
        actions_l.setContentsMargins(16, 12, 16, 12)
        actions_l.setSpacing(8)
        self.lbl_controls = self._section("CONTROLS")
        actions_l.addWidget(self.lbl_controls)
        self.btn_stop = QPushButton("Stop (F5 / Esc)")
        self.btn_stop.setObjectName("Danger")
        self.btn_stop.clicked.connect(self.stop_run)
        self.btn_new = QPushButton("New Run")
        self.btn_new.clicked.connect(self.new_run)
        self.btn_finish = QPushButton("Finish & Generate Report")
        self.btn_finish.setObjectName("Primary")
        self.btn_finish.clicked.connect(self.finish_report)
        self.btn_save = QPushButton("Save Report As…")
        self.btn_save.clicked.connect(self.save_report_as)
        self.btn_overlay = QPushButton("Compare Overlay")
        self.btn_overlay.setObjectName("Secondary")
        self.btn_overlay.clicked.connect(self.load_overlay_run)
        self.btn_clear_overlay = QPushButton("Clear Overlay")
        self.btn_clear_overlay.setObjectName("Secondary")
        self.btn_clear_overlay.clicked.connect(self.clear_overlay)
        self.btn_arm = QPushButton("Arm Capture")
        self.btn_arm.setObjectName("Primary")
        self.btn_arm.clicked.connect(self._on_arm_clicked)
        self.btn_edit_profile = QPushButton("Edit Profile")
        self.btn_edit_profile.setObjectName("Secondary")
        self.btn_edit_profile.clicked.connect(self.edit_profile)
        row1 = QHBoxLayout()
        row2 = QHBoxLayout()
        for btn in (self.btn_stop, self.btn_new, self.btn_finish, self.btn_arm):
            row1.addWidget(btn)
        row1.addStretch(1)
        for btn in (self.btn_save, self.btn_overlay, self.btn_clear_overlay, self.btn_edit_profile):
            row2.addWidget(btn)
        row2.addStretch(1)
        actions_l.addLayout(row1)
        actions_l.addLayout(row2)
        self.capture_actions = actions
        page_l.addWidget(actions)

        live = self._card()
        live_l = QVBoxLayout(live)
        live_l.setContentsMargins(16, 14, 16, 14)
        self.mode_label = QLabel("Manual · Observation")
        self.mode_label.setObjectName("Subtitle")
        live_l.addWidget(self.mode_label)

        stats = QGridLayout()
        stats.setHorizontalSpacing(14)
        stats.setVerticalSpacing(2)
        self.val_phase = self._add_stat(stats, 0, "PHASE", "phase")
        self.val_time = self._add_stat(stats, 1, "TIME", "time")
        self.val_clicks = self._add_stat(stats, 2, "CLICKS", "clicks")
        self.val_interval = self._add_stat(stats, 3, "INTERVAL", "interval")
        self.val_hold = self._add_stat(stats, 4, "HOLD", "hold")
        self.val_verdict = self._add_stat(stats, 5, "VERDICT", "verdict")
        live_l.addLayout(stats)

        issues = QGridLayout()
        self.val_extra = self._add_stat(issues, 0, "EXTRA", "extra")
        self.val_rebound = self._add_stat(issues, 1, "REBOUND", "rebound")
        self.val_delay = self._add_stat(issues, 2, "DELAY", "delay")
        self.val_dut = self._add_stat(issues, 3, "DUT", "dut")
        self.val_setup = self._add_stat(issues, 4, "SETUP", "setup_score")
        live_l.addSpacing(6)
        self.issue_title = QLabel("ISSUES")
        self.issue_title.setObjectName("StatLabel")
        live_l.addWidget(self.issue_title)
        live_l.addLayout(issues)

        self.status_label = QLabel("Click in the Test Area to start.")
        self.status_label.setObjectName("Muted")
        self.alert_label = QLabel("")
        self.alert_label.setObjectName("Alert")
        self.overlay_delta_label = QLabel("")
        self.overlay_delta_label.setObjectName("OverlayDelta")
        live_l.addWidget(self.status_label)
        live_l.addWidget(self.alert_label)
        live_l.addWidget(self.overlay_delta_label)
        page_l.addWidget(live)

        self.test_area = QFrame()
        self.test_area.setObjectName("TestArea")
        self.test_area.setProperty("active", False)
        ta_l = QVBoxLayout(self.test_area)
        self.hint = QLabel("TEST AREA\nClick here with the target button to start\nStop with F5 or Esc")
        self.hint.setObjectName("Hint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ta_l.addWidget(self.hint)
        self.scatter = ScatterChart()
        self.interval_chart = IntervalChart()
        self.scatter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.interval_chart.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        ta_l.addWidget(self.scatter, 3)
        ta_l.addWidget(self.interval_chart, 2)

        self.review_text = QTextEdit()
        self.review_text.setReadOnly(True)
        self.review_text.setMinimumHeight(120)
        self.review_text.hide()

        self.capture_splitter = QSplitter(Qt.Orientation.Vertical)
        self.capture_splitter.setObjectName("CaptureSplitter")
        self.capture_splitter.setChildrenCollapsible(True)
        self.capture_splitter.addWidget(self.test_area)
        self.capture_splitter.addWidget(self.review_text)
        self.capture_splitter.setStretchFactor(0, 3)
        self.capture_splitter.setStretchFactor(1, 1)
        self.capture_splitter.setSizes([1, 0])
        page_l.addWidget(self.capture_splitter, 1)
        return page

    def _build_results_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("ResultsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        card = self._card()
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(24, 24, 24, 24)
        self.results_placeholder = QLabel("")
        self.results_placeholder.setObjectName("Muted")
        self.results_placeholder.setWordWrap(True)
        card_l.addWidget(self.results_placeholder)
        card_l.addStretch(1)
        layout.addWidget(card)
        return page

    def _build_preferences_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("PreferencesPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        card = self._card()
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(24, 24, 24, 24)
        self.preferences_placeholder = QLabel("")
        self.preferences_placeholder.setObjectName("Muted")
        self.preferences_placeholder.setWordWrap(True)
        card_l.addWidget(self.preferences_placeholder)
        card_l.addStretch(1)
        layout.addWidget(card)
        return page

    def _show_workflow_page(self, name: str) -> None:
        """Switch stacked page. Presentation only: no run or evidence rebuild."""
        if name not in self._workflow_pages:
            return
        self._current_page = name
        self.page_stack.setCurrentIndex(self._workflow_pages.index(name))
        btn = self._nav_buttons[name]
        if not btn.isChecked():
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)
        titles = {
            "setup": ("nav_setup", "page_setup_subtitle"),
            "capture": ("nav_capture", "page_capture_subtitle"),
            "results": ("nav_results", "page_results_subtitle"),
            "preferences": ("nav_preferences", "page_preferences_subtitle"),
        }
        title_key, subtitle_key = titles[name]
        self.page_title.setText(self._tr(title_key))
        self.page_subtitle.setText(self._tr(subtitle_key))

    def _set_review_panel_visible(self, visible: bool) -> None:
        if visible:
            self.review_text.show()
            total = max(self.capture_splitter.height(), 400)
            review = max(int(total * 0.34), 180)
            self.capture_splitter.setSizes([max(total - review, 200), review])
        else:
            self.review_text.hide()
            self.capture_splitter.setSizes([1, 0])

    def _section(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("StatLabel")
        self._section_labels.append(lab)
        return lab

    def _add_stat(self, grid: QGridLayout, col: int, name: str, key: str) -> QLabel:
        lab = QLabel(name)
        lab.setObjectName("StatLabel")
        self._stat_name_labels[key] = lab
        val = QLabel("--")
        val.setObjectName("StatValue")
        box = QVBoxLayout()
        box.setSpacing(0)
        box.addWidget(lab)
        box.addWidget(val)
        w = QWidget()
        w.setLayout(box)
        grid.addWidget(w, 0, col)
        return val

    def _apply_theme(self):
        app = QApplication.instance()
        if app:
            app.setStyleSheet(get_style(self.theme))
        pal = get_palette(self.theme)
        labels = self._chart_labels()
        self.scatter.set_theme(pal, labels)
        self.interval_chart.set_theme(pal, labels)

    def _on_theme_changed(self):
        self.theme = self.theme_combo.currentData() or "light"
        self._apply_theme()
        self._retranslate_ui()
        self._update_controls()

    def _on_lang_changed(self):
        self.lang = self.lang_combo.currentData() or "en"
        self._retranslate_ui()
        self._apply_mode_fields()
        self._apply_theme()
        self._refresh_live_texts()
        self._update_controls()

    def _refresh_live_texts(self):
        """Re-apply translated runtime strings (charts, review, overlay, verdict)."""
        if self.completed or self.events:
            self._refresh_metrics(final=self.completed)
        elif self.overlay_path:
            self._update_overlay_deltas({})
        if self.completed:
            settings = self.locked or self.settings()
            annotated = annotate_events(list(self.events), settings)
            payload = build_payload(self.target, self.operator, settings, annotated, run_id=self.run_id)
            m = payload.get("metrics") or {}
            tags = _metrics_issue_tags(m, settings, annotated)
            verdict = qt_visible_verdict(tags, m, settings)
            if verdict == "PASS" and _is_manual_profile(settings):
                self.status_label.setText(self._tr("pass_manual"))
            elif verdict == "WARN":
                self.status_label.setText(self._tr("warn_manual") if _is_manual_profile(settings) else self._tr("warn_fixture"))
            elif verdict == "FAIL":
                self.status_label.setText(self._tr("fail_verdict"))
            elif not self.running:
                self.status_label.setText(self._tr("review_hint"))

    def _retranslate_ui(self):
        self.setWindowTitle(self._tr("app_title"))
        self.title_label.setText(self._tr("app_title"))
        self.nav_setup.setText(self._tr("nav_setup"))
        self.nav_capture.setText(self._tr("nav_capture"))
        self.nav_results.setText(self._tr("nav_results"))
        self.nav_preferences.setText(self._tr("nav_preferences"))
        self.lbl_setup.setText(self._tr("setup_device_section"))
        self.lbl_setup_config.setText(self._tr("setup_config_section"))
        self.lbl_controls.setText(self._tr("controls"))
        self.results_placeholder.setText(self._tr("page_results_placeholder"))
        self.preferences_placeholder.setText(self._tr("page_preferences_placeholder"))
        self.radio_manual.setText(self._tr("manual"))
        self.radio_fixture.setText(self._tr("fixture"))
        self.lbl_device.setText(self._tr("device"))
        self.device_edit.setPlaceholderText(self._tr("device_placeholder"))
        self.lbl_button.setText(self._tr("button"))
        self.hz_label.setText(self._tr("reference_rate_hz"))
        self.timing_tol_label.setText(self._tr("fixture_timing_tolerance_ms"))
        self.timing_tol_edit.setPlaceholderText(self._tr("fixture_timing_tolerance_placeholder"))
        self.auto_stop_label.setText(self._tr("auto_stop"))
        self.auto_stop_sec_label.setText(self._tr("auto_stop_after"))
        self.lbl_custom_limits.setText(self._tr("custom_limits"))
        for key, lab in self._limit_labels.items():
            lab.setText(self._tr(_QT_CUSTOM_LIMIT_LABEL_KEYS[key]))
        self.btn_stop.setText(self._tr("stop"))
        self.btn_new.setText(self._tr("new_run"))
        self.btn_finish.setText(qt_button_label(self._tr("finish_button")))
        self.btn_save.setText(self._tr("save_report_as"))
        self.btn_overlay.setText(self._tr("compare_overlay"))
        self.btn_clear_overlay.setText(self._tr("clear_overlay"))
        self.btn_lock_profile.setText(self._tr("lock_profile_continue"))
        self.btn_edit_profile.setText(self._tr("edit_profile"))
        self.btn_help.setText(self._tr("quick_start"))
        self.lbl_theme.setText(self._tr("theme"))
        self.theme_combo.setItemText(0, self._tr("theme_light"))
        self.theme_combo.setItemText(1, self._tr("theme_dark"))
        self.lbl_lang.setText(self._tr("language"))
        self.issue_title.setText(self._tr("issues"))
        for key, lab in self._stat_name_labels.items():
            lab.setText(self._tr(key).upper() if key not in ("dut", "setup_score") else self._tr(key).upper())
        self.hint.setText(self._tr("test_area_hint"))
        self._sync_auto_stop_widgets()
        self._show_workflow_page(self._current_page)
        self._refresh_lifecycle_presentation()

    # ── Settings / mode ─────────────────────────────────────────────
    def _ui_is_manual(self) -> bool:
        return self.radio_manual.isChecked()

    def _is_manual(self) -> bool:
        snapshot = self.locked if self.locked is not None else self.profile_locked_settings
        if snapshot is not None:
            return bool(snapshot.get("manual_mode"))
        return self._ui_is_manual()

    def _custom_limit_raw_values(self) -> dict[str, str]:
        return {key: self._limit_edits[key].text() for key in QT_CUSTOM_LIMIT_KEYS}

    def _apply_mode_fields(self):
        manual = self._ui_is_manual()
        self.hz_label.setVisible(not manual)
        self.hz_combo.setVisible(not manual)
        self.timing_tol_label.setVisible(not manual)
        self.timing_tol_edit.setVisible(not manual)
        self.auto_stop_label.setVisible(not manual)
        self.auto_stop_off.setVisible(not manual)
        self.auto_stop_on.setVisible(not manual)
        self._sync_auto_stop_widgets()
        if self._ui_is_manual():
            self.mode_label.setText(self._tr("mode_manual"))
        else:
            self._refresh_fixture_mode_label()
        if not self.running and not self.completed:
            self._refresh_lifecycle_presentation()

    def _refresh_fixture_mode_label(self, _text: str = ""):
        if self._ui_is_manual():
            return
        raw = self.hz_combo.currentText()
        try:
            hz_text = f"{parse_reference_rate_hz(raw):g}"
        except ValueError:
            hz_text = (raw or "").strip() or "—"
        self.mode_label.setText(self._tr("mode_fixture", hz=hz_text))

    def _sync_auto_stop_widgets(self):
        fixture = not self._ui_is_manual()
        on = self.auto_stop_on.isChecked()
        self.auto_stop_label.setVisible(fixture)
        self.auto_stop_off.setVisible(fixture)
        self.auto_stop_on.setVisible(fixture)
        self.auto_stop_sec_label.setVisible(fixture and on)
        self.auto_stop_sec_combo.setVisible(fixture and on)
        self.auto_stop_off.setObjectName("Primary" if not on else "Secondary")
        self.auto_stop_on.setObjectName("Primary" if on else "Secondary")
        for btn in (self.auto_stop_off, self.auto_stop_on):
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

    def _auto_stop_seconds(self) -> float | None:
        enabled = (not self._ui_is_manual()) and self.auto_stop_on.isChecked()
        return parse_auto_stop_seconds(enabled, self.auto_stop_sec_combo.currentText())

    def _validated_profile_settings_from_ui(self) -> dict[str, Any]:
        """Parse current Setup widgets into an immutable-ready settings dict.

        Raises ProfileValidationError with an i18n key on invalid input.
        """
        try:
            self._auto_stop_seconds()
        except ValueError as exc:
            raise ProfileValidationError("auto_stop_invalid") from exc
        if not self._ui_is_manual():
            try:
                parse_reference_rate_hz(self.hz_combo.currentText())
            except ValueError as exc:
                raise ProfileValidationError("reference_rate_invalid") from exc
            try:
                parse_fixture_timing_tolerance_ms(self.timing_tol_edit.text())
            except ValueError as exc:
                raise ProfileValidationError("fixture_timing_tolerance_invalid") from exc
        try:
            parse_qt_custom_limits(self._custom_limit_raw_values())
        except QtCustomLimitsError as exc:
            key = "custom_limits_order_invalid" if exc.code == "order" else "custom_limits_invalid"
            raise ProfileValidationError(key) from exc
        return copy.deepcopy(self.settings())

    def _lifecycle_state(self) -> str:
        """Authoritative UI/lifecycle label. Not stored separately from flags/snapshots."""
        if self.running:
            return "running"
        if self.completed:
            return "completed"
        if self.profile_locked_settings is None:
            return "draft"
        if self.capture_armed:
            return "armed"
        return "ready"

    def _refresh_lifecycle_presentation(self):
        state = self._lifecycle_state()
        if state == "draft":
            self.val_phase.setText(self._tr("phase_draft"))
            self.status_label.setText(self._tr("status_draft"))
            error_key = self._profile_validation_error_key
            self.lbl_profile_status.setText(self._tr(error_key) if error_key else self._tr("profile_status_draft"))
            self.hint.setText(self._tr("test_area_hint_draft"))
        elif state == "ready":
            self.val_phase.setText(self._tr("phase_ready"))
            self.status_label.setText(self._tr("status_ready"))
            self.lbl_profile_status.setText(self._tr("profile_status_locked"))
            self.hint.setText(self._tr("test_area_hint_ready"))
        elif state == "armed":
            self.val_phase.setText(self._tr("phase_armed"))
            self.status_label.setText(self._tr("status_armed"))
            self.lbl_profile_status.setText(self._tr("profile_status_locked"))
            self.hint.setText(self._tr("test_area_hint_armed"))
        elif state == "running":
            self.val_phase.setText(self._tr("phase_running"))
            self.lbl_profile_status.setText(self._tr("profile_status_locked"))
        elif state == "completed":
            self.val_phase.setText(self._tr("phase_review"))
            self.lbl_profile_status.setText(self._tr("profile_status_locked"))
        if self._ui_is_manual():
            self.mode_label.setText(self._tr("mode_manual"))
        else:
            self._refresh_fixture_mode_label()

    def lock_profile(self) -> bool:
        if self.running or self.completed:
            return False
        try:
            settings = self._validated_profile_settings_from_ui()
        except ProfileValidationError as exc:
            self.alert_label.setText(self._tr(exc.key))
            self._profile_validation_error_key = exc.key
            self._refresh_lifecycle_presentation()
            return False
        self._profile_validation_error_key = None
        device = self.device_edit.text().strip()
        if device:
            self.target = device
        self.profile_locked_settings = settings
        self.profile_locked_target = self.target
        self.capture_armed = False
        self.device_press_queues.clear()
        self._arming_scheduled = False
        self._locked_button = str(settings.get("focus_button") or "Left")
        self.alert_label.setText("")
        self._show_workflow_page("capture")
        self.enter_listen()
        return True

    def _on_arm_clicked(self):
        if self._lifecycle_state() == "armed":
            self.disarm_capture()
        else:
            self.arm_capture()

    def arm_capture(self) -> bool:
        if self.profile_locked_settings is None or self.running or self.completed:
            return False
        self.device_press_queues.clear()
        self._arming_scheduled = False
        self._arm_boundary_perf = time.perf_counter()
        self.capture_armed = True
        self._update_controls()
        return True

    def disarm_capture(self) -> bool:
        if not self.capture_armed or self.running or self.completed:
            return False
        self.capture_armed = False
        self._arm_boundary_perf = None
        self.device_press_queues.clear()
        self._arming_scheduled = False
        self._update_controls()
        return True

    def edit_profile(self) -> bool:
        if self.running or self.completed:
            return False
        self.capture_armed = False
        self._arm_boundary_perf = None
        self.profile_locked_settings = None
        self.profile_locked_target = ""
        self._profile_validation_error_key = None
        self.device_press_queues.clear()
        self._arming_scheduled = False
        self.alert_label.setText("")
        self._show_workflow_page("setup")
        self._update_controls()
        return True

    def settings(self) -> dict[str, Any]:
        manual = self._ui_is_manual()
        device = self.device_edit.text().strip()
        if self.profile_locked_settings is None and self.locked is None and device:
            self.target = device
        if manual:
            hz = 0.0
        else:
            hz = parse_reference_rate_hz(self.hz_combo.currentText())
        limits = parse_qt_custom_limits(self._custom_limit_raw_values())
        base = {
            "manual_mode": manual,
            "profile_name": "Manual_Left_Stable" if manual else "Fixture_Custom",
            "focus_button": self.button_combo.currentText(),
            "button": self.button_combo.currentText(),
            "fixture_hz": hz,
            "fixture_reference_hz": hz,
            "capture_mode": "Windows Raw Input / 裝置RawInput",
            "language": self._report_lang(),
            "judgement_mode": "Custom",
            **limits,
        }
        try:
            auto_sec = self._auto_stop_seconds()
        except ValueError:
            auto_sec = None
        if auto_sec is not None:
            # Legacy reports still read duration_sec; do not derive expected_clicks here.
            base["duration_sec"] = auto_sec
        if not manual:
            base["test_profile"] = "Fixture Custom"
        normalized = normalize_auto_settings({"settings": base})
        contained = contain_qt_runtime_click_expectation(normalized, auto_sec)
        stamped = stamp_qt_reference_rate(contained, manual=manual, reference_rate_hz=hz)
        stamped = stamp_qt_custom_limit_metadata(stamped, manual=manual)
        stamped = stamp_qt_explicit_limits(stamped, limits)
        tolerance_ms: float | None = None
        if not manual:
            try:
                tolerance_ms = parse_fixture_timing_tolerance_ms(self.timing_tol_edit.text())
            except ValueError:
                tolerance_ms = None
        return stamp_qt_fixture_timing_tolerance(stamped, manual=manual, tolerance_ms=tolerance_ms)

    # ── Overlay ─────────────────────────────────────────────────────
    def _run_result_and_clicks(
        self,
        payload: dict[str, Any],
        *,
        settings: dict[str, Any] | None = None,
        events: list[dict[str, Any]] | None = None,
    ) -> tuple[str, str]:
        result = str(payload.get("result") or "").strip()
        metrics = dict(payload.get("metrics") or {})
        ev = events or payload.get("events") or payload.get("all_click_events") or []
        s = settings or payload.get("settings") or {}
        if ev and (not result or result == "?"):
            annotated = annotate_events(list(ev), s)
            if not metrics.get("click_count"):
                metrics = (build_payload(
                    str(payload.get("target") or self.target),
                    str(payload.get("operator") or self.operator),
                    s,
                    annotated,
                    run_id=str(payload.get("run_id") or ""),
                ).get("metrics") or {})
            tags = _metrics_issue_tags(metrics, s, annotated)
            result = _result_from_tags(tags, metrics, s) if int(metrics.get("click_count") or 0) > 0 else "IDLE"
        clicks = str(metrics.get("click_count") if metrics.get("click_count") is not None else len(ev) or "?")
        return result or "?", clicks

    def _overlay_list_label(self, run_id: str, result: str, clicks: str, target: str = "") -> str:
        label = f"{run_id} · {target}" if target else run_id
        return self._tr("overlay_list_line", label=label, result=result, n=clicks)

    def _load_run_meta_from_disk(self, detail_path: Path) -> dict[str, Any] | None:
        rid = detail_path.name.replace("mcsa_", "").replace("_detail.json", "")
        summary_path = self.report_root / f"mcsa_{rid}_summary.json"
        payload: dict[str, Any] = {}
        try:
            if summary_path.exists():
                payload = json.loads(summary_path.read_text(encoding="utf-8"))
            elif detail_path.exists():
                payload = json.loads(detail_path.read_text(encoding="utf-8"))
            else:
                return None
        except Exception:
            return None
        result, clicks = self._run_result_and_clicks(payload)
        target = str(payload.get("target_product") or payload.get("target") or "").strip()
        return {
            "run_id": rid,
            "label": self._overlay_list_label(rid, result, clicks, target),
            "detail_path": str(detail_path),
            "summary_path": str(summary_path) if summary_path.exists() else "",
            "mtime": detail_path.stat().st_mtime,
        }

    def _session_run_meta(self, run: dict[str, Any]) -> dict[str, Any]:
        rid = str(run.get("run_id") or "")
        events = list(run.get("events") or [])
        settings = run.get("settings") or self.settings()
        payload = {
            "run_id": rid,
            "target": self.target,
            "settings": settings,
            "events": events,
            "metrics": run.get("metrics") or {},
        }
        result, clicks = self._run_result_and_clicks(payload, settings=settings, events=events)
        target = str(self.target or "").strip()
        return {
            "run_id": rid,
            "label": self._overlay_list_label(rid, result, clicks, target),
            "events": events,
            "metrics": run.get("metrics") or {},
            "mtime": time.time(),
        }

    def _list_overlay_candidates(self) -> list[dict[str, Any]]:
        by_id: dict[str, dict[str, Any]] = {}
        if self.report_root.exists():
            for detail in self.report_root.glob("mcsa_*_detail.json"):
                meta = self._load_run_meta_from_disk(detail)
                if meta:
                    by_id[meta["run_id"]] = meta
        for run in reversed(self.session_runs):
            rid = str(run.get("run_id") or "")
            if not rid:
                continue
            session_meta = self._session_run_meta(run)
            if rid in by_id:
                if run.get("events") and not by_id[rid].get("events"):
                    by_id[rid]["events"] = list(run["events"])
                    by_id[rid]["metrics"] = run.get("metrics") or {}
            else:
                by_id[rid] = session_meta
        items = sorted(by_id.values(), key=lambda x: float(x.get("mtime") or 0), reverse=True)
        return items[:25]

    def load_overlay_run(self):
        candidates = self._list_overlay_candidates()
        if not candidates:
            QMessageBox.information(self, self._tr("compare_overlay"), self._tr("no_runs"))
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(self._tr("compare_title"))
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(self._tr("compare_pick")))
        note = QLabel(self._tr("compare_note"))
        note.setObjectName("Muted")
        lay.addWidget(note)
        listbox = QListWidget()
        for item in candidates:
            listbox.addItem(item.get("label") or item.get("run_id"))
        listbox.setCurrentRow(0)
        lay.addWidget(listbox)

        def _apply_path(path: str):
            try:
                payload = load_overlay_payload(path)
            except OverlayLoadError as exc:
                QMessageBox.critical(self, self._tr("load_overlay_failed"), str(exc))
                return
            except Exception as exc:
                QMessageBox.critical(self, self._tr("load_overlay_failed"), str(exc))
                return
            events = extract_overlay_events(payload)
            metrics = payload.get("metrics") or {}
            self._set_overlay(events, metrics, path)
            dlg.accept()

        def _on_compare():
            row = listbox.currentRow()
            if row < 0:
                return
            item = candidates[row]
            if item.get("events"):
                self._set_overlay(list(item["events"]), item.get("metrics") or {}, f"session:{item.get('run_id')}")
                dlg.accept()
                return
            path = item.get("detail_path") or item.get("summary_path") or ""
            if not path:
                QMessageBox.critical(self, self._tr("load_overlay_failed"), self._tr("no_events"))
                return
            _apply_path(str(path))

        def _on_browse():
            path, _ = QFileDialog.getOpenFileName(
                dlg,
                self._tr("browse"),
                str(self.report_root),
                "MCSA detail JSON (*_detail.json);;JSON (*.json);;All (*.*)",
            )
            if path:
                _apply_path(path)

        buttons = QDialogButtonBox()
        btn_browse = buttons.addButton(self._tr("browse"), QDialogButtonBox.ButtonRole.ActionRole)
        btn_compare = buttons.addButton(self._tr("compare_btn"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(self._tr("cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        btn_browse.clicked.connect(_on_browse)
        btn_compare.clicked.connect(_on_compare)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        dlg.exec()

    def _set_overlay(self, events: list[dict[str, Any]], metrics: dict[str, Any], path: str):
        self.overlay_events = list(events)
        self.overlay_metrics = ranking_metrics(metrics, metrics)
        self.overlay_path = path
        name = Path(path).name if not path.startswith("session:") else path.replace("session:", "")
        self.overlay_delta_label.setText(self._tr("overlay_status", name=name))
        self._refresh_metrics(final=self.completed)

    def clear_overlay(self):
        self.overlay_events = []
        self.overlay_metrics = {}
        self.overlay_path = ""
        self.overlay_delta_label.setText("")
        self._refresh_metrics(final=self.completed)

    def _update_overlay_deltas(self, current_metrics: dict[str, Any]):
        if not self.overlay_metrics:
            self.overlay_delta_label.setText("")
            return
        current = ranking_metrics(current_metrics, current_metrics)
        a_extra = int(self.overlay_metrics.get("true_extra_click_count") or 0)
        b_extra = int(current.get("true_extra_click_count") or 0)
        a_delay = int(self.overlay_metrics.get("miss_or_slow_count") or 0)
        b_delay = int(current.get("miss_or_slow_count") or 0)
        line = self._tr("delta_line", a_extra=a_extra, a_delay=a_delay, b_extra=b_extra, b_delay=b_delay)
        cards = delta_cards(current, self.overlay_metrics)
        winners = [c for c in cards if c.get("winner") in ("A", "B")]
        if winners:
            bits = [f"{c.get('label')}: {'A' if c.get('winner') == 'A' else 'B'}" for c in winners[:3]]
            line += "  ·  " + " | ".join(bits)
        base = self._tr("overlay_status", name=Path(self.overlay_path).name) if self.overlay_path and not self.overlay_path.startswith("session:") else self.overlay_path
        if self.overlay_path.startswith("session:"):
            base = self._tr("overlay_status", name=self.overlay_path.replace("session:", ""))
        self.overlay_delta_label.setText(f"{base}\n{line}")

    def _chart_points(self, annotated: list[dict[str, Any]]) -> tuple[list, list]:
        pts: list[tuple[float, float, str]] = []
        series: list[tuple[float, float]] = []
        for e in annotated:
            if not e.get("accepted"):
                continue
            iv = e.get("press_interval_ms")
            hold = e.get("hold_ms")
            elapsed = e.get("press_elapsed_ms")
            if iv is not None and hold is not None:
                pts.append((float(iv), float(hold), str(e.get("click_class") or "ON_CADENCE")))
            if iv is not None and elapsed is not None:
                series.append((float(elapsed), float(iv)))
        return pts, series

    # ── Capture lifecycle ───────────────────────────────────────────
    def _reset_live_values_for_listen(self):
        """Clear stale previous-run metrics when entering fresh LISTEN."""
        self.val_time.setText("--")
        self.val_clicks.setText("0")
        self.val_interval.setText("--")
        self.val_hold.setText("--")
        self.val_verdict.setText("--")
        self.val_extra.setText("0")
        self.val_rebound.setText("0")
        self.val_delay.setText("0")
        self.val_dut.setText("--")
        self.val_setup.setText("--")
        self.review_text.clear()
        self._set_review_panel_visible(False)
        self.alert_label.setText("")

    def enter_listen(self):
        if getattr(self, "_listen_start_timer", None) is not None:
            self._listen_start_timer.stop()
        self.listening = True
        self.running = False
        self.completed = False
        self.report_written = False
        self._arming_scheduled = False
        self.capture_armed = False
        self._arm_boundary_perf = None
        self._reset_live_values_for_listen()
        self.hint.show()
        self.test_area.setProperty("active", False)
        self.test_area.style().unpolish(self.test_area)
        self.test_area.style().polish(self.test_area)
        self._apply_mode_fields()
        self._update_controls()
        if self.profile_locked_settings is not None:
            self._locked_button = str(self.profile_locked_settings.get("focus_button") or "Left")
        else:
            self._locked_button = self.button_combo.currentText()
        try:
            self.ensure_raw_input()
        except Exception as exc:
            self.alert_label.setText(f"Raw Input failed: {exc}")

    def ensure_raw_input(self):
        if self.raw_input is None:
            self.raw_input = WindowsRawInputSubprocess(lambda e: self.bridge.event_received.emit(e))
        self.raw_input.start()

    def stop_adapters(self):
        if self.raw_input is not None:
            try:
                self.raw_input.stop()
            except Exception:
                pass
            self.raw_input = None

    def new_run(self):
        if self.running:
            return
        if self.events and self.completed:
            settings = self.locked or self.settings()
            annotated = annotate_events(list(self.events), settings)
            payload = build_payload(self.target, self.operator, settings, annotated, run_id=self.run_id)
            m = payload.get("metrics") or {}
            tags = _metrics_issue_tags(m, settings, annotated)
            result = _result_from_tags(tags, m, settings) if int(m.get("click_count") or 0) > 0 else "IDLE"
            self.session_runs.append({
                "run_id": self.run_id,
                "label": self._overlay_list_label(self.run_id, result, str(m.get("click_count") or 0), self.target),
                "events": list(self.events),
                "metrics": m,
                "settings": settings,
            })
        self.stop_adapters()
        self.events.clear()
        self.raw_events.clear()
        self.device_press_queues.clear()
        self.first_press_time = self.last_press_time = None
        self.first_release_time = self.last_release_time = None
        self.start_time = self.end_time = self.stop_time = None
        self.locked = None
        self.host_evidence_snapshot = None
        self.capture_armed = False
        self._arm_boundary_perf = None
        self.run_id = _now_run_id()
        self.alert_label.setText("")
        self.scatter.set_points([])
        self.interval_chart.set_series([])
        self.enter_listen()

    def stop_run(self):
        if not self.running:
            return
        now = time.perf_counter()
        self.stop_time = now
        if self.start_time is not None:
            self.val_time.setText(f"{max(0.0, now - float(self.start_time)):.1f}s")
        self.running = False
        self.listening = False
        self.completed = True
        self.stop_adapters()
        self._build_host_evidence_snapshot_for_completed_run()
        self.val_phase.setText(self._tr("phase_review"))
        self.hint.hide()
        self._set_review_panel_visible(True)
        self._refresh_metrics(final=True)
        if not self.status_label.text().startswith(("PASS", "WARN", "FAIL")):
            self.status_label.setText(self._tr("review_hint"))
        self._update_controls()

    def _build_host_evidence_snapshot_for_completed_run(self) -> None:
        """Build the neutral Host Evidence snapshot once, from run-locked settings.

        Data only: never feeds verdict, issue tags, or reports. The frozen
        snapshot may be consumed by REVIEW presentation. Requires a
        configured duration (Auto Stop ON); Auto Stop OFF and Manual stay None.
        All accepted Presses are passed, including post-deadline ones;
        ``host_evidence`` separates in-window from outside observations.
        """
        self.host_evidence_snapshot = None
        locked = self.locked
        if locked is None or bool(locked.get("manual_mode")):
            return
        duration_s = locked.get("duration_sec")
        tolerance_ms = locked.get(FIXTURE_TIMING_TOLERANCE_KEY)
        if not isinstance(duration_s, (int, float)) or isinstance(duration_s, bool) or duration_s <= 0:
            return
        if tolerance_ms is None or not self.events:
            return
        observed: list[Any] = []
        for event in self.events:
            value = event.get("press_elapsed_ms")
            if value is None:
                _log.warning("Host evidence snapshot not built: accepted event without press_elapsed_ms")
                return
            observed.append(value)
        try:
            self.host_evidence_snapshot = build_fixture_host_evidence(
                duration_s,
                locked.get("fixture_reference_hz"),
                tolerance_ms,
                observed,
            )
        except (HostEvidenceError, ValueError) as exc:
            _log.warning("Host evidence snapshot not built: %s", exc)
            self.host_evidence_snapshot = None

    def finish_report(self):
        if self.running:
            self.stop_run()
        if not self.events:
            QMessageBox.information(self, self._tr("report"), self._tr("no_run"))
            return
        self.completed = True
        settings = self.locked or self.settings()
        try:
            self.report_paths = write_reports(
                self.report_root, self.target, self.operator, settings, self.events, self.run_id, raw_events=list(self.raw_events)
            )
            verification = _verify_artifacts(self.report_paths)
            if not verification.get("ok"):
                raise RuntimeError("Missing: " + ", ".join(verification.get("missing") or []))
            self.report_written = True
            annotated = annotate_events(list(self.events), settings)
            payload = build_payload(self.target, self.operator, settings, annotated, run_id=self.run_id)
            m = payload.get("metrics") or {}
            tags = _metrics_issue_tags(m, settings, annotated)
            result = _result_from_tags(tags, m, settings) if int(m.get("click_count") or 0) > 0 else "IDLE"
            self.session_runs.append({
                "run_id": self.run_id,
                "label": self._overlay_list_label(self.run_id, result, str(m.get("click_count") or 0), self.target),
                "events": list(self.events),
                "metrics": m,
                "settings": settings,
            })
            self.status_label.setText(self._tr("report_ready"))
            self._update_controls()
            QMessageBox.information(self, self._tr("report"), self._tr("saved_to", path=self.report_root))
        except Exception as exc:
            QMessageBox.critical(self, self._tr("report_failed"), str(exc))

    def save_report_as(self):
        if not self.report_written:
            self.finish_report()
            if not self.report_written:
                return
        dest = QFileDialog.getExistingDirectory(self, self._tr("save_report_as"))
        if not dest:
            return
        import shutil
        out = Path(dest) / f"mcsa_{self.run_id}"
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        for path in (self.report_paths or {}).values():
            if path and Path(path).exists():
                shutil.copy2(path, out / Path(path).name)
                n += 1
        self.status_label.setText(self._tr("saved_files", n=n, path=out))

    def show_guide(self):
        self._ignore_arm_until = time.perf_counter() + 1.5
        QMessageBox.information(self, self._tr("guide_title"), self._tr("guide_body"))
        self._ignore_arm_until = time.perf_counter() + 0.8

    def _update_controls(self):
        state = self._lifecycle_state()
        self.btn_stop.setEnabled(self.running)
        self.btn_new.setEnabled(not self.running)
        self.btn_finish.setEnabled(self.completed and not self.running)
        self.btn_save.setEnabled(self.report_written)
        self.btn_lock_profile.setEnabled(state == "draft")
        self.btn_arm.setEnabled(state in ("ready", "armed"))
        self.btn_arm.setText(self._tr("disarm_capture") if state == "armed" else self._tr("arm_capture"))
        self.btn_edit_profile.setEnabled(state in ("ready", "armed"))
        editable = setup_controls_editable(
            running=self.running,
            completed=self.completed,
            profile_locked=self.profile_locked_settings is not None,
        )
        for w in (
            self.radio_manual, self.radio_fixture, self.button_combo, self.hz_combo,
            self.timing_tol_edit, self.auto_stop_off, self.auto_stop_on, self.auto_stop_sec_combo,
            self.device_edit, *self._limit_edits.values(),
        ):
            w.setEnabled(editable)
        self._refresh_lifecycle_presentation()

    def _cursor_global_pos(self):
        return self.cursor().pos()

    def _test_area_is_active(self) -> bool:
        # Hidden stacked pages keep their last geometry, so a stale Test Area rect must not hit-test.
        return (
            self.page_stack.currentWidget() is self.page_capture
            and self.test_area.isVisibleTo(self)
        )

    def _cursor_in_test_area(self) -> bool:
        if not self._test_area_is_active():
            return False
        try:
            gp = self.test_area.mapFromGlobal(self._cursor_global_pos())
            return self.test_area.rect().contains(gp)
        except Exception as exc:
            _log.warning("Test Area hit-test failed; treating cursor as outside: %s", exc)
            return False

    # ── Raw input ───────────────────────────────────────────────────
    def _on_raw_event_ui(self, event: dict[str, Any]):
        if self.running:
            pass
        elif self.capture_armed and self.profile_locked_settings is not None and not self.completed:
            pass
        else:
            return
        if event.get("capture_source") != "windows_raw_input":
            return
        button = event.get("button")
        event_type = event.get("event_type")
        device_source = event.get("device_source") or "unknown_device"
        if self.running:
            t_perf = float(event.get("time_perf") or time.perf_counter())
        else:
            # Armed first-event qualification never substitutes parent delivery time.
            t_perf = _finite_raw_time_perf(event)
        target = self._locked_button
        if self.running:
            self.raw_events.append({
                "timestamp": now_iso(), "button": button, "event_type": event_type,
                "accepted": False, "time_perf": t_perf, "device_source": device_source,
            })
        if button != target:
            if self.running and event_type == "up":
                self.alert_label.setText(f"Wrong button: {button}")
            return
        key = (device_source, str(button))
        if not self.running and (t_perf is None or not self._is_timestamp_after_arm_boundary(t_perf)):
            # An unqualifiable target event must not leave a half pair a later event could complete.
            self.device_press_queues.pop(key, None)
            return
        if event_type == "down":
            self.device_press_queues[key].append(t_perf)
        elif event_type == "up":
            q = self.device_press_queues[key]
            if not q:
                return
            press = q.popleft()
            if self.running:
                if self._is_manual() and not self._cursor_in_test_area():
                    return
                if (
                    (not self._is_manual())
                    and self._cursor_in_test_area() is False
                    and self._cursor_over_capture_exclusion_ui()
                ):
                    return
                self.record_click(button, press, t_perf, event)
            elif self.capture_armed and not self._arming_scheduled:
                if (
                    not self._is_timestamp_after_arm_boundary(press)
                    or not self._is_timestamp_after_arm_boundary(t_perf)
                ):
                    return
                self._arming_scheduled = True
                self._begin_session_from_first_click(button, press, t_perf, event)

    def _is_timestamp_after_arm_boundary(self, t_perf: float) -> bool:
        """True only for Raw Input stamps strictly after Arm. At/before cannot become t0."""
        boundary = self._arm_boundary_perf
        if boundary is None:
            return False
        try:
            stamp = float(t_perf)
            limit = float(boundary)
        except (TypeError, ValueError):
            return False
        if not (math.isfinite(stamp) and math.isfinite(limit)):
            return False
        return stamp > limit

    def _capture_exclusion_widgets(self) -> list[QWidget]:
        # Interactive chrome only; page backgrounds stay location-independent for Fixture capture.
        return [
            self.nav_rail,
            self.capture_actions,
            self.theme_combo,
            self.lang_combo,
            self.radio_manual,
            self.radio_fixture,
            self.device_edit,
            self.button_combo,
            self.hz_combo,
            self.timing_tol_edit,
            self.auto_stop_off,
            self.auto_stop_on,
            self.auto_stop_sec_combo,
            self.btn_lock_profile,
            self.btn_arm,
            self.btn_edit_profile,
            *self._limit_edits.values(),
            self.setup_scroll.verticalScrollBar(),
        ]

    def _cursor_over_capture_exclusion_ui(self) -> bool:
        try:
            pos = self._cursor_global_pos()
            for widget in self._capture_exclusion_widgets():
                if not widget.isVisibleTo(self):
                    continue
                if widget.rect().contains(widget.mapFromGlobal(pos)):
                    return True
        except Exception as exc:
            _log.warning("Capture exclusion hit-test failed; treating cursor as over UI: %s", exc)
            return True
        return False

    def _begin_session_from_first_click(self, button, press, release, event):
        if self.running or self.completed:
            self._arming_scheduled = False
            return
        if self.profile_locked_settings is None or not self.capture_armed:
            self._arming_scheduled = False
            return
        if not (
            self._is_timestamp_after_arm_boundary(press)
            and self._is_timestamp_after_arm_boundary(release)
        ):
            self._arming_scheduled = False
            return
        if time.perf_counter() < self._ignore_arm_until:
            self._arming_scheduled = False
            return
        if self._is_manual():
            if not self._cursor_in_test_area():
                self._arming_scheduled = False
                return
        elif self._cursor_over_capture_exclusion_ui():
            self._arming_scheduled = False
            return
        s = copy.deepcopy(self.profile_locked_settings)
        duration_sec = s.get("duration_sec")
        auto_sec = None
        if isinstance(duration_sec, (int, float)) and not isinstance(duration_sec, bool) and duration_sec > 0:
            auto_sec = float(duration_sec)
        target = str(s.get("focus_button") or "Left")
        if button != target:
            self.alert_label.setText(f"Wrong button: got {button}, expected {target}")
            self._arming_scheduled = False
            return
        self.events.clear()
        self.raw_events.clear()
        self.device_press_queues.clear()
        self.first_press_time = self.last_press_time = None
        self.first_release_time = self.last_release_time = None
        self.locked = copy.deepcopy(s)
        self.target = self.profile_locked_target
        self.host_evidence_snapshot = None
        self._locked_button = target
        self.start_time = press
        self.stop_time = None
        self.end_time = None if auto_sec is None else press + float(auto_sec)
        self.running = True
        self.listening = False
        self.completed = False
        self.capture_armed = False
        self._arm_boundary_perf = None
        self.report_written = False
        self.val_phase.setText(self._tr("phase_running"))
        self.hint.hide()
        self.test_area.setProperty("active", True)
        self.test_area.style().unpolish(self.test_area)
        self.test_area.style().polish(self.test_area)
        if auto_sec is None:
            self.status_label.setText(self._tr("recording_manual") if self._is_manual() else self._tr("recording_fixture"))
        else:
            self.status_label.setText(self._tr("recording_fixture_autostop", sec=f"{auto_sec:g}"))
        self.alert_label.setText("")
        self._update_controls()
        self.record_click(button, press, release, event)

    def record_click(self, button, press_time, release_time, event):
        hold_ms = (release_time - press_time) * 1000.0
        if ARMING_SEC > 0 and self.start_time is not None and (press_time - float(self.start_time)) < ARMING_SEC:
            return
        if self.first_press_time is None:
            self.first_press_time = press_time
        if self.first_release_time is None:
            self.first_release_time = release_time
        press_elapsed = (press_time - self.first_press_time) * 1000.0
        release_elapsed = (release_time - self.first_release_time) * 1000.0
        press_interval = None if self.last_press_time is None else (press_time - self.last_press_time) * 1000.0
        self.last_press_time = press_time
        self.last_release_time = release_time
        self.events.append({
            "index": len(self.events) + 1,
            "timestamp": now_iso(),
            "button": button,
            "event_type": "click",
            "accepted": True,
            "press_elapsed_ms": round(press_elapsed, 4),
            "press_interval_ms": round(press_interval, 4) if press_interval is not None else None,
            "release_elapsed_ms": round(release_elapsed, 4),
            "elapsed_ms": round(release_elapsed, 4),
            "hold_ms": round(hold_ms, 4),
            "capture_source": event.get("capture_source", "windows_raw_input"),
            "device_source": event.get("device_source", "unknown_device"),
        })

    # ── Tick / metrics / charts ─────────────────────────────────────
    def _tick(self):
        if self.running:
            now = time.perf_counter()
            self.val_time.setText(f"{max(0.0, now - float(self.start_time or now)):.1f}s")
            if self.end_time is not None and now >= float(self.end_time):
                self.stop_run()
                return
            if now - self._last_metric_ts >= 0.45:
                self._last_metric_ts = now
                self._refresh_metrics(final=False)

    def _refresh_metrics(self, final: bool = False):
        settings = self.locked or self.settings()
        annotated = annotate_events(list(self.events), settings)
        payload = build_payload(self.target, self.operator, settings, annotated, run_id=self.run_id)
        m = payload.get("metrics") or {}
        tags = _metrics_issue_tags(m, settings, annotated) if (self.running or self.completed) else []
        verdict = qt_visible_verdict(tags, m, settings)
        accepted = [e for e in annotated if e.get("accepted")]
        self.val_clicks.setText(str(len(accepted)))
        if accepted:
            last = accepted[-1]
            if last.get("press_interval_ms") is not None:
                self.val_interval.setText(f"{last['press_interval_ms']:.2f} ms")
            if last.get("hold_ms") is not None:
                self.val_hold.setText(f"{last['hold_ms']:.2f} ms")
        extra = int(m.get("true_extra_click_count") or 0) + int(m.get("chatter_bounce_count") or 0)
        self.val_extra.setText(str(extra))
        self.val_rebound.setText(str(int(m.get("incomplete_rebound_count") or 0)))
        self.val_delay.setText(str(int(m.get("miss_or_slow_count") or 0)))
        if _is_manual_profile(settings):
            self.val_dut.setText(self._tr("na"))
            self.val_setup.setText(self._tr("na"))
        else:
            self.val_dut.setText(str(m.get("dut_score", "--")))
            self.val_setup.setText(str(m.get("setup_score", "--")))
        self.val_verdict.setText(str(verdict))
        if final or self.completed:
            if _is_manual_profile(settings) and verdict == "PASS":
                self.status_label.setText(self._tr("pass_manual"))
            elif verdict == "WARN":
                self.status_label.setText(self._tr("warn_manual") if _is_manual_profile(settings) else self._tr("warn_fixture"))
            elif verdict == "FAIL":
                self.status_label.setText(self._tr("fail_verdict"))
            alert = [tag for tag in _QT_ALERT_TAGS if tag in tags]
            self.alert_label.setText(" · ".join(alert))
            visible_tags = qt_present_issue_tags(tags)
            lines = [
                self._tr("review_mode", mode=self.mode_label.text(), button=settings.get("focus_button")),
                self._tr("review_clicks", clicks=m.get("click_count"), verdict=verdict),
                self._tr("review_interval", avg=m.get("interval_avg_ms"), cv=m.get("interval_cv_pct")),
                self._tr(
                    "review_tags",
                    tags=", ".join(visible_tags) if visible_tags else self._tr("review_tags_none"),
                ),
            ]
            evidence_lines = format_host_evidence_review_lines(self.host_evidence_snapshot, self._tr)
            if evidence_lines:
                lines += ["", *evidence_lines]
            self.review_text.setPlainText("\n".join(lines))

        self._update_overlay_deltas(m)

        pts, series = self._chart_points(accepted)
        beat = cadence_ms(settings)
        overlay_ann = annotate_events(list(self.overlay_events), settings) if self.overlay_events else []
        ov_pts, ov_series = self._chart_points(overlay_ann)

        if _is_manual_profile(settings):
            scatter_title = self._tr("chart_scatter_manual")
        else:
            scatter_title = self._tr("chart_scatter_fixture", beat=f"{beat:.1f}" if beat else "-")
        self.scatter.set_points(
            pts,
            title=scatter_title,
            overlay=ov_pts,
            target_beat_ms=beat if not _is_manual_profile(settings) else None,
        )
        self.interval_chart.set_series(
            series,
            title=self._tr("chart_interval"),
            overlay=ov_series,
            target_beat_ms=beat if not _is_manual_profile(settings) else None,
        )

    def closeEvent(self, event):
        if getattr(self, "_listen_start_timer", None) is not None:
            self._listen_start_timer.stop()
        if getattr(self, "ui_timer", None) is not None:
            self.ui_timer.stop()
        self.stop_adapters()
        super().closeEvent(event)


def run_qt_ui(
    *,
    report_root: str | Path | None = None,
    target: str = "",
    operator: str = "",
    run_id: str = "",
    lang: str = "en",
    theme: str = "light",
    **_kwargs,
) -> int:
    import sys
    root = Path(report_root) if report_root else Path(__file__).resolve().parents[3] / "reports"
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(get_style(theme))
    win = MainWindow(
        report_root=root,
        target=target,
        operator=operator,
        run_id=run_id or "",
        lang=lang,
        theme=theme,
    )
    win.showMaximized()
    return app.exec()
