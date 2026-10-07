"""PySide6 MainWindow — Apple-inspired shell over existing MCSA core."""
from __future__ import annotations

import copy
import json
import logging
import math
import shutil
import time
from collections import defaultdict, deque
from decimal import Decimal
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QEvent, QTimer, Signal, QObject, QPoint, QRect, QSettings, QSize
from PySide6.QtGui import QCursor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
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
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QButtonGroup,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QHeaderView,
    QAbstractItemView,
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
    _verify_artifacts,
)
from ..cadence import cadence_ms, fixture_hz as fixture_rate_hz, ranking_metrics
from ..completed_result import (
    RUN_STATUSES,
    accepted_host_press_count,
    build_completed_result_model,
    completed_run_status,
    run_status_for_count,
    paired_interval_histograms,
    qt_present_issue_tags,
    qt_visible_issue_tags,
    qt_visible_verdict,
)
from ..core import now_iso
from ..fixture_schedule import fixture_reference_interval_ms
from ..host_evidence import HostEvidenceError, build_fixture_host_evidence
from ..i18n import LANG_LABELS, STRINGS, SUPPORTED_LANGS, normalize_lang, t
from ..measurements import (
    actual_run_duration_s,
    reference_interval_ms,
    reference_interval_ms_or_none,
)
from ..overlay_io import OverlayLoadError, extract_overlay_events, load_overlay_payload
from ..schema import TOOL_NAME
from .charts import HistogramChart, IntervalChart, OccupancyBar, ScatterChart
from .presentation import (
    SCREENING_PRESENTATION_KEYS,
    measurement_only_timing_observation_label,
    screening_presentation_label,
    screening_presentation_labels,
)
from .click_table_sort import (
    CLICK_TABLE_COLUMN_IDS,
    CLICK_TABLE_ID_TO_INDEX,
    CLICK_TABLE_INDEX_TO_ID,
    CLICK_TABLE_LABEL_KEYS,
    CLICK_TABLE_MEASUREMENT_VISIBLE_IDS,
    CLICK_TABLE_NUMERIC_COLUMNS,
    sort_permutation,
)
from .styles import density_for_size, get_palette, get_style, layout_metric

_log = logging.getLogger(__name__)

# Quiet-period floor after a completed run. Fixture runs use
# max(floor, POST_RUN_QUIET_INTERVALS * reference_interval_ms) with no upper cap.
POST_RUN_INPUT_QUIET_MS = 900
POST_RUN_QUIET_INTERVALS = 2.0
POST_RUN_HUMAN_INTENT_MOVE_PX = 28
_POST_RUN_BUTTON_EVENTS = frozenset({
    QEvent.Type.MouseButtonPress,
    QEvent.Type.MouseButtonRelease,
})


def post_run_quiet_ms(settings: dict[str, Any] | None) -> int:
    """Cadence-aware post-run quiet period in milliseconds.

    Manual (and missing/invalid Fixture rate) uses ``POST_RUN_INPUT_QUIET_MS``.
    Fixture uses ``max(floor, POST_RUN_QUIET_INTERVALS * (1000 / Hz))``.
    Does not invent a Fixture reference rate for Manual.
    """
    floor = max(0, int(POST_RUN_INPUT_QUIET_MS))
    if not settings or _is_manual_profile(settings):
        return floor
    hz = settings.get("fixture_reference_hz")
    if hz is None:
        hz = settings.get("fixture_hz")
    if hz is None or isinstance(hz, bool):
        return floor
    try:
        hz_f = float(hz)
    except (TypeError, ValueError):
        return floor
    if not math.isfinite(hz_f) or hz_f <= 0.0:
        return floor
    interval_ms = reference_interval_ms(hz_f)
    scaled = float(POST_RUN_QUIET_INTERVALS) * interval_ms
    return max(floor, int(round(scaled)))


def _mouse_event_global_pos(event) -> QPoint | None:
    if event is None:
        return None
    getter = getattr(event, "globalPosition", None)
    if callable(getter):
        try:
            return getter().toPoint()
        except Exception:
            pass
    getter = getattr(event, "globalPos", None)
    if callable(getter):
        try:
            pos = getter()
            return QPoint(int(pos.x()), int(pos.y()))
        except Exception:
            pass
    return None


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


def format_reference_interval_ms(interval_ms: Any) -> str:
    """Two-decimal display of a reference interval; stored values keep full precision."""
    if interval_ms is None or isinstance(interval_ms, bool):
        return "—"
    try:
        value = float(interval_ms)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(value):
        return "—"
    return f"{value:.2f}"


def format_reference_rate_hz(rate_hz: Any) -> str:
    if rate_hz is None or isinstance(rate_hz, bool):
        return "—"
    try:
        value = float(rate_hz)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(value) or value <= 0.0:
        return "—"
    return f"{value:g}"


def setup_reference_interval_ms(raw_rate: Any) -> float | None:
    """Derived Setup interval for the typed Reference Rate, or None if the rate is invalid."""
    try:
        return reference_interval_ms_or_none(parse_reference_rate_hz(raw_rate))
    except ValueError:
        return None


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
    """Escape '&' so Qt buttons/actions show a literal ampersand.

    Source copy keeps a single '&'. This is presentation-only; do not store '&&'
    in i18n or future string resources.
    """
    return str(text).replace("&", "&&")


FOCUS_BUTTON_TOKENS: tuple[str, ...] = ("Left", "Right", "Middle", "X1", "X2")
DEFAULT_FOCUS_BUTTON = "Left"


def populate_focus_button_combo(combo: QComboBox) -> None:
    """Fill the Setup button selector: visible text is independent of itemData."""
    combo.clear()
    for token in FOCUS_BUTTON_TOKENS:
        combo.addItem(token, token)


def focus_button_token(combo: QComboBox) -> str:
    """Canonical focus_button token from combo itemData, never from display text."""
    data = combo.currentData()
    token = str(data if data is not None else "")
    return token if token in FOCUS_BUTTON_TOKENS else DEFAULT_FOCUS_BUTTON


def select_focus_button(combo: QComboBox, token: str) -> None:
    """Restore the selector from a canonical machine value."""
    idx = combo.findData(str(token))
    if idx >= 0:
        combo.setCurrentIndex(idx)


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

# i18n keys for the retired Setup editors. Kept so serialized/legacy tables
# remain discoverable; normal Setup no longer renders these as product limits.
_QT_CUSTOM_LIMIT_LABEL_KEYS: dict[str, str] = {
    "chatter_threshold_ms": "limit_chatter_ms",
    "duplicate_click_threshold_ms": "limit_double_click_ms",
    "fixture_actuation_too_short_ms": "limit_actuation_short_ms",
    "low_hold_warning_ms": "limit_low_hold_ms",
    "interval_cv_limit_pct": "limit_interval_cv_pct",
}

_CAPTURE_ISSUE_INTERNAL: dict[str, str] = {
    "extra": "TRUE_EXTRA_CLICK",
    "rebound": "INCOMPLETE_REBOUND",
    "delay": "MISS_OR_SLOW",
}


class QtCustomLimitsError(ValueError):
    """Invalid Custom Limits input. code is 'numeric' or 'order'."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def qt_custom_limit_defaults() -> dict[str, float]:
    """Legacy classifier compatibility defaults. Not tester-configured product limits.

    Copied from RULE_PRESETS['Strict'] so informational tags keep a stable
    heuristic. Setup no longer exposes these values for editing.
    """
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
    """Parse the tester-configured Schedule Association Window half-width (± ms).

    Persisted as ``fixture_timing_tolerance_ms``. Accepts 0 and any finite
    positive number. No default, clamp, rounding, maximum, or frequency-derived
    value. Distinct from legacy ``fixture_match_tolerance_ms``.
    """
    message = "Schedule Association Window must be a finite number >= 0"
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


def schedule_association_context(raw_rate: Any, raw_window: Any) -> dict[str, Any]:
    """Derived, informational Setup context for the Schedule Association Window.

    ``percent_of_interval`` = W / T × 100. ``windows_overlap`` uses the
    matcher's own inclusive condition 2W >= T with the same reference-interval
    and Decimal path. Neither value is editable or an acceptance threshold.
    Invalid or incomplete input yields None for every derived value it needs.
    """
    try:
        interval: float | None = fixture_reference_interval_ms(parse_reference_rate_hz(raw_rate))
    except ValueError:
        interval = None
    try:
        window: float | None = parse_fixture_timing_tolerance_ms(raw_window)
    except ValueError:
        window = None
    percent: float | None = None
    overlap: bool | None = None
    if interval is not None and window is not None and math.isfinite(interval) and interval > 0.0:
        percent = window / interval * 100.0
        overlap = (Decimal(2) * Decimal(str(window))) >= Decimal(str(interval))
    return {
        "reference_interval_ms": interval,
        "window_ms": window,
        "percent_of_interval": percent,
        "windows_overlap": overlap,
    }


def format_association_window_ms(window_ms: Any) -> str:
    if window_ms is None or isinstance(window_ms, bool):
        return "—"
    try:
        value = float(window_ms)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(value):
        return "—"
    return f"±{value:.2f} ms"


def format_percent_of_interval(percent: Any) -> str:
    if percent is None or isinstance(percent, bool):
        return "—"
    try:
        value = float(percent)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(value):
        return "—"
    return f"{value:.1f} %"


def stamp_qt_fixture_timing_tolerance(
    settings: dict[str, Any],
    *,
    manual: bool,
    tolerance_ms: float | None,
) -> dict[str, Any]:
    """Stamp the Schedule Association Window (``fixture_timing_tolerance_ms``) after legacy normalize.

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
            "he_matched_used",
            matched=int(matching["matched_host_observation_count"] or 0),
            total=int(counts["in_window_host_press_count"] or 0),
        ),
    ]
    matched_n = int(matching["matched_host_observation_count"] or 0)
    if matched_n == 0:
        lines.append(tr("he_timing_empty"))
    else:
        lines.append(
            tr(
                "he_timing",
                avg=_fmt_signed_ms(delta["average"]),
                min=_fmt_signed_ms(delta["minimum"]),
                max=_fmt_signed_ms(delta["maximum"]),
                sd=_fmt_unsigned_ms(delta["stdev"]),
                abs_avg=_fmt_unsigned_ms(abs_delta["average"]),
            )
        )
    if config.get("matching_windows_can_overlap"):
        lines.append(tr("he_overlap"))
    return lines


_QT_ALERT_TAGS = (
    "FIXTURE_HZ_MISMATCH",
    "HIGH_PROBABILITY_DOUBLE_CLICK",
    "CHATTER_HARD",
)


class CaptureBridge(QObject):
    """Marshals Raw Input callbacks onto the Qt UI thread."""

    event_received = Signal(dict)


def locked_profile_preview_rows(
    settings: dict[str, Any] | None,
    target: str,
    tr,
) -> list[tuple[str, str]]:
    """Read-only (label, value) rows derived only from a frozen profile snapshot."""
    if settings is None:
        return []
    manual = bool(settings.get("manual_mode"))
    rows = [
        (tr("device"), (target or "").strip() or "—"),
        (tr("button"), str(settings.get("focus_button") or "Left")),
        (tr("preview_mode"), tr("manual") if manual else tr("fixture")),
    ]
    if manual:
        return rows
    hz = settings.get("fixture_reference_hz")
    tol = settings.get(FIXTURE_TIMING_TOLERANCE_KEY)
    duration = settings.get("duration_sec")
    rows.append((tr("preview_reference_rate"), f"{float(hz):g} Hz" if isinstance(hz, (int, float)) else "—"))
    rows.append((
        tr("preview_timing_tolerance"),
        format_association_window_ms(tol) if isinstance(tol, (int, float)) else "—",
    ))
    if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration > 0:
        rows.append((tr("auto_stop"), f"{float(duration):g} s"))
    else:
        rows.append((tr("auto_stop"), tr("preview_auto_stop_off")))
    return rows


class ResponsiveCardGrid(QWidget):
    """Reflows Setup cards into 3 / 2 / 1 columns by width, preferring scroll over squeeze."""

    THREE_COLUMN_MIN_WIDTH = 1080
    TWO_COLUMN_MIN_WIDTH = 700
    # Keep below the thresholds above so the grid can always shrink and reflow.
    CARD_MIN_WIDTH = 300

    def __init__(self, cards: list[QWidget], parent: QWidget | None = None):
        super().__init__(parent)
        self._cards = list(cards)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(16)
        for card in self._cards:
            card.setMinimumWidth(self.CARD_MIN_WIDTH)
        self._columns = 0
        self._apply_columns(3)

    @classmethod
    def columns_for_width(cls, width: int) -> int:
        if width >= cls.THREE_COLUMN_MIN_WIDTH:
            return 3
        if width >= cls.TWO_COLUMN_MIN_WIDTH:
            return 2
        return 1

    def columns(self) -> int:
        return self._columns

    def _apply_columns(self, columns: int) -> None:
        if columns == self._columns:
            return
        for card in self._cards:
            self._grid.removeWidget(card)
        for col in range(3):
            self._grid.setColumnStretch(col, 0)
        if columns >= 3:
            positions = [(0, 0, 1, 1), (0, 1, 1, 1), (0, 2, 1, 1)]
        elif columns == 2:
            positions = [(0, 0, 1, 1), (0, 1, 1, 1), (1, 0, 1, 2)]
        else:
            positions = [(0, 0, 1, 1), (1, 0, 1, 1), (2, 0, 1, 1)]
        for card, (row, col, row_span, col_span) in zip(self._cards, positions):
            self._grid.addWidget(card, row, col, row_span, col_span)
        for col in range(min(columns, 3)):
            self._grid.setColumnStretch(col, 1)
        self._columns = columns

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_columns(self.columns_for_width(event.size().width()))


class ResponsiveItemGrid(QWidget):
    """Reflow existing child widgets into N columns from actual available width."""

    def __init__(
        self,
        items: list[QWidget],
        *,
        wide_columns: int,
        medium_columns: int,
        compact_columns: int,
        wide_min_width: int,
        medium_min_width: int,
        h_spacing: int = 12,
        v_spacing: int = 8,
        column_stretches: tuple[int, ...] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._items = list(items)
        self._column_stretches = tuple(column_stretches or ())
        self._wide_columns = wide_columns
        self._medium_columns = medium_columns
        self._compact_columns = compact_columns
        self._wide_min_width = wide_min_width
        self._medium_min_width = medium_min_width
        self._max_columns = max(wide_columns, medium_columns, compact_columns)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(h_spacing)
        self._grid.setVerticalSpacing(v_spacing)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._columns = 0
        self._apply_columns(wide_columns)

    def columns(self) -> int:
        return self._columns

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(self._compact_columns * 108, hint.height())

    def columns_for_width(self, width: int) -> int:
        if width >= self._wide_min_width:
            return self._wide_columns
        if width >= self._medium_min_width:
            return self._medium_columns
        return self._compact_columns

    def _apply_columns(self, columns: int) -> None:
        if columns == self._columns:
            return
        for item in self._items:
            self._grid.removeWidget(item)
        for col in range(self._max_columns):
            self._grid.setColumnStretch(col, 0)
        for index, item in enumerate(self._items):
            self._grid.addWidget(item, index // columns, index % columns)
        stretches = self._column_stretches if len(self._column_stretches) == columns else (1,) * columns
        for col, stretch in enumerate(stretches):
            self._grid.setColumnStretch(col, stretch)
        self._columns = columns

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_columns(self.columns_for_width(event.size().width()))


class WrappingButtonBar(QWidget):
    """Wrap action buttons onto extra rows when the Capture viewport is too narrow."""

    def __init__(self, buttons: list[QWidget], parent: QWidget | None = None):
        super().__init__(parent)
        self._buttons = list(buttons)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(8)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._signature: tuple[int, ...] | None = None
        for btn in self._buttons:
            btn.setMinimumHeight(38)
            btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._relayout(self.width() or 800)

    def row_count(self) -> int:
        if not self._signature:
            return 1
        return 1 + max(self._signature[0::2])

    def _relayout(self, width: int) -> None:
        available = max(int(width), 1)
        positions: list[tuple[int, int]] = []
        row = col = used = 0
        for btn in self._buttons:
            need = max(btn.sizeHint().width(), 88) + 8
            if col and used + need > available:
                row += 1
                col = 0
                used = 0
            positions.append((row, col))
            used += need
            col += 1
        signature = tuple(v for pos in positions for v in pos)
        if signature == self._signature:
            return
        for btn in self._buttons:
            self._grid.removeWidget(btn)
        for col_i in range(len(self._buttons)):
            self._grid.setColumnStretch(col_i, 0)
        for btn, (r, c) in zip(self._buttons, positions):
            self._grid.addWidget(btn, r, c)
        self._signature = signature

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout(event.size().width())


class ShrinkableButtonBar(WrappingButtonBar):
    """Results bar whose minimum is its widest button, so a narrow page wraps it instead of clipping."""

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        widest = max((max(btn.sizeHint().width(), 88) for btn in self._buttons), default=0)
        return QSize(widest, hint.height())


# Persisted IDs; "compact"/"standard"/"large" predate the size-named presets and must stay valid.
WINDOW_MODES: tuple[str, ...] = (
    "auto",
    "compact",
    "laptop",
    "standard",
    "large",
    "large_plus",
    "full_hd",
    "custom",
    "maximized",
)
WINDOW_PRESET_SIZES: dict[str, tuple[int, int]] = {
    "compact": (1280, 720),
    "laptop": (1366, 768),
    "standard": (1440, 810),
    "large": (1600, 900),
    "large_plus": (1728, 972),
    "full_hd": (1920, 1080),
}
CUSTOM_WINDOW_MAX_SIZE = (7680, 4320)
AUTO_WINDOW_FRACTION = 0.9
AUTO_WINDOW_MAX_SIZE = (1600, 900)
# Fraction of a remembered window that must lie on a current work area to be restored.
REMEMBERED_GEOMETRY_MIN_VISIBLE = 0.25


def _fit_window_size(width: int, height: int, available: QSize, minimum: QSize) -> QSize:
    """Honor the window minimum where possible, but never exceed the available work area."""
    width = min(max(width, minimum.width()), available.width())
    height = min(max(height, minimum.height()), available.height())
    return QSize(max(width, 1), max(height, 1))


def auto_window_size(available: QSize, minimum: QSize) -> QSize:
    """Comfortable logical window size for a work area, capped at AUTO_WINDOW_MAX_SIZE."""
    width = min(int(available.width() * AUTO_WINDOW_FRACTION), AUTO_WINDOW_MAX_SIZE[0])
    height = min(int(available.height() * AUTO_WINDOW_FRACTION), AUTO_WINDOW_MAX_SIZE[1])
    return _fit_window_size(width, height, available, minimum)


def fit_requested_window_size(width: int, height: int, available: QSize, minimum: QSize) -> QSize:
    """Exact size when it fits; otherwise scale down uniformly (keeping aspect), then clamp to the work area."""
    if width <= available.width() and height <= available.height():
        return _fit_window_size(width, height, available, minimum)
    scale = min(available.width() / max(width, 1), available.height() / max(height, 1))
    return _fit_window_size(int(width * scale), int(height * scale), available, minimum)


def window_size_for_mode(mode: str, available: QSize, minimum: QSize, custom: QSize | None = None) -> QSize:
    if mode in WINDOW_PRESET_SIZES:
        width, height = WINDOW_PRESET_SIZES[mode]
        return fit_requested_window_size(width, height, available, minimum)
    if mode == "custom" and custom is not None and custom.isValid():
        return fit_requested_window_size(custom.width(), custom.height(), available, minimum)
    return auto_window_size(available, minimum)


def centered_top_left(frame_size: QSize, available: QRect) -> QPoint:
    """Top-left that centers a frame inside a work area, keeping the title bar on-screen."""
    x = available.x() + max(0, (available.width() - frame_size.width()) // 2)
    y = available.y() + max(0, (available.height() - frame_size.height()) // 2)
    return QPoint(x, y)


def geometry_is_reachable(rect: QRect, work_areas: list[QRect]) -> bool:
    if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
        return False
    area = rect.width() * rect.height()
    title_point = QPoint(rect.center().x(), rect.top() + 8)
    for work in work_areas:
        visible = rect.intersected(work)
        if visible.isEmpty():
            continue
        if visible.width() * visible.height() >= area * REMEMBERED_GEOMETRY_MIN_VISIBLE and work.contains(title_point):
            return True
    return False


class MainWindow(QMainWindow):
    MAX_SETUP_CONTENT_WIDTH = 1360
    # Results/Preferences content widths at which side-by-side composition replaces one column.
    RESULTS_ANALYSIS_HORIZONTAL_MIN_WIDTH = 820
    RESULTS_TWO_COLUMN_MIN_WIDTH = 760
    RESULTS_EVIDENCE_THREE_COLUMN_MIN_WIDTH = 960
    RESULTS_EVIDENCE_TWO_COLUMN_MIN_WIDTH = 620
    RESULTS_ANALYSIS_CHART_FRACTION = 0.68
    PREFERENCES_TWO_COLUMN_MIN_WIDTH = 860

    def __init__(
        self,
        *,
        report_root: Path,
        target: str = "",
        operator: str = "",
        run_id: str = "",
        lang: str = "en",
        theme: str = "light",
        window_settings: QSettings | None = None,
    ):
        super().__init__()
        self.lang = normalize_lang(lang)
        self.theme = theme if theme in ("light", "dark") else "light"
        self.setWindowTitle(t(self.lang, "app_title"))
        self.setMinimumSize(1024, 640)
        self.resize(1280, 840)
        # Without a settings store, window preferences live for this session only.
        self._window_settings = window_settings
        self.custom_window_size = self._stored_custom_window_size()
        stored_mode = str(self._window_pref("window/startup_mode", "auto"))
        if stored_mode not in WINDOW_MODES or (stored_mode == "custom" and self.custom_window_size is None):
            stored_mode = "auto"
        self.window_mode = stored_mode
        self.remember_window_geometry = self._window_pref_bool("window/remember_geometry", False)
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
        self._editing_next_run = False
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
        self._post_run_input_guard_active = False
        self._post_run_human_intent = False
        self._post_run_quiet_ready = False
        self._post_run_guard_origin = QPoint(0, 0)
        self._post_run_quiet_timer = QTimer(self)
        self._post_run_quiet_timer.setSingleShot(True)
        self._post_run_quiet_timer.timeout.connect(self._on_post_run_quiet_timeout)

        self._density = density_for_size(self.width(), self.height())
        self._density_sync_active = False
        self._build_ui()
        self._apply_density_layout()
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
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _tr(self, key: str, **kwargs) -> str:
        return t(self.lang, key, **kwargs)

    def _screening_profile_active(self) -> bool:
        """True only when an approved Screening/Validation Profile is applied.

        Measurement-only is the current product mode. Classifier tags remain
        internal until a profile is actually selected.
        """
        return False

    def _measurement_only_presentation(self) -> bool:
        return not self._screening_profile_active()

    def _apply_measurement_only_chrome(self) -> None:
        measurement = self._measurement_only_presentation()
        if getattr(self, "issue_title", None) is not None:
            self.issue_title.setVisible(not measurement)
        if getattr(self, "capture_issues_grid", None) is not None:
            self.capture_issues_grid.setVisible(not measurement)
        if getattr(self, "scatter", None) is not None:
            self.scatter.set_measurement_only_presentation(measurement)
        if getattr(self, "interval_chart", None) is not None:
            self.interval_chart.set_measurement_only_presentation(measurement)
        self._apply_click_table_column_visibility()

    def _chart_labels(self) -> dict[str, str]:
        keys = (
            "waiting_data", "axis_interval_ms", "axis_hold_ms", "axis_elapsed_s",
            "legend_on_cadence", "legend_extra", "legend_chatter", "legend_miss",
            "legend_overlay", "legend_target", "chart_interval", "chart_interval_trend",
            "interval_distribution", "legend_configured_reference", "legend_host_observation",
            "clicks", "hold_vs_interval",
            "hover_click", "hover_interval", "hover_hold", "hover_interval_delta",
        )
        return {k: self._tr(k) for k in keys}

    def _report_lang(self) -> str:
        return "zh" if self.lang == "zh" else "en"

    def _capture_chart_subtitle(self, settings: dict[str, Any] | None) -> str:
        """Fixture: reference interval in ms first, configured rate second. Manual: no reference."""
        beat = cadence_ms(settings) if settings and not _is_manual_profile(settings) else None
        if not beat:
            return self._tr("chart_stability_map_subtitle")
        return self._tr(
            "chart_stability_map_subtitle_fixture",
            beat=format_reference_interval_ms(beat),
            hz=format_reference_rate_hz(fixture_rate_hz(settings)),
        )

    def _run_status_display(self, status: Any) -> str:
        """Localized label for an authoritative Run Status token; the token itself is unchanged."""
        token = str(status)
        key = f"run_status_{token.lower()}"
        if token in ("COMPLETE", "NO_DATA", "INVALID") and key in STRINGS["en"]:
            return self._tr(key)
        return token

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
        self._workspace_layout = work_l
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

        self.brand_label = QLabel("MCSA")
        self.brand_label.setObjectName("RailBrand")
        layout.addWidget(self.brand_label)
        self.title_label = QLabel(TOOL_NAME)
        self.title_label.setObjectName("RailProduct")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addSpacing(18)

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
        header.setContentsMargins(0, 2, 0, 6)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        self._workspace_header_layout = header
        self._workspace_titles_layout = titles
        self.page_title = QLabel("Setup")
        self.page_title.setObjectName("PageTitle")
        self.page_subtitle = QLabel("")
        self.page_subtitle.setObjectName("PageSubtitle")
        self.page_subtitle.setWordWrap(True)
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        header.addLayout(titles, 1)
        return header

    def _card_title(self, text: str = "") -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("CardTitle")
        return lab

    def _field_label(self, text: str = "") -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("FieldLabel")
        lab.setWordWrap(True)
        self._field_labels.append(lab)
        return lab

    def _setup_field(self, widget: QWidget) -> None:
        widget.setMinimumWidth(160)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _setup_card(self) -> tuple[QFrame, QVBoxLayout]:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 22)
        layout.setSpacing(6)
        return card, layout

    @staticmethod
    def _centered_content_wrap(inner: QWidget) -> QWidget:
        """Content claims the viewport width up to its maximum; only the excess beyond that is split as side margins."""
        inner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        wrap = QWidget()
        wrap_l = QHBoxLayout(wrap)
        wrap_l.setContentsMargins(0, 0, 0, 0)
        wrap_l.setSpacing(0)
        wrap_l.addStretch(0)
        wrap_l.addWidget(inner, 1)
        wrap_l.addStretch(0)
        return wrap

    def _build_setup_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("SetupPage")
        page_l = QVBoxLayout(page)
        page_l.setContentsMargins(0, 0, 0, 0)

        inner = QWidget()
        inner.setObjectName("SetupContent")
        inner.setMaximumWidth(self.MAX_SETUP_CONTENT_WIDTH)
        # Setup content must claim the viewport width rather than its one-column size hint;
        # otherwise ResponsiveCardGrid never sees enough width to reflow upward.
        inner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setup_content = inner
        inner_l = QVBoxLayout(inner)
        inner_l.setContentsMargins(0, 0, 4, 12)
        inner_l.setSpacing(16)

        device_card, device_l = self._setup_card()
        self.setup_device_card = device_card
        self.lbl_setup = self._card_title()
        device_l.addWidget(self.lbl_setup)
        device_l.addSpacing(8)
        self.lbl_device = self._field_label("Device")
        device_l.addWidget(self.lbl_device)
        self.device_edit = QLineEdit(self.target)
        self.device_edit.setPlaceholderText("Device name (optional)")
        self._setup_field(self.device_edit)
        device_l.addWidget(self.device_edit)
        device_l.addSpacing(10)
        self.lbl_button = self._field_label("Button")
        device_l.addWidget(self.lbl_button)
        self.button_combo = QComboBox()
        populate_focus_button_combo(self.button_combo)
        self._setup_field(self.button_combo)
        device_l.addWidget(self.button_combo)
        device_l.addStretch(1)

        config_card, config_l = self._setup_card()
        self.setup_config_card = config_card
        self.lbl_setup_config = self._card_title()
        config_l.addWidget(self.lbl_setup_config)
        config_l.addSpacing(8)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(20)
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

        config_l.addSpacing(10)
        self.hz_label = self._field_label("Reference Rate (Hz)")
        config_l.addWidget(self.hz_label)
        self.hz_combo = QComboBox()
        self.hz_combo.setEditable(True)
        self.hz_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.hz_combo.setCompleter(None)
        self.hz_combo.addItems(["5", "10", "20", "40"])
        self.hz_combo.setCurrentText("10")
        self._setup_field(self.hz_combo)
        config_l.addWidget(self.hz_combo)
        self.hz_interval_label = QLabel("")
        self.hz_interval_label.setObjectName("DerivedValue")
        self.hz_interval_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.hz_interval_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        config_l.addWidget(self.hz_interval_label)
        self.hz_combo.currentTextChanged.connect(self._refresh_fixture_mode_label)

        config_l.addSpacing(10)
        self.timing_tol_label = self._field_label("Schedule Association Window (± ms)")
        config_l.addWidget(self.timing_tol_label)
        self.timing_tol_edit = QLineEdit()
        self.timing_tol_edit.setPlaceholderText("e.g. 2")
        self._setup_field(self.timing_tol_edit)
        config_l.addWidget(self.timing_tol_edit)
        self.assoc_context_box = QWidget()
        self.assoc_context_box.setObjectName("AssociationContext")
        assoc_grid = QGridLayout(self.assoc_context_box)
        assoc_grid.setContentsMargins(0, 6, 0, 0)
        assoc_grid.setHorizontalSpacing(12)
        assoc_grid.setVerticalSpacing(2)
        self._assoc_context_rows: dict[str, tuple[QLabel, QLabel]] = {}
        for row, key in enumerate(("assoc_reference_interval", "assoc_window", "assoc_relative", "assoc_overlap")):
            name = QLabel("")
            value = QLabel("—")
            for lab in (name, value):
                lab.setObjectName("DerivedValue")
                lab.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
                lab.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            assoc_grid.addWidget(name, row, 0)
            assoc_grid.addWidget(value, row, 1)
            self._assoc_context_rows[key] = (name, value)
        assoc_grid.setColumnStretch(1, 1)
        self.assoc_overlap_note = QLabel("")
        self.assoc_overlap_note.setObjectName("DerivedValue")
        self.assoc_overlap_note.setWordWrap(True)
        self.assoc_overlap_note.hide()
        assoc_grid.addWidget(self.assoc_overlap_note, 4, 0, 1, 2)
        self.assoc_derived_note = QLabel("")
        self.assoc_derived_note.setObjectName("DerivedValue")
        self.assoc_derived_note.setWordWrap(True)
        assoc_grid.addWidget(self.assoc_derived_note, 5, 0, 1, 2)
        config_l.addWidget(self.assoc_context_box)
        self.hz_combo.currentTextChanged.connect(self._refresh_association_context)
        self.timing_tol_edit.textChanged.connect(self._refresh_association_context)

        config_l.addSpacing(10)
        self.auto_stop_label = self._field_label("Auto Stop")
        config_l.addWidget(self.auto_stop_label)
        auto_stop_row = QHBoxLayout()
        auto_stop_row.setSpacing(8)
        self.auto_stop_off = QPushButton("")
        self.auto_stop_on = QPushButton("")
        for btn in (self.auto_stop_off, self.auto_stop_on):
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(38)
            btn.setMinimumWidth(80)
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
        config_l.addSpacing(10)
        self.auto_stop_sec_label = self._field_label("Auto Stop After (s)")
        config_l.addWidget(self.auto_stop_sec_label)
        self.auto_stop_sec_combo = QComboBox()
        self.auto_stop_sec_combo.setEditable(True)
        self.auto_stop_sec_combo.addItems(["30", "60", "120", "300"])
        self.auto_stop_sec_combo.setCurrentText("60")
        self._setup_field(self.auto_stop_sec_combo)
        config_l.addWidget(self.auto_stop_sec_combo)
        config_l.addStretch(1)

        screening_card, screening_l = self._setup_card()
        self.setup_screening_card = screening_card
        self.setup_limits_card = screening_card
        self.lbl_screening = self._card_title()
        screening_l.addWidget(self.lbl_screening)
        screening_l.addSpacing(8)
        self.lbl_screening_status = QLabel("Measurement only")
        self.lbl_screening_status.setObjectName("PreviewValue")
        self.lbl_screening_status.setWordWrap(True)
        screening_l.addWidget(self.lbl_screening_status)
        self.lbl_screening_note = QLabel("")
        self.lbl_screening_note.setObjectName("Muted")
        self.lbl_screening_note.setWordWrap(True)
        screening_l.addWidget(self.lbl_screening_note)
        screening_l.addStretch(1)
        self._limit_edits: dict[str, QLineEdit] = {}
        self._limit_labels: dict[str, QLabel] = {}
        self.lbl_custom_limits = self.lbl_screening

        self.setup_card_grid = ResponsiveCardGrid([device_card, config_card, screening_card])
        inner_l.addWidget(self.setup_card_grid)

        profile_card, profile_l = self._setup_card()
        self.setup_profile_card = profile_card
        self.lbl_profile_section = self._card_title()
        profile_l.addWidget(self.lbl_profile_section)
        profile_l.addSpacing(6)
        profile_row = QHBoxLayout()
        profile_row.setSpacing(16)
        self.lbl_profile_status = QLabel("")
        self.lbl_profile_status.setObjectName("ProfileStatus")
        self.lbl_profile_status.setProperty("state", "draft")
        self.lbl_profile_status.setWordWrap(True)
        profile_row.addWidget(self.lbl_profile_status, 1)
        self.btn_lock_profile = QPushButton("Lock Profile && Continue")
        self.btn_lock_profile.setObjectName("Primary")
        self.btn_lock_profile.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lock_profile.setMinimumHeight(42)
        self.btn_lock_profile.setMinimumWidth(220)
        self.btn_lock_profile.clicked.connect(self.lock_profile)
        profile_row.addWidget(self.btn_lock_profile, 0, Qt.AlignmentFlag.AlignVCenter)
        profile_l.addLayout(profile_row)
        inner_l.addWidget(profile_card)

        preview_card, preview_l = self._setup_card()
        self.locked_profile_card = preview_card
        self.lbl_locked_profile_section = self._card_title()
        preview_l.addWidget(self.lbl_locked_profile_section)
        preview_l.addSpacing(6)
        preview_grid = QGridLayout()
        preview_grid.setContentsMargins(0, 0, 0, 0)
        preview_grid.setHorizontalSpacing(28)
        preview_grid.setVerticalSpacing(12)
        self._preview_cells: list[tuple[QWidget, QLabel, QLabel]] = []
        for index in range(6):
            cell = QWidget()
            cell_l = QVBoxLayout(cell)
            cell_l.setContentsMargins(0, 0, 0, 0)
            cell_l.setSpacing(2)
            key_lab = QLabel("")
            key_lab.setObjectName("StatLabel")
            val_lab = QLabel("")
            val_lab.setObjectName("PreviewValue")
            val_lab.setWordWrap(True)
            cell_l.addWidget(key_lab)
            cell_l.addWidget(val_lab)
            row, col = divmod(index, 3)
            preview_grid.addWidget(cell, row, col)
            self._preview_cells.append((cell, key_lab, val_lab))
        for col in range(3):
            preview_grid.setColumnStretch(col, 1)
        preview_l.addLayout(preview_grid)
        preview_card.hide()
        inner_l.addWidget(preview_card)
        inner_l.addStretch(1)

        wrap = QWidget()
        wrap_l = QHBoxLayout(wrap)
        wrap_l.setContentsMargins(0, 0, 0, 0)
        wrap_l.addWidget(inner, 1)
        wrap_l.addStretch(0)

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
        page_l.setSpacing(0)

        inner = QWidget()
        inner.setObjectName("CaptureContent")
        inner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        inner.setMinimumWidth(360)
        self.capture_content = inner
        inner_l = QVBoxLayout(inner)
        inner_l.setContentsMargins(0, 0, 4, 8)
        inner_l.setSpacing(12)
        self._capture_layout = inner_l

        actions = self._card()
        actions.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        actions_l = QVBoxLayout(actions)
        actions_l.setContentsMargins(16, 12, 16, 12)
        actions_l.setSpacing(8)
        self._capture_actions_layout = actions_l
        self.lbl_controls = self._section("CONTROLS")
        actions_l.addWidget(self.lbl_controls)
        self.btn_stop = QPushButton("Stop (F5 / Esc)")
        self.btn_stop.setObjectName("Danger")
        self.btn_stop.clicked.connect(self.stop_run)
        self.btn_arm = QPushButton("Start Capture")
        self.btn_arm.setObjectName("Primary")
        self.btn_arm.clicked.connect(self._on_arm_clicked)
        self.btn_edit_profile = QPushButton("Edit Profile")
        self.btn_edit_profile.setObjectName("Secondary")
        self.btn_edit_profile.clicked.connect(self.edit_profile)
        self.capture_action_bar = WrappingButtonBar([
            self.btn_stop, self.btn_arm, self.btn_edit_profile,
        ])
        actions_l.addWidget(self.capture_action_bar)
        self.btn_capture_new_run = QPushButton("New Run")
        self.btn_capture_new_run.setObjectName("Primary")
        self.btn_capture_new_run.clicked.connect(self.new_run)
        self.btn_capture_goto_results = QPushButton("Results")
        self.btn_capture_goto_results.setObjectName("Secondary")
        self.btn_capture_goto_results.clicked.connect(self._goto_results_from_capture)
        self.btn_capture_edit_setup = QPushButton("Edit Setup")
        self.btn_capture_edit_setup.setObjectName("Secondary")
        self.btn_capture_edit_setup.clicked.connect(self.edit_setup_new_run)
        self.capture_completed_bar = WrappingButtonBar([
            self.btn_capture_new_run, self.btn_capture_goto_results, self.btn_capture_edit_setup,
        ])
        self.capture_completed_bar.hide()
        actions_l.addWidget(self.capture_completed_bar)
        self.capture_actions = actions
        inner_l.addWidget(actions)

        live = self._card()
        live.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.capture_live = live
        live_l = QVBoxLayout(live)
        live_l.setContentsMargins(16, 14, 16, 14)
        live_l.setSpacing(8)
        self._capture_live_layout = live_l
        self.mode_label = QLabel("Manual · Observation")
        self.mode_label.setObjectName("Subtitle")
        live_l.addWidget(self.mode_label)

        phase_cell, self.val_phase = self._stat_cell("PHASE", "phase")
        time_cell, self.val_time = self._stat_cell("TIME", "time")
        clicks_cell, self.val_clicks = self._stat_cell("HOST PRESSES", "host_presses")
        interval_cell, self.val_interval = self._stat_cell("INTERVAL", "interval")
        hold_cell, self.val_hold = self._stat_cell("HOLD", "hold")
        verdict_cell, self.val_verdict = self._stat_cell("RUN STATUS", "run_status")
        # 960 keeps one row at 1280 wide (content ~1014, 6× ~159 px cells) so the chart gets the height.
        self.capture_stats_grid = ResponsiveItemGrid(
            [phase_cell, time_cell, clicks_cell, interval_cell, hold_cell, verdict_cell],
            wide_columns=6,
            medium_columns=3,
            compact_columns=2,
            wide_min_width=960,
            medium_min_width=760,
        )
        live_l.addWidget(self.capture_stats_grid)

        self.issue_title = QLabel("OBSERVATIONS")
        self.issue_title.setObjectName("StatLabel")
        live_l.addWidget(self.issue_title)
        extra_cell, self.val_extra = self._stat_cell("EXTRA", "extra")
        rebound_cell, self.val_rebound = self._stat_cell("REBOUND", "rebound")
        delay_cell, self.val_delay = self._stat_cell("DELAY", "delay")
        dut_cell, self.val_dut = self._stat_cell("DUT", "dut")
        setup_cell, self.val_setup = self._stat_cell("SETUP", "setup_score")
        self._hidden_score_cells = (dut_cell, setup_cell)
        for cell in self._hidden_score_cells:
            cell.setParent(self)
            cell.hide()
        self.capture_issues_grid = ResponsiveItemGrid(
            [extra_cell, rebound_cell, delay_cell],
            wide_columns=3,
            medium_columns=3,
            compact_columns=2,
            wide_min_width=940,
            medium_min_width=760,
        )
        live_l.addWidget(self.capture_issues_grid)

        self.status_label = QLabel("Click in the Test Area to start.")
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        self.alert_label = QLabel("")
        self.alert_label.setObjectName("Alert")
        self.alert_label.setWordWrap(True)
        self.overlay_delta_label = QLabel("")
        self.overlay_delta_label.setObjectName("OverlayDelta")
        self.overlay_delta_label.setWordWrap(True)
        live_l.addWidget(self.status_label)
        live_l.addWidget(self.alert_label)
        live_l.addWidget(self.overlay_delta_label)
        self.capture_completed_note = QLabel("")
        self.capture_completed_note.setObjectName("Muted")
        self.capture_completed_note.setWordWrap(True)
        self.capture_completed_note.hide()
        live_l.addWidget(self.capture_completed_note)
        inner_l.addWidget(live)

        viz = self._card()
        viz.setObjectName("CaptureVizToolbar")
        viz.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        viz_l = QHBoxLayout(viz)
        viz_l.setContentsMargins(8, 4, 8, 4)
        viz_l.setSpacing(6)
        self._capture_viz_layout = viz_l
        self.btn_view_stability = QPushButton("Stability Map")
        self.btn_view_stability.setObjectName("Segment")
        self.btn_view_stability.setCheckable(True)
        self.btn_view_stability.setChecked(True)
        self.btn_view_interval = QPushButton("Interval Trend")
        self.btn_view_interval.setObjectName("Segment")
        self.btn_view_interval.setCheckable(True)
        self.btn_chart_fit = QPushButton("Fit Data")
        self.btn_chart_fit.setObjectName("Secondary")
        self.btn_chart_zoom_in = QPushButton("Zoom In")
        self.btn_chart_zoom_in.setObjectName("Secondary")
        self.btn_chart_zoom_out = QPushButton("Zoom Out")
        self.btn_chart_zoom_out.setObjectName("Secondary")
        self.btn_chart_reset = QPushButton("Reset View")
        self.btn_chart_reset.setObjectName("Secondary")
        for btn in (
            self.btn_view_stability, self.btn_view_interval,
            self.btn_chart_fit, self.btn_chart_zoom_in,
            self.btn_chart_zoom_out, self.btn_chart_reset,
        ):
            btn.setMinimumHeight(28)
            btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.capture_view_group = QButtonGroup(self)
        self.capture_view_group.setExclusive(True)
        self.capture_view_group.addButton(self.btn_view_stability, 0)
        self.capture_view_group.addButton(self.btn_view_interval, 1)
        self.capture_view_group.idClicked.connect(self._on_capture_view_id)
        self.btn_chart_fit.clicked.connect(self._on_capture_fit_data)
        self.btn_chart_zoom_in.clicked.connect(self._on_capture_zoom_in)
        self.btn_chart_zoom_out.clicked.connect(self._on_capture_zoom_out)
        self.btn_chart_reset.clicked.connect(self._on_capture_reset_view)
        viz_l.addWidget(self.btn_view_stability)
        viz_l.addWidget(self.btn_view_interval)
        viz_l.addStretch(1)
        viz_l.addWidget(self.btn_chart_fit)
        viz_l.addWidget(self.btn_chart_zoom_in)
        viz_l.addWidget(self.btn_chart_zoom_out)
        viz_l.addWidget(self.btn_chart_reset)
        self.capture_viz_bar = viz
        self.capture_viz_toolbar = viz
        inner_l.addWidget(viz)

        self.test_area = QFrame()
        self.test_area.setObjectName("TestArea")
        self.test_area.setProperty("active", False)
        self.test_area.setMinimumHeight(320)
        self.test_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        ta_l = QVBoxLayout(self.test_area)
        self._test_area_layout = ta_l
        self._test_area_default_margins = ta_l.contentsMargins()
        self.hint = QLabel("TEST AREA\nLock the Setup profile, then Start Capture.\nStop with F5 or Esc")
        self.hint.setObjectName("Hint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(True)
        ta_l.addWidget(self.hint)
        self.scatter = ScatterChart()
        self.interval_chart = IntervalChart()
        self.scatter.set_data_aware_fit(True)
        self.interval_chart.set_data_aware_fit(True)
        self.scatter.set_measurement_only_presentation(True)
        self.interval_chart.set_measurement_only_presentation(True)
        self.scatter.title = self._tr("chart_stability_map")
        self.scatter.subtitle = self._tr("chart_stability_map_subtitle")
        self.interval_chart.title = self._tr("chart_interval_trend")
        self.scatter.setMinimumHeight(220)
        self.interval_chart.setMinimumHeight(220)
        self.scatter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.interval_chart.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.capture_chart_stack = QStackedWidget()
        self.capture_chart_stack.setObjectName("CaptureChartStack")
        self.capture_chart_stack.addWidget(self.scatter)
        self.capture_chart_stack.addWidget(self.interval_chart)
        self._capture_view = "stability"
        self.capture_chart_stack.setCurrentIndex(0)
        ta_l.addWidget(self.capture_chart_stack, 1)

        self.review_text = QTextEdit()
        self.review_text.setReadOnly(True)
        self.review_text.setMinimumHeight(160)
        self.review_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.review_text.hide()

        self.capture_splitter = QSplitter(Qt.Orientation.Vertical)
        self.capture_splitter.setObjectName("CaptureSplitter")
        self.capture_splitter.setChildrenCollapsible(False)
        self.capture_splitter.setMinimumHeight(320)
        self.capture_splitter.addWidget(self.test_area)
        self.capture_splitter.addWidget(self.review_text)
        self.capture_splitter.setStretchFactor(0, 3)
        self.capture_splitter.setStretchFactor(1, 1)
        self.capture_splitter.setSizes([1, 0])
        inner_l.addWidget(self.capture_splitter, 1)

        self.capture_scroll = QScrollArea()
        self.capture_scroll.setObjectName("PageScroll")
        self.capture_scroll.setWidgetResizable(True)
        self.capture_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.capture_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.capture_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.capture_scroll.setWidget(inner)
        page_l.addWidget(self.capture_scroll)
        return page

    def _build_results_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("ResultsPage")
        page_l = QVBoxLayout(page)
        page_l.setContentsMargins(0, 0, 0, 0)

        inner = QWidget()
        inner.setObjectName("ResultsContent")
        inner.setMaximumWidth(self.MAX_SETUP_CONTENT_WIDTH)
        inner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.results_content = inner
        inner_l = QVBoxLayout(inner)
        inner_l.setContentsMargins(0, 0, 4, 12)
        inner_l.setSpacing(12)

        empty_card, empty_l = self._setup_card()
        self.results_empty_card = empty_card
        self.results_placeholder = QLabel("")
        self.results_placeholder.setObjectName("Muted")
        self.results_placeholder.setWordWrap(True)
        empty_l.addWidget(self.results_placeholder)
        inner_l.addWidget(empty_card)

        self.results_workspace = QWidget()
        self.results_workspace.setObjectName("Workspace")
        work_l = QVBoxLayout(self.results_workspace)
        work_l.setContentsMargins(0, 0, 0, 0)
        work_l.setSpacing(12)

        self.results_input_guard_status = QLabel("")
        self.results_input_guard_status.setObjectName("Muted")
        self.results_input_guard_status.setWordWrap(True)
        self.results_input_guard_status.hide()
        work_l.addWidget(self.results_input_guard_status)

        context_card, context_l = self._setup_card()
        self.results_summary_card = context_card
        self.lbl_results_summary = self._card_title()
        context_l.addWidget(self.lbl_results_summary)
        self.results_context_label = QLabel("")
        self.results_context_label.setObjectName("PreviewValue")
        self.results_context_label.setWordWrap(True)
        context_l.addWidget(self.results_context_label)
        self._results_summary_cells: list[tuple[QWidget, QLabel, QLabel]] = []

        assess_card, assess_l = self._setup_card()
        self.results_assessment_card = assess_card
        self.lbl_results_run_status = self._card_title()
        assess_l.addWidget(self.lbl_results_run_status)
        self.results_verdict_label = QLabel("--")
        self.results_verdict_label.setObjectName("StatValue")
        self.results_verdict_label.setWordWrap(True)
        assess_l.addWidget(self.results_verdict_label)
        self.results_tags_label = QLabel("")
        self.results_tags_label.setObjectName("Muted")
        self.results_tags_label.setWordWrap(True)
        assess_l.addWidget(self.results_tags_label)
        assess_l.addStretch(1)
        context_l.addStretch(1)
        self.results_header_grid = ResponsiveItemGrid(
            [context_card, assess_card],
            wide_columns=2,
            medium_columns=2,
            compact_columns=1,
            wide_min_width=self.RESULTS_TWO_COLUMN_MIN_WIDTH,
            medium_min_width=self.RESULTS_TWO_COLUMN_MIN_WIDTH,
            h_spacing=12,
            v_spacing=12,
        )
        work_l.addWidget(self.results_header_grid)

        self.results_tabs = QTabWidget()
        self.results_tabs.setObjectName("ResultsTabs")
        self.results_tabs.setDocumentMode(True)
        self.results_tabs.currentChanged.connect(lambda _index: self._schedule_results_layout_sync())
        work_l.addWidget(self.results_tabs, 1)

        analysis_page = QWidget()
        analysis_l = QVBoxLayout(analysis_page)
        analysis_l.setContentsMargins(0, 8, 0, 0)
        analysis_l.setSpacing(8)
        analysis_header = QHBoxLayout()
        self.lbl_analysis_view = QLabel("")
        self.lbl_analysis_view.setObjectName("Muted")
        self.results_view_combo = QComboBox()
        self.results_view_combo.setMinimumWidth(180)
        self.results_view_combo.currentIndexChanged.connect(self._on_analysis_view_changed)
        analysis_header.addWidget(self.lbl_analysis_view)
        analysis_header.addWidget(self.results_view_combo, 1)
        self.btn_overlay = QPushButton("Compare Overlay")
        self.btn_overlay.setObjectName("Secondary")
        self.btn_overlay.clicked.connect(self.load_overlay_run)
        self.btn_clear_overlay = QPushButton("Clear Overlay")
        self.btn_clear_overlay.setObjectName("Secondary")
        self.btn_clear_overlay.clicked.connect(self.clear_overlay)
        self.results_overlay_bar = ShrinkableButtonBar([self.btn_overlay, self.btn_clear_overlay])
        analysis_header.addWidget(self.results_overlay_bar, 1)
        analysis_l.addLayout(analysis_header)
        self.results_overlay_status = QLabel("")
        self.results_overlay_status.setObjectName("OverlayDelta")
        self.results_overlay_status.setWordWrap(True)
        analysis_l.addWidget(self.results_overlay_status)

        self.results_analysis_split = QSplitter(Qt.Orientation.Horizontal)
        chart_host = QWidget()
        chart_l = QVBoxLayout(chart_host)
        chart_l.setContentsMargins(0, 0, 0, 0)
        self.results_chart_stack = QStackedWidget()
        self.results_interval_chart = IntervalChart()
        self.results_distribution_chart = HistogramChart()
        self.results_scatter = ScatterChart()
        self.results_interval_chart.set_measurement_only_presentation(True)
        self.results_distribution_chart.set_measurement_only_presentation(True)
        self.results_scatter.set_measurement_only_presentation(True)
        self.results_timing_panel = QWidget()
        timing_l = QVBoxLayout(self.results_timing_panel)
        timing_l.setContentsMargins(12, 12, 12, 12)
        self.results_timing_title = QLabel("")
        self.results_timing_title.setObjectName("CardTitle")
        self.results_timing_text = QLabel("")
        self.results_timing_text.setObjectName("Muted")
        self.results_timing_text.setWordWrap(True)
        timing_l.addWidget(self.results_timing_title)
        timing_l.addWidget(self.results_timing_text)
        timing_l.addStretch(1)
        self.results_chart_stack.addWidget(self.results_interval_chart)
        self.results_chart_stack.addWidget(self.results_distribution_chart)
        self.results_chart_stack.addWidget(self.results_scatter)
        self.results_chart_stack.addWidget(self.results_timing_panel)
        chart_l.addWidget(self.results_chart_stack, 1)
        self.results_chart_legend_help = QLabel("")
        self.results_chart_legend_help.setObjectName("Muted")
        self.results_chart_legend_help.setWordWrap(True)
        chart_l.addWidget(self.results_chart_legend_help)
        self.results_analysis_split.addWidget(chart_host)

        observations_card, observations_l = self._setup_card()
        self.results_observations_card = observations_card
        self.lbl_results_observations = self._card_title()
        observations_l.addWidget(self.lbl_results_observations)
        self.results_observations_text = QLabel("")
        self.results_observations_text.setObjectName("Muted")
        self.results_observations_text.setWordWrap(True)
        self.results_observations_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        observations_l.addWidget(self.results_observations_text)
        observations_l.addStretch(1)
        observations_card.setMinimumWidth(240)
        self.results_analysis_split.addWidget(observations_card)
        self.results_analysis_split.setChildrenCollapsible(False)
        self.results_analysis_split.setStretchFactor(0, 7)
        self.results_analysis_split.setStretchFactor(1, 3)
        self._results_split_synced_extent = -1
        analysis_l.addWidget(self.results_analysis_split, 1)
        self.results_tabs.addTab(analysis_page, "Analysis")
        self.results_analysis_page = analysis_page

        evidence_page = QWidget()
        evidence_outer = QVBoxLayout(evidence_page)
        evidence_outer.setContentsMargins(0, 8, 0, 0)
        evidence_card, evidence_l = self._setup_card()
        self.results_evidence_card = evidence_card
        self.lbl_results_evidence = self._card_title()
        evidence_l.addWidget(self.lbl_results_evidence)
        self.results_evidence_na = QLabel("")
        self.results_evidence_na.setObjectName("Muted")
        self.results_evidence_na.setWordWrap(True)
        evidence_l.addWidget(self.results_evidence_na)
        self.results_evidence_body = QWidget()
        self.results_evidence_body.setObjectName("Workspace")
        body_l = QVBoxLayout(self.results_evidence_body)
        body_l.setContentsMargins(0, 0, 0, 0)
        body_l.setSpacing(10)
        self.results_occupancy_bar = OccupancyBar()
        body_l.addWidget(self.results_occupancy_bar)
        self._results_evidence_cells: list[tuple[QLabel, QLabel]] = []
        # Row counts per group (header + values) must match _populate_evidence_tab's row order:
        # Schedule, Host observations, Occupancy, Association, Matched timing.
        self.results_evidence_groups: list[QWidget] = []
        for size in (4, 4, 4, 5, 9):
            group = QWidget()
            group.setObjectName("Workspace")
            group_grid = QGridLayout(group)
            group_grid.setContentsMargins(0, 0, 0, 0)
            group_grid.setHorizontalSpacing(16)
            group_grid.setVerticalSpacing(6)
            group_grid.setColumnStretch(1, 1)
            for row in range(size):
                key_lab = QLabel("")
                key_lab.setObjectName("StatLabel")
                val_lab = QLabel("")
                val_lab.setObjectName("PreviewValue")
                val_lab.setWordWrap(True)
                group_grid.addWidget(key_lab, row, 0)
                group_grid.addWidget(val_lab, row, 1)
                self._results_evidence_cells.append((key_lab, val_lab))
            group_grid.setRowStretch(size, 1)
            self.results_evidence_groups.append(group)
        self.results_evidence_grid = ResponsiveItemGrid(
            self.results_evidence_groups,
            wide_columns=3,
            medium_columns=2,
            compact_columns=1,
            wide_min_width=self.RESULTS_EVIDENCE_THREE_COLUMN_MIN_WIDTH,
            medium_min_width=self.RESULTS_EVIDENCE_TWO_COLUMN_MIN_WIDTH,
            h_spacing=32,
            v_spacing=16,
        )
        body_l.addWidget(self.results_evidence_grid)
        evidence_l.addWidget(self.results_evidence_body)
        self.results_evidence_note = QLabel("")
        self.results_evidence_note.setObjectName("Muted")
        self.results_evidence_note.setWordWrap(True)
        evidence_l.addWidget(self.results_evidence_note)
        self.results_evidence_text = QTextEdit()
        self.results_evidence_text.setObjectName("ResultsEvidence")
        self.results_evidence_text.setReadOnly(True)
        self.results_evidence_text.hide()
        evidence_l.addWidget(self.results_evidence_text)
        evidence_outer.addWidget(evidence_card)
        evidence_outer.addStretch(1)
        self.results_tabs.addTab(evidence_page, "Evidence")
        self.results_evidence_page = evidence_page

        clicks_page = QWidget()
        clicks_l = QVBoxLayout(clicks_page)
        clicks_l.setContentsMargins(0, 8, 0, 0)
        sort_bar = QHBoxLayout()
        sort_bar.setContentsMargins(0, 0, 0, 8)
        sort_bar.setSpacing(8)
        self.lbl_click_sort_by = QLabel("Sort by:")
        self.lbl_click_sort_by.setObjectName("Muted")
        self.click_sort_column_combo = QComboBox()
        self.click_sort_column_combo.setObjectName("ClickSortColumnCombo")
        self.click_sort_column_combo.currentIndexChanged.connect(self._on_click_sort_column_changed)
        self.lbl_click_sort_order = QLabel("Order:")
        self.lbl_click_sort_order.setObjectName("Muted")
        self.click_sort_order_combo = QComboBox()
        self.click_sort_order_combo.setObjectName("ClickSortOrderCombo")
        self.click_sort_order_combo.currentIndexChanged.connect(self._on_click_sort_order_changed)
        sort_bar.addWidget(self.lbl_click_sort_by)
        sort_bar.addWidget(self.click_sort_column_combo)
        sort_bar.addWidget(self.lbl_click_sort_order)
        sort_bar.addWidget(self.click_sort_order_combo)
        sort_bar.addStretch(1)
        for combo in (self.click_sort_column_combo, self.click_sort_order_combo):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.click_sort_column_combo.setMinimumContentsLength(8)
        self.click_sort_order_combo.setMinimumContentsLength(8)
        clicks_l.addLayout(sort_bar)
        self.results_click_table = QTableWidget(0, len(CLICK_TABLE_COLUMN_IDS))
        self.results_click_table.setObjectName("ResultsClickTable")
        self.results_click_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_click_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_click_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_click_table.verticalHeader().setVisible(False)
        self.results_click_table.setSortingEnabled(False)
        self.results_click_table.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.results_click_table.setMinimumWidth(0)
        clicks_page.setMinimumWidth(0)
        clicks_page.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        click_header = self.results_click_table.horizontalHeader()
        click_header.setStretchLastSection(True)
        click_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        click_header.setSectionsClickable(True)
        click_header.setSortIndicatorShown(True)
        self._click_sort_id = "index"
        self._click_sort_descending = False
        click_header.setSortIndicator(CLICK_TABLE_ID_TO_INDEX["index"], Qt.SortOrder.AscendingOrder)
        click_header.sortIndicatorChanged.connect(self._on_click_sort_indicator_changed)
        self.results_click_table.itemSelectionChanged.connect(self._on_click_table_selection_changed)
        clicks_l.addWidget(self.results_click_table)
        self._fill_click_sort_controls()
        self._apply_click_table_column_visibility()
        self.results_tabs.addTab(clicks_page, "Click Data")
        self.results_clicks_page = clicks_page

        actions_card, actions_card_l = self._setup_card()
        self.results_actions_card = actions_card
        next_run_group = QWidget()
        next_run_group.setObjectName("Workspace")
        actions_l = QVBoxLayout(next_run_group)
        actions_l.setContentsMargins(0, 0, 0, 0)
        actions_l.setSpacing(6)
        self.lbl_results_actions = self._card_title()
        actions_l.addWidget(self.lbl_results_actions)
        actions_l.addSpacing(8)
        self.btn_new = QPushButton("Run Again")
        self.btn_new.setObjectName("Primary")
        self.btn_new.clicked.connect(self.new_run)
        self.btn_edit_setup_new_run = QPushButton("Edit Setup && New Run")
        self.btn_edit_setup_new_run.setObjectName("Secondary")
        self.btn_edit_setup_new_run.clicked.connect(self.edit_setup_new_run)
        self.results_lifecycle_bar = ShrinkableButtonBar([self.btn_new, self.btn_edit_setup_new_run])
        actions_l.addWidget(self.results_lifecycle_bar)
        self.results_next_run_note = QLabel("")
        self.results_next_run_note.setObjectName("Muted")
        self.results_next_run_note.setWordWrap(True)
        self.results_next_run_note.hide()
        actions_l.addWidget(self.results_next_run_note)
        actions_l.addStretch(1)

        report_group = QWidget()
        report_group.setObjectName("Workspace")
        report_l = QVBoxLayout(report_group)
        report_l.setContentsMargins(0, 0, 0, 0)
        report_l.setSpacing(6)
        self.lbl_results_report = self._card_title()
        report_l.addWidget(self.lbl_results_report)
        report_l.addSpacing(8)
        self.btn_generate_excel = QPushButton("Generate Excel")
        self.btn_generate_excel.setObjectName("Primary")
        self.btn_generate_excel.clicked.connect(self.generate_excel_report)
        self.btn_finish = self.btn_generate_excel
        self.btn_generate_html = QPushButton("Generate HTML")
        self.btn_generate_html.setObjectName("Primary")
        self.btn_generate_html.clicked.connect(self.generate_html_report)
        self.btn_export = QToolButton()
        self.btn_export.setObjectName("Secondary")
        self.btn_export.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_export.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.export_menu = QMenu(self.btn_export)
        self.act_export_txt = self.export_menu.addAction("Analysis TXT")
        self.act_export_csv = self.export_menu.addAction("Click Log CSV")
        self.act_export_summary_json = self.export_menu.addAction("Summary JSON")
        self.act_export_detail_json = self.export_menu.addAction("Detail JSON")
        self.export_menu.addSeparator()
        self.act_save_report_as = self.export_menu.addAction("Save Report As…")
        self.act_export_txt.triggered.connect(lambda: self.export_report_artifact("txt"))
        self.act_export_csv.triggered.connect(lambda: self.export_report_artifact("all_click_log_csv"))
        self.act_export_summary_json.triggered.connect(lambda: self.export_report_artifact("summary_json"))
        self.act_export_detail_json.triggered.connect(lambda: self.export_report_artifact("detail_json"))
        self.act_save_report_as.triggered.connect(self.save_report_as)
        self.btn_export.setMenu(self.export_menu)
        self.btn_save = self.btn_export
        self.results_report_bar = ShrinkableButtonBar([
            self.btn_generate_excel, self.btn_generate_html, self.btn_export,
        ])
        report_l.addWidget(self.results_report_bar)
        report_l.addStretch(1)
        self.results_action_bar = self.results_report_bar
        self.results_compare_bar = self.results_lifecycle_bar
        self.results_actions_grid = ResponsiveItemGrid(
            [next_run_group, report_group],
            wide_columns=2,
            medium_columns=2,
            compact_columns=1,
            wide_min_width=self.RESULTS_TWO_COLUMN_MIN_WIDTH,
            medium_min_width=self.RESULTS_TWO_COLUMN_MIN_WIDTH,
            h_spacing=32,
            v_spacing=16,
        )
        actions_card_l.addWidget(self.results_actions_grid)
        work_l.addWidget(actions_card)

        inner_l.addWidget(self.results_workspace)
        inner_l.addStretch(1)

        self.results_scroll = QScrollArea()
        self.results_scroll.setObjectName("PageScroll")
        self.results_scroll.setWidgetResizable(True)
        self.results_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.results_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.results_scroll.setWidget(self._centered_content_wrap(inner))
        page_l.addWidget(self.results_scroll)
        self._refresh_results_workspace()
        return page

    def _build_preferences_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("PreferencesPage")
        page_l = QVBoxLayout(page)
        page_l.setContentsMargins(0, 0, 0, 0)

        inner = QWidget()
        inner.setObjectName("PreferencesContent")
        inner.setMaximumWidth(self.MAX_SETUP_CONTENT_WIDTH)
        self.preferences_content = inner
        inner_l = QVBoxLayout(inner)
        inner_l.setContentsMargins(0, 0, 4, 12)
        inner_l.setSpacing(16)

        appearance_card, appearance_l = self._setup_card()
        self.pref_appearance_card = appearance_card
        self.lbl_pref_appearance = self._card_title()
        appearance_l.addWidget(self.lbl_pref_appearance)
        appearance_l.addSpacing(8)
        self.lbl_theme = self._field_label("Theme")
        appearance_l.addWidget(self.lbl_theme)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.setCurrentIndex(0 if self.theme == "light" else 1)
        self.theme_combo.setMinimumWidth(240)
        self.theme_combo.setMaximumWidth(360)
        self.theme_combo.setMinimumHeight(36)
        self.theme_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        appearance_l.addWidget(self.theme_combo)

        language_card, language_l = self._setup_card()
        self.pref_language_card = language_card
        self.lbl_pref_language = self._card_title()
        language_l.addWidget(self.lbl_pref_language)
        language_l.addSpacing(8)
        self.lbl_lang = self._field_label("Display Language")
        language_l.addWidget(self.lbl_lang)
        self.lang_combo = QComboBox()
        for code in SUPPORTED_LANGS:
            self.lang_combo.addItem(LANG_LABELS.get(code, code), code)
        idx = SUPPORTED_LANGS.index(self.lang) if self.lang in SUPPORTED_LANGS else 0
        self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.setMinimumWidth(240)
        self.lang_combo.setMaximumWidth(360)
        self.lang_combo.setMinimumHeight(36)
        self.lang_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        language_l.addWidget(self.lang_combo)

        window_card, window_l = self._setup_card()
        self.pref_window_card = window_card
        self.lbl_pref_window = self._card_title()
        window_l.addWidget(self.lbl_pref_window)
        window_l.addSpacing(8)
        self.lbl_startup_window = self._field_label("Startup Window")
        window_l.addWidget(self.lbl_startup_window)
        self.startup_window_combo = QComboBox()
        for mode in WINDOW_MODES:
            self.startup_window_combo.addItem(mode, mode)
        self.startup_window_combo.setCurrentIndex(WINDOW_MODES.index(self.window_mode))
        self.startup_window_combo.setMinimumWidth(240)
        self.startup_window_combo.setMaximumWidth(360)
        self.startup_window_combo.setMinimumHeight(36)
        self.startup_window_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.startup_window_combo.currentIndexChanged.connect(self._on_window_mode_changed)
        self.startup_window_combo.activated.connect(self._on_window_mode_activated)
        window_l.addWidget(self.startup_window_combo)
        self.window_fit_note = QLabel("")
        self.window_fit_note.setObjectName("Muted")
        self.window_fit_note.setWordWrap(True)
        window_l.addWidget(self.window_fit_note)

        self.custom_window_panel = QWidget()
        self.custom_window_panel.setObjectName("Workspace")
        custom_l = QVBoxLayout(self.custom_window_panel)
        custom_l.setContentsMargins(0, 8, 0, 0)
        custom_l.setSpacing(6)
        self.lbl_custom_window = self._field_label("Custom Window Size")
        custom_l.addWidget(self.lbl_custom_window)
        size_row = QGridLayout()
        size_row.setHorizontalSpacing(12)
        size_row.setVerticalSpacing(4)
        self.lbl_custom_width = QLabel("Width")
        self.lbl_custom_width.setObjectName("Muted")
        self.lbl_custom_height = QLabel("Height")
        self.lbl_custom_height.setObjectName("Muted")
        self.custom_width_spin = self._custom_size_spin(self.minimumWidth(), CUSTOM_WINDOW_MAX_SIZE[0])
        self.custom_height_spin = self._custom_size_spin(self.minimumHeight(), CUSTOM_WINDOW_MAX_SIZE[1])
        size_row.addWidget(self.lbl_custom_width, 0, 0)
        size_row.addWidget(self.lbl_custom_height, 0, 1)
        size_row.addWidget(self.custom_width_spin, 1, 0)
        size_row.addWidget(self.custom_height_spin, 1, 1)
        size_row.setColumnStretch(2, 1)
        custom_l.addLayout(size_row)
        self.apply_custom_size_button = QPushButton("Apply Custom Size")
        self.apply_custom_size_button.setObjectName("Secondary")
        self.apply_custom_size_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_custom_size_button.setMinimumHeight(36)
        self.apply_custom_size_button.clicked.connect(lambda: self.apply_custom_window_size())
        custom_l.addWidget(self.apply_custom_size_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.custom_size_status = QLabel("")
        self.custom_size_status.setObjectName("Muted")
        self.custom_size_status.setWordWrap(True)
        custom_l.addWidget(self.custom_size_status)
        self.custom_width_spin.valueChanged.connect(self._sync_custom_size_status)
        self.custom_height_spin.valueChanged.connect(self._sync_custom_size_status)
        window_l.addWidget(self.custom_window_panel)
        self._seed_custom_size_fields()
        self._sync_custom_window_panel()

        window_l.addSpacing(10)
        self.remember_window_size_checkbox = QCheckBox("Remember last window size and position")
        self.remember_window_size_checkbox.setChecked(self.remember_window_geometry)
        self.remember_window_size_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remember_window_size_checkbox.toggled.connect(self._on_remember_window_toggled)
        window_l.addWidget(self.remember_window_size_checkbox)
        self.remember_window_size_note = QLabel("")
        self.remember_window_size_note.setObjectName("Muted")
        self.remember_window_size_note.setWordWrap(True)
        window_l.addWidget(self.remember_window_size_note)
        window_l.addSpacing(10)
        self.reset_window_geometry_button = QPushButton("Reset Window Size && Position")
        self.reset_window_geometry_button.setObjectName("Secondary")
        self.reset_window_geometry_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_window_geometry_button.setMinimumHeight(38)
        self.reset_window_geometry_button.clicked.connect(self.reset_window_geometry)
        window_l.addWidget(self.reset_window_geometry_button, 0, Qt.AlignmentFlag.AlignLeft)
        window_l.addStretch(1)

        side_column = QWidget()
        side_column.setObjectName("Workspace")
        side_l = QVBoxLayout(side_column)
        side_l.setContentsMargins(0, 0, 0, 0)
        side_l.setSpacing(16)
        side_l.addWidget(appearance_card)
        side_l.addWidget(language_card)
        side_l.addStretch(1)
        self.preferences_side_column = side_column
        self.preferences_grid = ResponsiveItemGrid(
            [side_column, window_card],
            wide_columns=2,
            medium_columns=2,
            compact_columns=1,
            wide_min_width=self.PREFERENCES_TWO_COLUMN_MIN_WIDTH,
            medium_min_width=self.PREFERENCES_TWO_COLUMN_MIN_WIDTH,
            h_spacing=16,
            v_spacing=16,
            column_stretches=(2, 3),
        )
        inner_l.addWidget(self.preferences_grid)

        self.preferences_note = QLabel("")
        self.preferences_note.setObjectName("Muted")
        self.preferences_note.setWordWrap(True)
        inner_l.addWidget(self.preferences_note)
        inner_l.addStretch(1)

        self.preferences_scroll = QScrollArea()
        self.preferences_scroll.setObjectName("PageScroll")
        self.preferences_scroll.setWidgetResizable(True)
        self.preferences_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.preferences_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.preferences_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.preferences_scroll.setWidget(self._centered_content_wrap(inner))
        page_l.addWidget(self.preferences_scroll)
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
        if name == "results":
            self._schedule_results_layout_sync()
            if self.completed and getattr(self, "results_scroll", None) is not None:
                self.results_scroll.verticalScrollBar().setValue(0)

    def _set_review_panel_visible(self, visible: bool) -> None:
        if visible:
            self.review_text.show()
            total = max(self.capture_splitter.height(), 480)
            review = max(160, min(int(total * 0.32), total - 280))
            self.capture_splitter.setSizes([max(total - review, 280), review])
        else:
            self.review_text.hide()
            self.capture_splitter.setSizes([1, 0])

    def _section(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("StatLabel")
        self._section_labels.append(lab)
        return lab

    def _stat_cell(self, name: str, key: str) -> tuple[QWidget, QLabel]:
        lab = QLabel(name)
        lab.setObjectName("StatLabel")
        lab.setWordWrap(True)
        self._stat_name_labels[key] = lab
        val = QLabel("--")
        val.setObjectName("StatValue")
        val.setWordWrap(True)
        cell = QWidget()
        cell.setObjectName("StatCell")
        box = QVBoxLayout(cell)
        box.setContentsMargins(4, 2, 4, 2)
        box.setSpacing(2)
        box.addWidget(lab)
        box.addWidget(val)
        cell.setMinimumWidth(108)
        cell.setMinimumHeight(48)
        return cell, val

    @property
    def density(self) -> str:
        return self._density

    def _sync_density(self) -> None:
        """Switch the compact/normal tier only when the window crosses a tier boundary."""
        if getattr(self, "_density_sync_active", True) or not hasattr(self, "test_area"):
            return
        density = density_for_size(self.width(), self.height())
        if density == self._density:
            return
        self._density_sync_active = True
        try:
            self._density = density
            self._apply_density_layout()
            self._apply_theme()
        finally:
            self._density_sync_active = False

    def _apply_density_layout(self) -> None:
        """Presentation-only spacing; never touches run data or Test Area acceptance rules."""
        d = self._density

        def margins(layout, name):
            layout.setContentsMargins(*layout_metric(name, d))

        self._workspace_layout.setSpacing(layout_metric("workspace_gap", d))
        margins(self._workspace_header_layout, "header_margins")
        self._workspace_titles_layout.setSpacing(layout_metric("header_gap", d))
        self._capture_layout.setSpacing(layout_metric("capture_gap", d))
        margins(self._capture_actions_layout, "actions_margins")
        margins(self._capture_live_layout, "live_margins")
        self._capture_actions_layout.setSpacing(layout_metric("card_gap", d))
        self._capture_live_layout.setSpacing(layout_metric("card_gap", d))
        margins(self._capture_viz_layout, "toolbar_margins")
        ta_margins = layout_metric("test_area_margins", d)
        if ta_margins is None:
            self._test_area_layout.setContentsMargins(self._test_area_default_margins)
        else:
            self._test_area_layout.setContentsMargins(*ta_margins)
        action_h = layout_metric("action_button_min_h", d)
        for btn in (*self.capture_action_bar._buttons, *self.capture_completed_bar._buttons):
            btn.setMinimumHeight(action_h)
        toolbar_h = layout_metric("toolbar_button_min_h", d)
        for btn in (
            self.btn_view_stability, self.btn_view_interval,
            self.btn_chart_fit, self.btn_chart_zoom_in,
            self.btn_chart_zoom_out, self.btn_chart_reset,
        ):
            btn.setMinimumHeight(toolbar_h)
        cell_h = layout_metric("stat_cell_min_h", d)
        for lab in self._stat_name_labels.values():
            cell = lab.parentWidget()
            if cell is not None and cell.objectName() == "StatCell":
                cell.setMinimumHeight(cell_h)
        test_area_h = layout_metric("test_area_min_h", d)
        self.test_area.setMinimumHeight(test_area_h)
        self.capture_splitter.setMinimumHeight(test_area_h)
        chart_h = layout_metric("chart_min_h", d)
        self.scatter.setMinimumHeight(chart_h)
        self.interval_chart.setMinimumHeight(chart_h)

    def _apply_theme(self):
        app = QApplication.instance()
        if app:
            app.setStyleSheet(get_style(self.theme, self._density))
        pal = get_palette(self.theme)
        labels = self._chart_labels()
        self.scatter.set_theme(pal, labels)
        self.interval_chart.set_theme(pal, labels)
        if getattr(self, "results_interval_chart", None) is not None:
            self.results_interval_chart.set_theme(pal, labels)
            self.results_distribution_chart.set_theme(pal, labels)
            self.results_scatter.set_theme(pal, labels)
            self.results_occupancy_bar.set_theme(pal)

    def _on_theme_changed(self):
        self.theme = self.theme_combo.currentData() or "light"
        self._apply_theme()
        self._retranslate_ui()
        self._update_controls()

    def _on_lang_changed(self):
        self.lang = normalize_lang(self.lang_combo.currentData())
        self._retranslate_ui()
        self._apply_mode_fields()
        self._apply_theme()
        self._refresh_live_texts()
        self._update_controls()

    def _window_pref(self, key: str, default: Any) -> Any:
        if self._window_settings is None:
            return default
        return self._window_settings.value(key, default)

    def _window_pref_bool(self, key: str, default: bool) -> bool:
        value = self._window_pref(key, default)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    def _store_window_pref(self, key: str, value: Any) -> None:
        if self._window_settings is not None:
            self._window_settings.setValue(key, value)

    def _forget_window_geometry(self) -> None:
        if self._window_settings is not None:
            self._window_settings.remove("window/geometry")
            self._window_settings.remove("window/maximized")

    def _active_screen(self):
        screen = self.screen() if self.isVisible() else None
        if screen is None:
            screen = QGuiApplication.screenAt(QCursor.pos())
        return screen or QGuiApplication.primaryScreen()

    def _available_geometry(self) -> QRect:
        screen = self._active_screen()
        return screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 720)

    def _work_areas(self) -> list[QRect]:
        return [screen.availableGeometry() for screen in QGuiApplication.screens()]

    def _frame_extra(self) -> QSize:
        """Window decoration size (frame minus client); zero until the native window exists."""
        frame, client = self.frameGeometry(), self.geometry()
        return QSize(max(0, frame.width() - client.width()), max(0, frame.height() - client.height()))

    def apply_window_mode(self, mode: str | None = None) -> None:
        """Resize/center (or maximize) this window only; lifecycle and run data are untouched."""
        mode = mode or self.window_mode
        if mode == "maximized":
            self.showMaximized() if self.isVisible() else self.setWindowState(Qt.WindowState.WindowMaximized)
            return
        if self.isMaximized() or self.isFullScreen():
            self.showNormal()
        available = self._available_geometry()
        extra = self._frame_extra()
        size = window_size_for_mode(mode, self._client_work_area(), self.minimumSize(), self.custom_window_size)
        self.resize(size)
        self.move(centered_top_left(size + extra, available))
        self._schedule_results_layout_sync()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_density()
        self._sync_results_analysis_split()
        self._schedule_results_layout_sync()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._schedule_results_layout_sync()

    def _schedule_results_layout_sync(self) -> None:
        """Re-sync Results layout after Qt has delivered real geometry (page switch, tab, window state)."""
        if getattr(self, "_results_layout_sync_pending", False):
            return
        self._results_layout_sync_pending = True
        # Context-object overload: Qt drops the callback if this window is destroyed first.
        QTimer.singleShot(0, self, self._run_scheduled_results_layout_sync)

    def _run_scheduled_results_layout_sync(self) -> None:
        self._results_layout_sync_pending = False
        self._sync_results_layout()

    def _sync_results_layout(self) -> None:
        """Presentation-only reflow: never rebuilds run data, verdict, or Host Evidence."""
        content = getattr(self, "results_content", None)
        if content is None:
            return
        content_layout = content.parentWidget().layout() if content.parentWidget() is not None else None
        if content_layout is not None:
            content_layout.activate()
        self._sync_results_analysis_split()

    def _results_available_width(self) -> int:
        scroll = getattr(self, "results_scroll", None)
        if scroll is not None and scroll.viewport().width() > 1:
            return min(scroll.viewport().width(), self.MAX_SETUP_CONTENT_WIDTH)
        content = getattr(self, "results_content", None)
        return content.width() if content is not None else self.width()

    def _sync_results_analysis_split(self) -> None:
        split = getattr(self, "results_analysis_split", None)
        if split is None:
            return
        width = self._results_available_width()
        horizontal = width >= self.RESULTS_ANALYSIS_HORIZONTAL_MIN_WIDTH
        orientation = Qt.Orientation.Horizontal if horizontal else Qt.Orientation.Vertical
        changed = split.orientation() != orientation
        if changed:
            split.setOrientation(orientation)
        if not horizontal:
            self._results_split_synced_extent = -1
            return
        extent = split.width()
        if extent <= 1 or (not changed and extent == self._results_split_synced_extent):
            return
        chart = int(extent * self.RESULTS_ANALYSIS_CHART_FRACTION)
        split.setSizes([chart, max(extent - chart, 1)])
        self._results_split_synced_extent = extent

    def _client_work_area(self) -> QSize:
        available, extra = self._available_geometry(), self._frame_extra()
        return QSize(available.width() - extra.width(), available.height() - extra.height())

    def show_startup_window(self) -> None:
        restored = self._restorable_window_geometry()
        if restored is not None:
            rect, maximized = restored
            self.setGeometry(rect)
            self.showMaximized() if maximized else self.show()
            return
        if self.window_mode == "maximized":
            self.showMaximized()
            return
        self.show()
        self.apply_window_mode()

    def _restorable_window_geometry(self) -> tuple[QRect, bool] | None:
        if not self.remember_window_geometry:
            return None
        rect = self._window_pref("window/geometry", None)
        if not isinstance(rect, QRect) or not geometry_is_reachable(rect, self._work_areas()):
            return None
        return rect, self._window_pref_bool("window/maximized", False)

    def _save_window_geometry(self) -> None:
        if not self.remember_window_geometry:
            return
        rect = self.normalGeometry() if self.isMaximized() else self.geometry()
        if not geometry_is_reachable(rect, self._work_areas()):
            return
        self._store_window_pref("window/geometry", rect)
        self._store_window_pref("window/maximized", self.isMaximized())

    def _on_window_mode_changed(self, index: int) -> None:
        mode = self.startup_window_combo.itemData(index)
        if mode not in WINDOW_MODES:
            return
        if mode == "custom":
            # Custom only becomes the active/persisted mode once Apply Custom Size succeeds.
            self._seed_custom_size_fields()
            self._sync_custom_window_panel()
            return
        self.window_mode = mode
        self._store_window_pref("window/startup_mode", mode)
        self._sync_custom_window_panel()
        self._mark_window_mode_index_handled(index)
        self.apply_window_mode()

    def _mark_window_mode_index_handled(self, index: int) -> None:
        # Qt emits currentIndexChanged before activated for one user pick; the marker lets activated
        # skip that pick and is cleared on the next event-loop pass so programmatic changes never linger.
        self._window_mode_handled_index = index
        QTimer.singleShot(0, self, self._clear_window_mode_handled_index)

    def _clear_window_mode_handled_index(self) -> None:
        self._window_mode_handled_index = None

    def _on_window_mode_activated(self, index: int) -> None:
        """Re-picking the entry already shown (e.g. after a remembered geometry restore) emits no
        currentIndexChanged, so the pick is applied here."""
        if getattr(self, "_window_mode_handled_index", None) == index:
            self._window_mode_handled_index = None
            return
        mode = self.startup_window_combo.itemData(index)
        if mode not in WINDOW_MODES or mode == "custom" or mode != self.window_mode:
            return
        self.apply_window_mode()

    def _custom_size_spin(self, minimum: int, maximum: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSuffix(" px")
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        spin.setMinimumWidth(130)
        spin.setMinimumHeight(36)
        return spin

    def _valid_custom_window_size(self, width: Any, height: Any) -> bool:
        if isinstance(width, bool) or isinstance(height, bool):
            return False
        if not isinstance(width, int) or not isinstance(height, int):
            return False
        return (
            self.minimumWidth() <= width <= CUSTOM_WINDOW_MAX_SIZE[0]
            and self.minimumHeight() <= height <= CUSTOM_WINDOW_MAX_SIZE[1]
        )

    def _stored_custom_window_size(self) -> QSize | None:
        try:
            width = int(self._window_pref("window/custom_width", 0))
            height = int(self._window_pref("window/custom_height", 0))
        except (TypeError, ValueError):
            return None
        return QSize(width, height) if self._valid_custom_window_size(width, height) else None

    def _custom_size_seed(self) -> QSize:
        if self.custom_window_size is not None:
            return QSize(self.custom_window_size)
        if self.isMaximized() or self.isFullScreen():
            normal = self.normalGeometry()
            if normal.isValid() and not normal.isEmpty():
                return normal.size()
            return window_size_for_mode("auto", self._client_work_area(), self.minimumSize())
        return self.size()

    def _seed_custom_size_fields(self) -> None:
        seed = self._custom_size_seed()
        self.custom_width_spin.setValue(seed.width())
        self.custom_height_spin.setValue(seed.height())

    def _custom_size_pending(self) -> bool:
        if self.startup_window_combo.currentData() != "custom":
            return False
        entered = QSize(self.custom_width_spin.value(), self.custom_height_spin.value())
        return self.window_mode != "custom" or self.custom_window_size != entered

    def _sync_custom_size_status(self, *_args) -> None:
        pending = self._custom_size_pending()
        self.custom_size_status.setText(self._tr("custom_size_pending") if pending else "")
        self.custom_size_status.setVisible(pending)

    def _sync_custom_window_panel(self) -> None:
        self.custom_window_panel.setVisible(self.startup_window_combo.currentData() == "custom")
        self._sync_custom_size_status()

    def apply_custom_window_size(self, width: int | None = None, height: int | None = None) -> bool:
        """Validate, persist and apply a custom window size; Custom becomes the startup mode only on success."""
        width = self.custom_width_spin.value() if width is None else width
        height = self.custom_height_spin.value() if height is None else height
        if not self._valid_custom_window_size(width, height):
            return False
        self.custom_window_size = QSize(width, height)
        self._store_window_pref("window/custom_width", width)
        self._store_window_pref("window/custom_height", height)
        self.window_mode = "custom"
        self._store_window_pref("window/startup_mode", "custom")
        self.startup_window_combo.blockSignals(True)
        try:
            self.startup_window_combo.setCurrentIndex(WINDOW_MODES.index("custom"))
        finally:
            self.startup_window_combo.blockSignals(False)
        self.custom_width_spin.setValue(width)
        self.custom_height_spin.setValue(height)
        self._sync_custom_window_panel()
        self.apply_window_mode("custom")
        return True

    def _on_remember_window_toggled(self, checked: bool) -> None:
        self.remember_window_geometry = bool(checked)
        self._store_window_pref("window/remember_geometry", self.remember_window_geometry)
        if not self.remember_window_geometry:
            self._forget_window_geometry()

    def reset_window_geometry(self) -> None:
        """Forget remembered geometry and return startup mode, combo and window to Auto in one step."""
        self._forget_window_geometry()
        self.window_mode = "auto"
        self._store_window_pref("window/startup_mode", "auto")
        self.startup_window_combo.blockSignals(True)
        try:
            self.startup_window_combo.setCurrentIndex(WINDOW_MODES.index("auto"))
        finally:
            self.startup_window_combo.blockSignals(False)
        self._sync_custom_window_panel()
        self.apply_window_mode("auto")

    def _refresh_live_texts(self):
        """Re-apply translated runtime strings (charts, review, overlay, verdict)."""
        if self.completed or self.events:
            self._refresh_metrics(final=self.completed)
        elif self.overlay_path:
            self._update_overlay_deltas({})
        self._refresh_results_workspace()
        if self.completed and self.locked is not None and not self.running:
            self.status_label.setText(self._tr("review_hint"))

    def _retranslate_ui(self):
        self.setWindowTitle(self._tr("app_title"))
        self.title_label.setText(self._tr("app_title"))
        self.nav_setup.setText(self._tr("nav_setup"))
        self.nav_capture.setText(self._tr("nav_capture"))
        self.nav_results.setText(self._tr("nav_results"))
        self.nav_preferences.setText(self._tr("nav_preferences"))
        self.lbl_setup.setText(self._tr("setup_device_section").upper())
        self.lbl_setup_config.setText(self._tr("setup_config_section").upper())
        self.lbl_profile_section.setText(self._tr("setup_profile_section").upper())
        self.lbl_locked_profile_section.setText(self._tr("setup_locked_profile_section").upper())
        self.lbl_pref_appearance.setText(self._tr("pref_appearance_section").upper())
        self.lbl_pref_language.setText(self._tr("language").upper())
        self.lbl_controls.setText(self._tr("controls"))
        self.results_placeholder.setText(self._tr("results_empty"))
        self.lbl_results_summary.setText(self._tr("results_run_context").upper())
        self.lbl_results_run_status.setText(self._tr("run_status").upper())
        self.lbl_results_observations.setText(self._tr("results_observations").upper())
        self.lbl_results_evidence.setText(self._tr("results_host_evidence_section").upper())
        self.lbl_results_actions.setText(self._tr("next_run").upper())
        if self._post_run_input_guard_active:
            self.results_input_guard_status.setText(self._tr("waiting_for_mouse_input"))
        self.lbl_results_report.setText(self._tr("report").upper())
        self.lbl_analysis_view.setText(self._tr("analysis_view"))
        self.results_tabs.setTabText(0, self._tr("analysis"))
        self.results_tabs.setTabText(1, self._tr("evidence"))
        self.results_tabs.setTabText(2, self._tr("click_data"))
        self.lbl_click_sort_by.setText(self._tr("click_sort_by"))
        self.lbl_click_sort_order.setText(self._tr("click_sort_order"))
        headers = [
            self._tr("col_index"),
            self._tr("col_elapsed"),
            self._tr("col_button"),
            self._tr("col_interval"),
            self._tr("col_hold"),
            self._tr("col_state"),
            self._tr("col_tags"),
            self._tr("col_ref_delta"),
        ]
        self.results_click_table.setHorizontalHeaderLabels(headers)
        state_header = self.results_click_table.horizontalHeaderItem(5)
        if state_header is not None:
            state_header.setToolTip(self._tr("col_state_tooltip"))
        header_item = self.results_click_table.horizontalHeaderItem(7)
        if header_item is not None:
            header_item.setToolTip(self._tr("col_ref_delta_tooltip"))
        help_text = self._tr("results_chart_legend_help")
        self.results_chart_legend_help.setText(help_text)
        self.results_scatter.setToolTip(help_text)
        self.results_interval_chart.setToolTip(help_text)
        self.results_distribution_chart.setToolTip(help_text)
        self.btn_new.setText(self._tr("run_again"))
        self.btn_edit_setup_new_run.setText(qt_button_label(self._tr("edit_setup_new_run")))
        self.btn_capture_new_run.setText(self._tr("new_run"))
        self.btn_capture_goto_results.setText(self._tr("nav_results"))
        self.btn_capture_edit_setup.setText(qt_button_label(self._tr("edit_setup_new_run")))
        self.capture_completed_note.setText(self._tr("capture_run_completed"))
        self.btn_view_stability.setText(self._tr("viz_stability_map"))
        self.btn_view_interval.setText(self._tr("viz_interval_trend"))
        self.btn_chart_fit.setText(self._tr("viz_fit_data"))
        self.btn_chart_zoom_in.setText(self._tr("viz_zoom_in"))
        self.btn_chart_zoom_out.setText(self._tr("viz_zoom_out"))
        self.btn_chart_reset.setText(self._tr("viz_reset_view"))
        self.scatter.title = self._tr("chart_stability_map")
        self.scatter.subtitle = self._capture_chart_subtitle(self.locked or self.profile_locked_settings)
        self.interval_chart.title = self._tr("chart_interval_trend")
        self.scatter.update()
        self.interval_chart.update()
        self.preferences_note.setText(self._tr("preferences_more_note"))
        self.radio_manual.setText(self._tr("manual"))
        self.radio_fixture.setText(self._tr("fixture"))
        self.lbl_device.setText(self._tr("device"))
        self.device_edit.setPlaceholderText(self._tr("device_placeholder"))
        self.lbl_button.setText(self._tr("button"))
        self.hz_label.setText(self._tr("reference_rate_hz"))
        self._refresh_fixture_mode_label()
        self.timing_tol_label.setText(self._tr("fixture_timing_tolerance_ms"))
        self.timing_tol_edit.setPlaceholderText(self._tr("fixture_timing_tolerance_placeholder"))
        self._refresh_association_context()
        self.auto_stop_label.setText(self._tr("auto_stop"))
        self.auto_stop_off.setText(self._tr("auto_stop_off_button"))
        self.auto_stop_on.setText(self._tr("auto_stop_on_button"))
        self.auto_stop_sec_label.setText(self._tr("auto_stop_after"))
        self.lbl_custom_limits.setText(self._tr("screening").upper())
        self.lbl_screening.setText(self._tr("screening").upper())
        self.lbl_screening_status.setText(self._tr("screening_measurement_only"))
        self.lbl_screening_note.setText(self._tr("screening_measurement_only_note"))
        self.btn_stop.setText(self._tr("stop"))
        self.btn_generate_excel.setText(self._tr("generate_excel"))
        self.btn_generate_html.setText(self._tr("generate_html"))
        self.btn_export.setText(self._tr("export_save_as"))
        self.act_export_txt.setText(self._tr("export_analysis_txt"))
        self.act_export_csv.setText(self._tr("export_click_log_csv"))
        self.act_export_summary_json.setText(self._tr("export_summary_json"))
        self.act_export_detail_json.setText(self._tr("export_detail_json"))
        self.act_save_report_as.setText(self._tr("save_report_as"))
        self.btn_overlay.setText(self._tr("compare"))
        self.btn_clear_overlay.setText(self._tr("clear_overlay"))
        self.btn_lock_profile.setText(qt_button_label(self._tr("lock_profile_continue")))
        self.btn_edit_profile.setText(self._tr("edit_profile"))
        self.btn_help.setText(self._tr("quick_start"))
        self.lbl_theme.setText(self._tr("theme"))
        self.theme_combo.setItemText(0, self._tr("theme_light"))
        self.theme_combo.setItemText(1, self._tr("theme_dark"))
        self.lbl_lang.setText(self._tr("display_language"))
        self.lbl_pref_window.setText(self._tr("pref_window_section").upper())
        self.lbl_startup_window.setText(self._tr("startup_window"))
        for index, mode in enumerate(WINDOW_MODES):
            label = self._tr(f"window_mode_{mode}")
            if mode in WINDOW_PRESET_SIZES:
                width, height = WINDOW_PRESET_SIZES[mode]
                label = f"{width} × {height} — {label}"
            self.startup_window_combo.setItemText(index, label)
        self.window_fit_note.setText(self._tr("window_fit_note"))
        self.lbl_custom_window.setText(self._tr("custom_window_size"))
        self.lbl_custom_width.setText(self._tr("custom_width"))
        self.lbl_custom_height.setText(self._tr("custom_height"))
        self.apply_custom_size_button.setText(self._tr("apply_custom_size"))
        self._sync_custom_size_status()
        self.remember_window_size_checkbox.setText(self._tr("remember_window_size"))
        self.remember_window_size_note.setText(self._tr("remember_window_size_note"))
        self.reset_window_geometry_button.setText(qt_button_label(self._tr("reset_window_geometry")))
        self.issue_title.setText(self._tr("issues"))
        for key, lab in self._stat_name_labels.items():
            token = _CAPTURE_ISSUE_INTERNAL.get(key)
            text = screening_presentation_label(token, self._tr) if token else self._tr(key)
            lab.setText(text.upper())
        self.hint.setText(self._tr("test_area_hint"))
        self._sync_auto_stop_widgets()
        self._fill_click_sort_controls()
        self._apply_measurement_only_chrome()
        self._show_workflow_page(self._current_page)
        self._refresh_lifecycle_presentation()
        self._refresh_results_workspace()

    # ── Settings / mode ─────────────────────────────────────────────
    def _capture_mode_key(self, base: str) -> str:
        return f"{base}_manual" if self._is_manual() else f"{base}_fixture"

    def _ui_is_manual(self) -> bool:
        return self.radio_manual.isChecked()

    def _is_manual(self) -> bool:
        snapshot = self.locked if self.locked is not None else self.profile_locked_settings
        if snapshot is not None:
            return bool(snapshot.get("manual_mode"))
        return self._ui_is_manual()

    def _custom_limit_raw_values(self) -> dict[str, str]:
        """String form of internal compatibility defaults. Setup has no editors."""
        return {key: f"{value:g}" for key, value in qt_custom_limit_defaults().items()}

    def _apply_mode_fields(self):
        manual = self._ui_is_manual()
        self.hz_label.setVisible(not manual)
        self.hz_combo.setVisible(not manual)
        self.hz_interval_label.setVisible(not manual)
        self.timing_tol_label.setVisible(not manual)
        self.timing_tol_edit.setVisible(not manual)
        self.assoc_context_box.setVisible(not manual)
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
        raw = self.hz_combo.currentText()
        interval_text = format_reference_interval_ms(setup_reference_interval_ms(raw))
        self.hz_interval_label.setText(self._tr("reference_interval_derived", ms=interval_text))
        if self._ui_is_manual():
            return
        try:
            hz_text = f"{parse_reference_rate_hz(raw):g}"
        except ValueError:
            hz_text = (raw or "").strip() or "—"
        self.mode_label.setText(self._tr("mode_fixture", hz=hz_text, ms=interval_text))

    def _refresh_association_context(self, _text: str = "") -> None:
        if getattr(self, "_assoc_context_rows", None) is None:
            return
        ctx = schedule_association_context(self.hz_combo.currentText(), self.timing_tol_edit.text())
        overlap = ctx["windows_overlap"]
        values = {
            "assoc_reference_interval": (
                f"{format_reference_interval_ms(ctx['reference_interval_ms'])} ms"
                if ctx["reference_interval_ms"] is not None
                else "—"
            ),
            "assoc_window": format_association_window_ms(ctx["window_ms"]),
            "assoc_relative": format_percent_of_interval(ctx["percent_of_interval"]),
            "assoc_overlap": "—" if overlap is None else self._tr("assoc_yes" if overlap else "assoc_no"),
        }
        for key, (name, value) in self._assoc_context_rows.items():
            name.setText(self._tr(key))
            value.setText(values[key])
        self.assoc_overlap_note.setText(self._tr("assoc_overlap_note"))
        self.assoc_overlap_note.setVisible(bool(overlap))
        self.assoc_derived_note.setText(self._tr("assoc_derived_note"))

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
            if error_key:
                self.lbl_profile_status.setText(self._tr(error_key))
            elif self._editing_next_run:
                self.lbl_profile_status.setText(self._tr("editing_next_run_note"))
            else:
                self.lbl_profile_status.setText(self._tr("profile_status_draft"))
            self.hint.setText(self._tr("test_area_hint_draft"))
        elif state == "ready":
            self.val_phase.setText(self._tr("phase_ready"))
            self.status_label.setText(self._tr(self._capture_mode_key("status_ready")))
            self.lbl_profile_status.setText(self._tr("profile_status_locked"))
            self.hint.setText(self._tr(self._capture_mode_key("test_area_hint_ready")))
        elif state == "armed":
            self.val_phase.setText(self._tr("phase_armed"))
            self.status_label.setText(self._tr(self._capture_mode_key("status_armed")))
            self.lbl_profile_status.setText(self._tr("profile_status_locked"))
            self.hint.setText(self._tr(self._capture_mode_key("test_area_hint_armed")))
        elif state == "running":
            self.val_phase.setText(self._tr("phase_running"))
            self.lbl_profile_status.setText(self._tr("profile_status_locked"))
        elif state == "completed":
            self.val_phase.setText(self._tr("phase_review"))
            self.status_label.setText(self._tr("review_hint"))
            self.lbl_profile_status.setText(self._tr("profile_status_locked"))
        if state == "draft":
            status_state = "error" if self._profile_validation_error_key else "draft"
        else:
            status_state = "locked"
        if self.lbl_profile_status.property("state") != status_state:
            self.lbl_profile_status.setProperty("state", status_state)
            self.lbl_profile_status.style().unpolish(self.lbl_profile_status)
            self.lbl_profile_status.style().polish(self.lbl_profile_status)
        self._refresh_locked_profile_preview()
        if self._ui_is_manual():
            self.mode_label.setText(self._tr("mode_manual"))
        else:
            self._refresh_fixture_mode_label()

    def _refresh_locked_profile_preview(self) -> None:
        rows = locked_profile_preview_rows(self.profile_locked_settings, self.profile_locked_target, self._tr)
        for index, (cell, key_lab, val_lab) in enumerate(self._preview_cells):
            if index < len(rows):
                key_lab.setText(rows[index][0].upper())
                val_lab.setText(rows[index][1])
                cell.show()
            else:
                key_lab.setText("")
                val_lab.setText("")
                cell.hide()
        self.locked_profile_card.setVisible(bool(rows))

    def _completed_run_facts(self) -> dict[str, Any] | None:
        """Presentation facts from frozen run-owned data only. Does not rebuild Host Evidence."""
        if not self.completed or self.locked is None:
            return None
        model = build_completed_result_model(
            locked=self.locked,
            events=list(self.events),
            run_id=self.run_id,
            target=self.target,
            operator=self.operator,
            start_time=self.start_time,
            stop_time=self.stop_time,
            host_evidence_snapshot=self.host_evidence_snapshot,
        )
        if model is None:
            return None
        run = model["run"]
        assessment = model["assessment"]
        return {
            "settings": run["settings"],
            "metrics": assessment["metrics"],
            "tags": assessment["tags"],
            "run_status": run["run_status"],
            "elapsed_s": run["elapsed_s"],
            "manual": run["manual"],
            "model": model,
        }

    def _format_run_context(self, model: dict[str, Any]) -> str:
        run = model["run"]
        settings = run.get("settings") or {}
        parts = [
            (run["target"] or "").strip() or "—",
            run["button"],
        ]
        profile = str(settings.get("profile_name") or "").strip()
        if profile:
            parts.append(f"{self._tr('run_profile')}: {profile}")
        parts.append(f"{self._tr('screening')}: {self._tr('screening_measurement_only')}")
        if run["manual"]:
            parts.append(self._tr("manual"))
        else:
            hz = run["reference_hz"]
            parts.append(f"{self._tr('fixture')} {hz:g} Hz" if hz is not None else self._tr("fixture"))
            tol = run["timing_tolerance_ms"]
            if tol is not None:
                parts.append(f"{self._tr('tolerance')} {format_association_window_ms(tol)}")
        elapsed = run["elapsed_s"]
        if isinstance(elapsed, (int, float)):
            parts.append(f"{elapsed:.1f} s")
        parts.append(f"{run['host_press_count']} {self._tr('results_host_clicks')}")
        return " · ".join(parts)

    def _format_observation_text(self, model: dict[str, Any]) -> str:
        findings = model["observations"]
        if not findings:
            return self._tr("observations_none")
        blocks: list[str] = [self._tr("informational_observation")]
        for finding in findings:
            lines = [self._tr(finding["title_key"])]
            for row in finding.get("rows") or []:
                value = row["value"]
                unit = row.get("unit") or ""
                if isinstance(value, float):
                    rendered = f"{value:.2f}"
                else:
                    rendered = str(value)
                if unit:
                    rendered = f"{rendered} {unit}"
                lines.append(f"{self._tr(row['label_key'])}    {rendered}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def _legacy_observation_lines(self, facts: dict[str, Any]) -> list[str]:
        model = facts.get("model")
        if model:
            return self._format_observation_text(model).splitlines()
        return []

    def _results_summary_rows(self, facts: dict[str, Any]) -> list[tuple[str, str]]:
        model = facts.get("model")
        if not model:
            return []
        return [("", self._format_run_context(model))]

    def _refresh_results_workspace(self) -> None:
        facts = self._completed_run_facts()
        has_run = facts is not None
        self.results_empty_card.setVisible(not has_run)
        self.results_workspace.setVisible(has_run)
        self.results_placeholder.setText(self._tr("results_empty"))
        if not has_run:
            self.results_observations_text.setText("")
            self.results_evidence_text.clear()
            self.results_verdict_label.setText("--")
            self.results_tags_label.setText("")
            self.results_overlay_status.setText("")
            self.results_context_label.setText("")
            self.results_evidence_na.show()
            self.results_evidence_body.hide()
            self.results_click_table.setRowCount(0)
            return
        model = facts["model"]
        self.val_clicks.setText(str(int(model["run"]["host_press_count"])))
        self.results_context_label.setText(self._format_run_context(model))
        visible_tags = model["assessment"]["tags"]
        self.results_verdict_label.setText(self._run_status_display(model["run"]["run_status"]))
        visible_aliases = screening_presentation_labels(visible_tags, self._tr)
        self.results_tags_label.setText(
            ", ".join(visible_aliases) if visible_aliases else self._tr("review_tags_none")
        )
        self.results_observations_text.setText(self._format_observation_text(model))
        self._populate_evidence_tab(model)
        self._populate_click_table(model)
        self._fill_analysis_views(model)
        self._refresh_results_charts(model)
        if self.overlay_path:
            self.results_overlay_status.setText(self.overlay_delta_label.text())
        else:
            self.results_overlay_status.setText("")

    def _populate_evidence_tab(self, model: dict[str, Any]) -> None:
        snapshot = model["host_evidence"]["snapshot"]
        self.lbl_results_evidence.setText(self._tr("results_host_evidence_section").upper())
        if snapshot is None:
            self.results_evidence_body.hide()
            self.results_occupancy_bar.hide()
            self.results_evidence_note.hide()
            self.results_evidence_na.show()
            if model["run"]["manual"]:
                self.results_evidence_na.setText(self._tr("not_applicable_manual"))
            else:
                self.results_evidence_na.setText(self._tr("not_applicable_no_duration"))
            self.results_evidence_text.setPlainText(self.results_evidence_na.text())
            return
        self.results_evidence_na.hide()
        self.results_evidence_body.show()
        self.results_evidence_note.show()
        self.results_occupancy_bar.show()
        config = snapshot["configuration"]
        counts = snapshot["counts"]
        matching = snapshot["matching"]
        delta = snapshot["timing"]["matched_delta_stats"]
        abs_delta = snapshot["timing"]["matched_absolute_delta_stats"]
        matched_n = int(matching["matched_host_observation_count"] or 0)
        in_capture_n = int(counts["in_window_host_press_count"] or 0)
        timing_rows: list[tuple[str, str]] = [
            (self._tr("timing_group").upper(), ""),
            (
                self._tr("matched_observations_used"),
                self._tr("matched_observations_used_value", matched=matched_n, total=in_capture_n),
            ),
        ]
        if matched_n == 0:
            timing_rows.append((self._tr("matched_timing_empty"), ""))
        else:
            timing_rows.extend(
                [
                    (self._tr("average_error"), f"{_fmt_signed_ms(delta['average'])} ms"),
                    (self._tr("average_abs_error"), f"{_fmt_unsigned_ms(abs_delta['average'])} ms"),
                    (self._tr("min_error"), f"{_fmt_signed_ms(delta['minimum'])} ms"),
                    (self._tr("max_error"), f"{_fmt_signed_ms(delta['maximum'])} ms"),
                    (self._tr("stdev"), f"{_fmt_unsigned_ms(delta['stdev'])} ms"),
                ]
            )
            if matched_n == 1:
                timing_rows.append((self._tr("matched_timing_single"), ""))
        rows = [
            (self._tr("schedule").upper(), ""),
            (self._tr("expected_windows"), str(counts["expected_slot_count"])),
            (self._tr("reference_interval"), f"{float(config['reference_interval_ms']):.2f} ms"),
            (self._tr("tolerance"), f"±{float(config['timing_tolerance_ms']):.3f} ms"),
            (self._tr("host_observations").upper(), ""),
            (self._tr("in_capture"), str(counts["in_window_host_press_count"])),
            (self._tr("raw_observations"), str(counts["raw_host_press_count"])),
            (self._tr("delta_vs_windows"), _fmt_signed_count(int(counts["host_count_delta_vs_expected_slots"]))),
            (self._tr("occupancy").upper(), ""),
            (self._tr("unoccupied"), str(matching["empty_expected_slot_count"])),
            (self._tr("single_occupancy"), str(matching["single_occupancy_slot_count"])),
            (self._tr("multi_occupancy"), str(matching["multi_occupancy_slot_count"])),
            (self._tr("association").upper(), ""),
            (self._tr("matched"), str(matching["matched_host_observation_count"])),
            (self._tr("unmatched"), str(matching["unmatched_host_observation_count"])),
            (self._tr("ambiguous"), str(matching["ambiguous_host_observation_count"])),
            (self._tr("outside_capture"), str(matching["outside_capture_window_observation_count"])),
            *timing_rows,
        ]
        self.results_occupancy_bar.set_counts(
            int(matching["empty_expected_slot_count"]),
            int(matching["single_occupancy_slot_count"]),
            int(matching["multi_occupancy_slot_count"]),
        )
        for index, (key_lab, val_lab) in enumerate(self._results_evidence_cells):
            if index < len(rows):
                key_lab.setText(rows[index][0])
                val_lab.setText(rows[index][1])
                key_lab.show()
                val_lab.show()
            else:
                key_lab.setText("")
                val_lab.setText("")
                key_lab.hide()
                val_lab.hide()
        self.results_evidence_note.setText(self._tr("neutral_host_evidence_note"))
        lines = format_host_evidence_review_lines(snapshot, self._tr)
        lines.append(self._tr("neutral_host_evidence_note"))
        self.results_evidence_text.setPlainText("\n".join(lines))

    def _populate_click_table(self, model: dict[str, Any]) -> None:
        rows = model["click_data"]
        table = self.results_click_table
        table.setRowCount(len(rows))
        neutral = measurement_only_timing_observation_label()
        for r, row in enumerate(rows):
            index_val = row.get("index")
            try:
                index_sort: int | None = int(index_val) if index_val not in (None, "") else None
            except (TypeError, ValueError):
                index_sort = None
            cells = (
                (str(index_val or ""), index_sort),
                ("" if row.get("elapsed_ms") is None else f"{row['elapsed_ms']:.2f}", row.get("elapsed_ms")),
                (str(row.get("button") or ""), str(row.get("button") or "")),
                ("" if row.get("interval_ms") is None else f"{row['interval_ms']:.2f}", row.get("interval_ms")),
                ("" if row.get("hold_ms") is None else f"{row['hold_ms']:.2f}", row.get("hold_ms")),
                (neutral, neutral),
                (neutral, neutral),
                (
                    "" if row.get("reference_delta_ms") is None else f"{row['reference_delta_ms']:.2f}",
                    row.get("reference_delta_ms"),
                ),
            )
            for c, (display, sort_value) in enumerate(cells):
                item = QTableWidgetItem(display)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setData(Qt.ItemDataRole.UserRole, sort_value)
                item.setData(Qt.ItemDataRole.UserRole + 1, r)
                table.setItem(r, c, item)
        self._apply_click_table_column_visibility()
        self._set_click_sort("index", False)

    def _click_table_visible_ids(self) -> tuple[str, ...]:
        if self._measurement_only_presentation():
            return CLICK_TABLE_MEASUREMENT_VISIBLE_IDS
        return CLICK_TABLE_COLUMN_IDS

    def _apply_click_table_column_visibility(self) -> None:
        table = getattr(self, "results_click_table", None)
        if table is None:
            return
        header = table.horizontalHeader()
        visible = set(self._click_table_visible_ids())
        for index, column_id in enumerate(CLICK_TABLE_COLUMN_IDS):
            hidden = column_id not in visible
            header.setSectionHidden(index, hidden)
            if hidden:
                header.resizeSection(index, 0)
        if self._click_sort_id not in visible:
            self._click_sort_id = "index"
            self._click_sort_descending = False

    def _fill_click_sort_controls(self) -> None:
        if getattr(self, "click_sort_column_combo", None) is None:
            return
        visible_ids = self._click_table_visible_ids()
        column_combo = self.click_sort_column_combo
        order_combo = self.click_sort_order_combo
        column_combo.blockSignals(True)
        order_combo.blockSignals(True)
        try:
            column_combo.clear()
            for column_id in visible_ids:
                column_combo.addItem(self._tr(CLICK_TABLE_LABEL_KEYS[column_id]), column_id)
            index = column_combo.findData(self._click_sort_id)
            column_combo.setCurrentIndex(index if index >= 0 else 0)
            order_combo.clear()
            order_combo.addItem(self._tr("click_sort_ascending"), "asc")
            order_combo.addItem(self._tr("click_sort_descending"), "desc")
            order_combo.setCurrentIndex(1 if self._click_sort_descending else 0)
        finally:
            column_combo.blockSignals(False)
            order_combo.blockSignals(False)

    def _sync_click_sort_controls(self) -> None:
        self._fill_click_sort_controls()
        header = self.results_click_table.horizontalHeader()
        logical = CLICK_TABLE_ID_TO_INDEX[self._click_sort_id]
        order = Qt.SortOrder.DescendingOrder if self._click_sort_descending else Qt.SortOrder.AscendingOrder
        header.blockSignals(True)
        header.setSortIndicator(logical, order)
        header.blockSignals(False)

    def _set_click_sort(self, column_id: str, descending: bool) -> None:
        visible = self._click_table_visible_ids()
        if column_id not in visible:
            column_id = "index"
            descending = False
        self._click_sort_id = column_id
        self._click_sort_descending = bool(descending)
        self._sync_click_sort_controls()
        self._apply_click_table_sort()

    def _on_click_sort_column_changed(self, _index: int = 0) -> None:
        column_id = self.click_sort_column_combo.currentData()
        if not column_id or column_id == self._click_sort_id:
            return
        self._set_click_sort(str(column_id), False)

    def _on_click_sort_order_changed(self, _index: int = 0) -> None:
        descending = self.click_sort_order_combo.currentData() == "desc"
        if descending == self._click_sort_descending:
            return
        self._set_click_sort(self._click_sort_id, descending)

    def _on_click_sort_indicator_changed(self, section: int, order: Qt.SortOrder) -> None:
        column_id = CLICK_TABLE_INDEX_TO_ID.get(section)
        if column_id is None or column_id not in self._click_table_visible_ids():
            return
        descending = order == Qt.SortOrder.DescendingOrder
        if column_id == self._click_sort_id and descending == self._click_sort_descending:
            return
        self._click_sort_id = column_id
        self._click_sort_descending = descending
        self._fill_click_sort_controls()
        self._apply_click_table_sort()

    def _on_click_header_clicked(self, section: int) -> None:
        column_id = CLICK_TABLE_INDEX_TO_ID.get(section)
        if column_id is None or column_id not in self._click_table_visible_ids():
            return
        if column_id == self._click_sort_id:
            descending = not self._click_sort_descending
        else:
            descending = False
        self._set_click_sort(column_id, descending)

    def _apply_click_table_sort(self) -> None:
        table = self.results_click_table
        column = CLICK_TABLE_ID_TO_INDEX.get(self._click_sort_id, 0)
        descending = self._click_sort_descending
        n = table.rowCount()
        m = table.columnCount()
        if n <= 1 or column < 0:
            return
        grid = [[table.takeItem(r, c) for c in range(m)] for r in range(n)]
        values = []
        ties = []
        for row_items in grid:
            item = row_items[column] if column < len(row_items) else None
            values.append(None if item is None else item.data(Qt.ItemDataRole.UserRole))
            ties.append(0 if item is None else int(item.data(Qt.ItemDataRole.UserRole + 1) or 0))
        order = sort_permutation(
            values,
            descending=descending,
            numeric=column in CLICK_TABLE_NUMERIC_COLUMNS,
            tie_breakers=ties,
        )
        table.blockSignals(True)
        try:
            for new_r, old_r in enumerate(order):
                for c, item in enumerate(grid[old_r]):
                    table.setItem(new_r, c, item)
        finally:
            table.blockSignals(False)

    def _on_click_table_selection_changed(self):
        return

    def _fill_analysis_views(self, model: dict[str, Any]) -> None:
        combo = self.results_view_combo
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(self._tr("interval_over_time"), "interval")
        combo.addItem(self._tr("interval_distribution"), "distribution")
        combo.addItem(self._tr("hold_vs_interval"), "scatter")
        if not model["run"]["manual"] and model["host_evidence"]["snapshot"] is not None:
            combo.addItem(self._tr("timing_error"), "timing")
        index = max(0, combo.findData(current) if current else 0)
        combo.setCurrentIndex(index)
        combo.blockSignals(False)
        self._on_analysis_view_changed()

    def _on_analysis_view_changed(self, _index: int = 0):
        key = self.results_view_combo.currentData()
        mapping = {"interval": 0, "distribution": 1, "scatter": 2, "timing": 3}
        self.results_chart_stack.setCurrentIndex(mapping.get(key, 0))
        facts = self._completed_run_facts()
        if facts:
            self._refresh_results_charts(facts["model"])

    def _refresh_results_charts(self, model: dict[str, Any]) -> None:
        analysis = model["analysis"]
        beat = analysis["reference_interval_ms"]
        labels = self._chart_labels()
        overlay_ann = annotate_events(list(self.overlay_events), model["run"]["settings"]) if self.overlay_events else []
        ov_pts, ov_series = self._chart_points(overlay_ann)
        ov_intervals = [pt[1] for pt in ov_series]
        current_hist, overlay_hist = paired_interval_histograms(analysis["intervals"], ov_intervals)
        pal = get_palette(self.theme)
        for chart in (self.results_interval_chart, self.results_distribution_chart, self.results_scatter):
            chart.set_theme(pal, labels)
        self.results_occupancy_bar.set_theme(pal)
        self.results_interval_chart.set_series(
            analysis["interval_series"],
            title=self._tr("interval_over_time"),
            overlay=ov_series,
            target_beat_ms=beat,
        )
        self.results_distribution_chart.set_bins(
            current_hist,
            title=self._tr("interval_distribution"),
            overlay=overlay_hist,
            target_beat_ms=beat,
        )
        self.results_scatter.set_points(
            analysis["scatter_points"],
            title=self._tr("hold_vs_interval"),
            overlay=ov_pts,
            target_beat_ms=beat,
        )
        snapshot = model["host_evidence"]["snapshot"]
        self.results_timing_title.setText(self._tr("timing_error").upper())
        if snapshot is None:
            text = self._tr("not_applicable_manual") if model["run"]["manual"] else self._tr("not_applicable_no_duration")
        else:
            matching = snapshot["matching"]
            counts = snapshot["counts"]
            matched_n = int(matching["matched_host_observation_count"] or 0)
            in_capture_n = int(counts["in_window_host_press_count"] or 0)
            used = (
                f"{self._tr('matched_observations_used')}: "
                f"{self._tr('matched_observations_used_value', matched=matched_n, total=in_capture_n)}"
            )
            if matched_n == 0:
                text = f"{self._tr('timing_error_unavailable')}\n\n{used}\n{self._tr('matched_timing_empty')}"
            else:
                delta = snapshot["timing"]["matched_delta_stats"]
                abs_delta = snapshot["timing"]["matched_absolute_delta_stats"]
                lines = [
                    self._tr("timing_error_unavailable"),
                    "",
                    used,
                    f"{self._tr('average_error')}: {_fmt_signed_ms(delta['average'])} ms",
                    f"{self._tr('average_abs_error')}: {_fmt_unsigned_ms(abs_delta['average'])} ms",
                    f"{self._tr('min_error')}: {_fmt_signed_ms(delta['minimum'])} ms",
                    f"{self._tr('max_error')}: {_fmt_signed_ms(delta['maximum'])} ms",
                    f"{self._tr('stdev')}: {_fmt_unsigned_ms(delta['stdev'])} ms",
                ]
                if matched_n == 1:
                    lines.append(self._tr("matched_timing_single"))
                text = "\n".join(lines)
        self.results_timing_text.setText(text)

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
        self._editing_next_run = False
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
        # Compatibility stamp only: testers no longer edit these heuristics in Setup.
        limits = qt_custom_limit_defaults()
        base = {
            "manual_mode": manual,
            "profile_name": "Manual_Left_Stable" if manual else "Fixture_Custom",
            "focus_button": focus_button_token(self.button_combo),
            "button": focus_button_token(self.button_combo),
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
        """Run status (never a legacy heuristic PASS/WARN/FAIL) and click count for list labels."""
        metrics = dict(payload.get("metrics") or {})
        ev = events or payload.get("events") or payload.get("all_click_events") or []
        status = str(payload.get("run_status") or "").strip()
        if status not in RUN_STATUSES:
            if ev and any("accepted" in e for e in ev):
                count = accepted_host_press_count(ev)
            else:
                count = metrics.get("click_count") if metrics.get("click_count") is not None else len(ev)
            tags = payload.get("issue_tags") or metrics.get("issue_tags") or []
            status = run_status_for_count(count, tags)
        clicks = str(metrics.get("click_count") if metrics.get("click_count") is not None else len(ev) or "?")
        return status, clicks

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
            "target": target,
            "result": result,
            "mtime": detail_path.stat().st_mtime,
        }

    def _session_run_meta(self, run: dict[str, Any]) -> dict[str, Any]:
        rid = str(run.get("run_id") or "")
        events = list(run.get("events") or [])
        settings = dict(run.get("settings") or {})
        metrics = dict(run.get("metrics") or {})
        target = str(run.get("target") or "")
        result = str(run.get("result") or "").strip()
        if result not in RUN_STATUSES and settings:
            annotated = annotate_events(events, settings)
            payload = build_payload(target, "", settings, annotated, run_id=rid)
            metrics = dict(payload.get("metrics") or metrics)
            tags = _metrics_issue_tags(metrics, settings, annotated)
            result = completed_run_status(events, tags)
        clicks = str(metrics.get("click_count") if metrics.get("click_count") is not None else len(events) or "?")
        label = str(run.get("label") or "") or self._overlay_list_label(rid, result, clicks, target)
        return {
            "run_id": rid,
            "label": label,
            "events": events,
            "metrics": metrics,
            "settings": settings,
            "target": target,
            "result": result,
            "mtime": float(run.get("mtime") or 0),
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
                merged = dict(by_id[rid])
                if session_meta.get("events"):
                    merged["events"] = list(session_meta["events"])
                    merged["metrics"] = session_meta.get("metrics") or {}
                    merged["settings"] = session_meta.get("settings") or merged.get("settings")
                if session_meta.get("target"):
                    merged["target"] = session_meta["target"]
                if session_meta.get("result"):
                    merged["result"] = session_meta["result"]
                if session_meta.get("label"):
                    merged["label"] = session_meta["label"]
                if session_meta.get("mtime") is not None:
                    merged["mtime"] = float(session_meta["mtime"])
                by_id[rid] = merged
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
        self._refresh_results_workspace()
        self._sync_overlay_controls()

    def clear_overlay(self):
        self.overlay_events = []
        self.overlay_metrics = {}
        self.overlay_path = ""
        self._refresh_metrics(final=self.completed)
        self._refresh_results_workspace()
        self._sync_overlay_controls()

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
                pts.append((
                    float(iv),
                    float(hold),
                    str(e.get("click_class") or "ON_CADENCE"),
                    e.get("click_index") or e.get("index"),
                ))
            if iv is not None and elapsed is not None:
                series.append((float(elapsed), float(iv)))
        return pts, series

    def _on_capture_view_id(self, index: int) -> None:
        self._set_capture_view("stability" if index == 0 else "interval")

    def _set_capture_view(self, name: str) -> None:
        if name not in ("stability", "interval"):
            name = "stability"
        self._capture_view = name
        if getattr(self, "capture_chart_stack", None) is not None:
            self.capture_chart_stack.setCurrentIndex(0 if name == "stability" else 1)
        if getattr(self, "btn_view_stability", None) is None:
            return
        self.btn_view_stability.blockSignals(True)
        self.btn_view_interval.blockSignals(True)
        self.btn_view_stability.setChecked(name == "stability")
        self.btn_view_interval.setChecked(name == "interval")
        self.btn_view_stability.blockSignals(False)
        self.btn_view_interval.blockSignals(False)

    def _active_capture_chart(self):
        if getattr(self, "_capture_view", "stability") == "interval":
            return self.interval_chart
        return self.scatter

    def _on_capture_fit_data(self) -> None:
        self._active_capture_chart().fit_data()

    def _on_capture_zoom_in(self) -> None:
        self._active_capture_chart().zoom_in()

    def _on_capture_zoom_out(self) -> None:
        self._active_capture_chart().zoom_out()

    def _on_capture_reset_view(self) -> None:
        self._active_capture_chart().reset_view()

    def _reset_capture_visualization(self) -> None:
        if getattr(self, "scatter", None) is not None:
            self.scatter.clear_navigation()
        if getattr(self, "interval_chart", None) is not None:
            self.interval_chart.clear_navigation()
        self._set_capture_view("stability")
        self._sync_capture_chart_pan()

    def _sync_capture_chart_pan(self) -> None:
        enabled = (
            self._lifecycle_state() == "completed"
            and not self._post_run_input_guard_active
        )
        if getattr(self, "scatter", None) is not None:
            self.scatter.set_pan_enabled(enabled)
        if getattr(self, "interval_chart", None) is not None:
            self.interval_chart.set_pan_enabled(enabled)

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
        self.capture_completed_note.hide()
        self.alert_label.setText("")

    def enter_listen(self):
        if getattr(self, "_listen_start_timer", None) is not None:
            self._listen_start_timer.stop()
        self._cancel_post_run_input_guard()
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
            self._locked_button = focus_button_token(self.button_combo)
        try:
            self.ensure_raw_input()
        except Exception as exc:
            self.alert_label.setText(self._tr("raw_input_failed", error=exc))

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

    def _upsert_session_run_for_compare(self) -> None:
        if not (self.events and self.completed):
            return
        rid = str(self.run_id or "")
        if not rid:
            return
        settings = copy.deepcopy(self.locked) if self.locked is not None else copy.deepcopy(self.settings())
        events = copy.deepcopy(list(self.events))
        target = str(self.target or "")
        model = build_completed_result_model(
            locked=settings,
            events=events,
            run_id=rid,
            target=target,
            operator=self.operator,
            start_time=self.start_time,
            stop_time=self.stop_time,
            host_evidence_snapshot=self.host_evidence_snapshot,
        )
        metrics = copy.deepcopy((model or {}).get("assessment", {}).get("metrics") or {})
        result = str((model or {}).get("run", {}).get("run_status") or completed_run_status(events))
        clicks = str((model or {}).get("run", {}).get("host_press_count") or len(events) or 0)
        entry = {
            "run_id": rid,
            "target": target,
            "label": self._overlay_list_label(rid, result, clicks, target),
            "events": events,
            "metrics": metrics,
            "settings": settings or {},
            "result": result,
        }
        for existing in self.session_runs:
            if str(existing.get("run_id") or "") == rid:
                mtime = existing.get("mtime")
                existing.clear()
                existing.update(entry)
                existing["mtime"] = mtime if mtime is not None else time.time()
                return
        entry["mtime"] = time.time()
        self.session_runs.append(entry)

    def _archive_completed_run_for_compare(self) -> None:
        self._upsert_session_run_for_compare()

    def new_run(self):
        if self.running:
            return
        self._archive_completed_run_for_compare()
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
        self._reset_capture_visualization()
        self._editing_next_run = False
        self.results_next_run_note.hide()
        self.enter_listen()
        self._refresh_results_workspace()
        self._show_workflow_page("capture")

    def edit_setup_new_run(self) -> bool:
        if self.running:
            return False
        previous = copy.deepcopy(self.locked) if self.locked is not None else copy.deepcopy(self.profile_locked_settings)
        previous_target = self.target
        self._archive_completed_run_for_compare()
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
        self._reset_capture_visualization()
        self.profile_locked_settings = None
        self.profile_locked_target = ""
        self._profile_validation_error_key = None
        if previous:
            self._apply_settings_to_setup_widgets(previous, previous_target)
        self._editing_next_run = True
        self.enter_listen()
        self._refresh_results_workspace()
        self._show_workflow_page("setup")
        self.results_next_run_note.setText(self._tr("editing_next_run_note"))
        self._update_controls()
        return True

    def _apply_settings_to_setup_widgets(self, settings: dict[str, Any], target: str) -> None:
        self.device_edit.setText((target or "").strip())
        select_focus_button(
            self.button_combo,
            str(settings.get("focus_button") or settings.get("button") or DEFAULT_FOCUS_BUTTON),
        )
        if bool(settings.get("manual_mode")):
            self.radio_manual.setChecked(True)
        else:
            self.radio_fixture.setChecked(True)
            hz = settings.get("fixture_reference_hz") or settings.get("fixture_hz")
            if hz:
                text = f"{float(hz):g}"
                found = self.hz_combo.findText(text)
                if found >= 0:
                    self.hz_combo.setCurrentIndex(found)
                else:
                    self.hz_combo.setCurrentText(text)
            tol = settings.get(FIXTURE_TIMING_TOLERANCE_KEY)
            if tol is not None:
                self.timing_tol_edit.setText(f"{float(tol):g}")
            duration = settings.get("duration_sec")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration > 0:
                self.auto_stop_on.setChecked(True)
                self.auto_stop_sec_combo.setCurrentText(f"{float(duration):g}")
            else:
                self.auto_stop_off.setChecked(True)
        self._apply_mode_fields()

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
        self.val_clicks.setText(str(accepted_host_press_count(self.events)))
        self._build_host_evidence_snapshot_for_completed_run()
        self.val_phase.setText(self._tr("phase_review"))
        self.hint.hide()
        self._set_review_panel_visible(False)
        self.capture_completed_note.setText(self._tr("capture_run_completed"))
        self.capture_completed_note.show()
        self.review_text.clear()
        self._refresh_metrics(final=True)
        self.status_label.setText(self._tr("review_hint"))
        self._update_controls()
        self._activate_post_run_input_guard()
        self._show_workflow_page("results")

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

    def generate_excel_report(self):
        """Primary Results action: full report bundle, success target is the engineering XLSX."""
        self.finish_report(preferred_artifact="engineering_xlsx")

    def generate_html_report(self):
        """Primary Results action: full report bundle, success target is the engineering HTML."""
        self.finish_report(preferred_artifact="engineering_html")

    def finish_report(self, preferred_artifact: str | None = None, notify: bool = True):
        """Write the full report bundle from the completed snapshot.

        ``preferred_artifact`` must exist for the call to count as success.
        ``notify=False`` suppresses only the success dialog; failures are always shown.
        """
        if self.running:
            self.stop_run()
        if not self.events:
            QMessageBox.information(self, self._tr("report"), self._tr("no_run"))
            return
        self.completed = True
        settings = self.locked or self.settings()
        facts = self._completed_run_facts()
        try:
            self.report_paths = write_reports(
                self.report_root,
                self.target,
                self.operator,
                settings,
                self.events,
                self.run_id,
                raw_events=list(self.raw_events),
                completed_model=facts["model"] if facts else None,
            )
            verification = _verify_artifacts(self.report_paths)
            if not verification.get("ok"):
                raise RuntimeError("Missing: " + ", ".join(verification.get("missing") or []))
            target_path: Path | str = self.report_root
            if preferred_artifact:
                preferred = str((self.report_paths or {}).get(preferred_artifact) or "")
                if not preferred or not Path(preferred).exists():
                    raise RuntimeError("Missing: " + (Path(preferred).name if preferred else preferred_artifact))
                target_path = preferred
            self.report_written = True
            self._upsert_session_run_for_compare()
            self.status_label.setText(self._tr("report_ready"))
            self._update_controls()
            if notify:
                QMessageBox.information(self, self._tr("report"), self._tr("saved_to", path=target_path))
        except Exception as exc:
            QMessageBox.critical(self, self._tr("report_failed"), str(exc))

    def export_report_artifact(self, key: str):
        """Copy one bundle file through a native Save As dialog, preparing the bundle silently if needed."""
        if not self.report_written:
            self.finish_report(notify=False)
            if not self.report_written:
                return
        src = Path(str((self.report_paths or {}).get(key) or ""))
        if not src.exists():
            QMessageBox.critical(self, self._tr("report_failed"), self._tr("report_missing_detail", detail=src.name or key))
            return
        filters = {
            "txt": "Text (*.txt);;All (*.*)",
            "all_click_log_csv": "CSV (*.csv);;All (*.*)",
            "summary_json": "JSON (*.json);;All (*.*)",
            "detail_json": "JSON (*.json);;All (*.*)",
        }
        dest, _ = QFileDialog.getSaveFileName(
            self,
            self._tr("export_save_as"),
            str(src),
            filters.get(key) or "All (*.*)",
        )
        if not dest:
            return
        try:
            shutil.copy2(src, dest)
        except Exception as exc:
            QMessageBox.critical(self, self._tr("report_failed"), str(exc))
            return
        self.status_label.setText(self._tr("saved_to", path=dest))

    def save_report_as(self):
        if not self.report_written:
            self.finish_report(notify=False)
            if not self.report_written:
                return
        dest = QFileDialog.getExistingDirectory(self, self._tr("save_report_as"))
        if not dest:
            return
        out = Path(dest) / f"mcsa_{self.run_id}"
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        try:
            for path in (self.report_paths or {}).values():
                if path and Path(path).exists():
                    shutil.copy2(path, out / Path(path).name)
                    n += 1
        except Exception as exc:
            QMessageBox.critical(self, self._tr("report_failed"), str(exc))
            return
        self.status_label.setText(self._tr("saved_files", n=n, path=out))

    def show_guide(self):
        self._ignore_arm_until = time.perf_counter() + 1.5
        QMessageBox.information(self, self._tr("guide_title"), self._tr("guide_body"))
        self._ignore_arm_until = time.perf_counter() + 0.8

    def _goto_results_from_capture(self) -> None:
        if not self.completed or self.running:
            return
        self._show_workflow_page("results")

    def _update_controls(self):
        state = self._lifecycle_state()
        completed = state == "completed"
        self.capture_action_bar.setVisible(not completed)
        self.capture_completed_bar.setVisible(completed)
        self.btn_stop.setEnabled(self.running)
        self.btn_new.setEnabled(not self.running)
        self.btn_edit_setup_new_run.setEnabled(self.completed and not self.running)
        self.btn_generate_excel.setEnabled(self.completed and not self.running)
        self.btn_generate_html.setEnabled(self.completed and not self.running)
        self.btn_export.setEnabled(self.completed and not self.running)
        self.btn_lock_profile.setEnabled(state == "draft")
        self.btn_arm.setEnabled(state in ("ready", "armed"))
        self.btn_arm.setText(self._tr("disarm_capture") if state == "armed" else self._tr("arm_capture"))
        self.btn_edit_profile.setEnabled(state in ("ready", "armed"))
        capture_completed_ok = completed and not self.running
        self.btn_capture_new_run.setEnabled(capture_completed_ok)
        self.btn_capture_goto_results.setEnabled(capture_completed_ok)
        self.btn_capture_edit_setup.setEnabled(capture_completed_ok)
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
        self._sync_capture_chart_pan()
        if self._post_run_input_guard_active:
            self._apply_post_run_input_guard_disable()
        else:
            self._sync_overlay_controls()

    def _post_run_protected_widgets(self) -> list:
        return [
            self.btn_new,
            self.btn_edit_setup_new_run,
            self.btn_capture_new_run,
            self.btn_capture_goto_results,
            self.btn_capture_edit_setup,
            self.btn_overlay,
            self.btn_clear_overlay,
            self.btn_generate_excel,
            self.btn_generate_html,
            self.btn_export,
            self.nav_setup,
            self.nav_capture,
            self.nav_preferences,
            self.btn_help,
        ]

    def _overlay_is_loaded(self) -> bool:
        return bool(self.overlay_events) or bool(str(self.overlay_path or "").strip())

    def _sync_overlay_controls(self) -> None:
        """Restore Compare / Clear Overlay to normal lifecycle enablement."""
        if self._post_run_input_guard_active:
            self.btn_overlay.setEnabled(False)
            self.btn_clear_overlay.setEnabled(False)
            return
        self.btn_overlay.setEnabled(True)
        self.btn_clear_overlay.setEnabled(self._overlay_is_loaded())

    def _set_post_run_input_guard_status_visible(self, visible: bool) -> None:
        if visible:
            self.results_input_guard_status.setText(self._tr("waiting_for_mouse_input"))
            self.results_input_guard_status.show()
        else:
            self.results_input_guard_status.hide()
            self.results_input_guard_status.setText("")

    def _apply_post_run_input_guard_disable(self) -> None:
        for widget in self._post_run_protected_widgets():
            widget.setEnabled(False)

    def _post_run_quiet_ms(self) -> int:
        return post_run_quiet_ms(self.locked)

    def _activate_post_run_input_guard(self) -> None:
        """Disable destructive Results mouse targets until quiet + human intent."""
        if not self.completed or self.running:
            return
        self._post_run_input_guard_active = True
        self._post_run_human_intent = False
        self._post_run_quiet_ready = False
        origin = self._cursor_global_pos()
        self._post_run_guard_origin = QPoint(origin)
        self._apply_post_run_input_guard_disable()
        self._set_post_run_input_guard_status_visible(True)
        self._restart_post_run_quiet_timer()
        self._sync_capture_chart_pan()

    def _restart_post_run_quiet_timer(self) -> None:
        self._post_run_quiet_ready = False
        self._post_run_quiet_timer.stop()
        self._post_run_quiet_timer.start(int(self._post_run_quiet_ms()))

    def _note_post_run_human_intent(self, event=None) -> None:
        if not self._post_run_input_guard_active or self._post_run_human_intent:
            return
        pos = _mouse_event_global_pos(event)
        if pos is None:
            pos = QPoint(self._cursor_global_pos())
        origin = self._post_run_guard_origin
        dx = int(pos.x()) - int(origin.x())
        dy = int(pos.y()) - int(origin.y())
        threshold = int(POST_RUN_HUMAN_INTENT_MOVE_PX)
        if (dx * dx) + (dy * dy) < (threshold * threshold):
            return
        self._post_run_human_intent = True
        self._try_release_post_run_input_guard()

    def _on_post_run_quiet_timeout(self) -> None:
        if not self._post_run_input_guard_active:
            return
        self._post_run_quiet_ready = True
        self._try_release_post_run_input_guard()

    def _try_release_post_run_input_guard(self) -> None:
        if (
            self._post_run_input_guard_active
            and self._post_run_quiet_ready
            and self._post_run_human_intent
        ):
            self._release_post_run_input_guard()

    def _cancel_post_run_input_guard(self) -> None:
        was_active = self._post_run_input_guard_active
        self._post_run_input_guard_active = False
        self._post_run_human_intent = False
        self._post_run_quiet_ready = False
        self._post_run_quiet_timer.stop()
        if was_active:
            self._set_post_run_input_guard_status_visible(False)

    def _release_post_run_input_guard(self) -> None:
        if not self._post_run_input_guard_active:
            return
        self._cancel_post_run_input_guard()
        self._update_controls()
        self.nav_setup.setEnabled(True)
        self.nav_capture.setEnabled(True)
        self.nav_preferences.setEnabled(True)
        self.nav_results.setEnabled(True)
        self.btn_help.setEnabled(True)

    def eventFilter(self, watched, event):  # noqa: N802
        if self._post_run_input_guard_active and event is not None:
            etype = event.type()
            if etype in _POST_RUN_BUTTON_EVENTS:
                self._restart_post_run_quiet_timer()
            elif etype == QEvent.Type.MouseMove:
                self._note_post_run_human_intent(event)
        return super().eventFilter(watched, event)

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
            pos = self._cursor_global_pos()
            if not self.test_area.rect().contains(self.test_area.mapFromGlobal(pos)):
                return False
            # Capture scrolls: Test Area geometry outside the viewport is clipped, not clickable.
            viewport = self.capture_scroll.viewport()
            return viewport.rect().contains(viewport.mapFromGlobal(pos))
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
                self.alert_label.setText(self._tr("wrong_button_alert", button=button))
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
            self.startup_window_combo,
            self.custom_width_spin,
            self.custom_height_spin,
            self.apply_custom_size_button,
            self.remember_window_size_checkbox,
            self.reset_window_geometry_button,
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
            self.setup_screening_card,
            self.btn_arm,
            self.btn_edit_profile,
            self.capture_viz_toolbar,
            self.btn_capture_new_run,
            self.btn_capture_goto_results,
            self.btn_capture_edit_setup,
            self.btn_new,
            self.btn_edit_setup_new_run,
            self.btn_generate_excel,
            self.btn_generate_html,
            self.btn_export,
            self.btn_overlay,
            self.btn_clear_overlay,
            *self._limit_edits.values(),
            self.setup_scroll.verticalScrollBar(),
            self.capture_scroll.verticalScrollBar(),
            self.results_scroll.verticalScrollBar(),
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
            self.alert_label.setText(self._tr("wrong_button_expected_alert", button=button, target=target))
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
        self.capture_completed_note.hide()
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
        run_status = completed_run_status(self.events, tags) if self.completed else "--"
        accepted = [e for e in annotated if e.get("accepted")]
        self.val_clicks.setText(str(accepted_host_press_count(self.events)))
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
        self.val_dut.setText(self._tr("na"))
        self.val_setup.setText(self._tr("na"))
        self.val_verdict.setText(self._run_status_display(run_status))
        if final or self.completed:
            if self._screening_profile_active():
                alert = []
                for tag in _QT_ALERT_TAGS:
                    if tag not in tags:
                        continue
                    if tag in SCREENING_PRESENTATION_KEYS:
                        alert.append(screening_presentation_label(tag, self._tr))
                    else:
                        alert.append(str(tag))
                self.alert_label.setText(" · ".join(alert))
            else:
                self.alert_label.setText("")
            self.review_text.clear()
            self._refresh_results_workspace()

        self._update_overlay_deltas(m)

        pts, series = self._chart_points(accepted)
        beat = cadence_ms(settings)
        overlay_ann = annotate_events(list(self.overlay_events), settings) if self.overlay_events else []
        ov_pts, ov_series = self._chart_points(overlay_ann)
        fixture = not _is_manual_profile(settings)
        reference = beat if fixture else None
        subtitle = self._capture_chart_subtitle(settings)
        duration_s = settings.get("duration_sec")
        capture_duration_ms = None
        if isinstance(duration_s, (int, float)) and not isinstance(duration_s, bool) and duration_s > 0:
            capture_duration_ms = float(duration_s) * 1000.0
        self.scatter.set_points(
            pts,
            title=self._tr("chart_stability_map"),
            subtitle=subtitle,
            overlay=ov_pts,
            target_beat_ms=reference,
        )
        self.interval_chart.set_series(
            series,
            title=self._tr("chart_interval_trend"),
            overlay=ov_series,
            target_beat_ms=reference,
            capture_duration_ms=capture_duration_ms,
        )

    def closeEvent(self, event):
        if getattr(self, "_listen_start_timer", None) is not None:
            self._listen_start_timer.stop()
        if getattr(self, "ui_timer", None) is not None:
            self.ui_timer.stop()
        if getattr(self, "_post_run_quiet_timer", None) is not None:
            self._post_run_quiet_timer.stop()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._save_window_geometry()
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
    window_settings = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "MCSA",
        "MouseClickStabilityAnalyzer",
    )
    win = MainWindow(
        report_root=root,
        target=target,
        operator=operator,
        run_id=run_id or "",
        lang=lang,
        theme=theme,
        window_settings=window_settings,
    )
    win.show_startup_window()
    return app.exec()
