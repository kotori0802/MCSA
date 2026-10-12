"""QPainter charts with axes, legends, and overlay support."""
from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import Qt, QPoint, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QPainterPath, QPolygonF
from PySide6.QtWidgets import QScrollBar, QToolTip, QWidget

from ..chart_domain import (
    DOMAIN_COUNT,
    DOMAIN_HOLD,
    DOMAIN_INTERVAL,
    domain_axis_bounds,
)
from ..interval_comparison import (
    POSITION_ABOVE,
    POSITION_BELOW,
    POSITION_NOT_COMPARABLE,
    POSITION_WITHIN,
    classify_interval,
)
from ..duration import elapsed_axis_uses_seconds, format_elapsed_axis_tick
from .presentation import screening_presentation_label
from .styles import ChartPalette, LIGHT_PALETTE, chart_font

FIT_MARGIN_FRAC = 0.08
SCATTER_X_MIN_SPAN_MS = 8.0
SCATTER_Y_MIN_SPAN_MS = 8.0
INTERVAL_Y_MIN_SPAN_MS = 8.0
INTERVAL_X_MIN_SPAN_MS = 500.0
ZOOM_IN_FACTOR = 0.8
ZOOM_OUT_FACTOR = 1.25
WHEEL_ANGLE_NOTCH = 120
WHEEL_PIXELS_PER_NOTCH = 40.0
WHEEL_MAX_STEPS_PER_EVENT = 4
NAV_CONTEXT_FACTOR = 4.0
AXIS_CONTEXT = "context"
AXIS_ELAPSED = "elapsed"
HOVER_HIT_PX = 12.0
# Low-emphasis fill so the band never competes with observation markers.
RANGE_BAND_ALPHA = 38
# One palette entry per configured-range category; histogram bar fill and legend share it.
HIST_CATEGORY_PALETTE_KEYS = {
    POSITION_BELOW: "chatter",
    POSITION_WITHIN: "interval_line",
    POSITION_ABOVE: "extra",
}


def nice_ticks(vmin: float, vmax: float, target: int = 5) -> list[float]:
    if vmax <= vmin:
        vmax = vmin + 1.0
    span = vmax - vmin
    raw = span / max(1, target)
    mag = 10 ** math.floor(math.log10(max(raw, 1e-9)))
    norm = raw / mag
    if norm < 1.5:
        step = 1 * mag
    elif norm < 3:
        step = 2 * mag
    elif norm < 7:
        step = 5 * mag
    else:
        step = 10 * mag
    start = math.floor(vmin / step) * step
    ticks: list[float] = []
    v = start
    guard = 0
    while v <= vmax + step * 0.001 and guard < 24:
        if v >= vmin - step * 0.001:
            ticks.append(round(v, 6))
        v += step
        guard += 1
    if len(ticks) < 2:
        ticks = [round(vmin, 4), round(vmax, 4)]
    else:
        if ticks[0] > vmin + step * 0.05:
            ticks.insert(0, round(vmin, 4))
        if ticks[-1] < vmax - step * 0.05:
            last_gap = vmax - ticks[-1]
            if last_gap >= span * 0.12:
                ticks.append(round(vmax, 4))
    # Drop ticks that are too close (avoids "140" on top of "145" labels)
    merged: list[float] = []
    for t in ticks:
        if merged and abs(t - merged[-1]) < span * 0.09:
            continue
        merged.append(t)
    return merged


def _fmt_tick(v: float) -> str:
    av = abs(v)
    if av >= 1000:
        return f"{v:.0f}"
    if av >= 100:
        return f"{v:.0f}"
    if av >= 10:
        return f"{v:.1f}"
    if av >= 1:
        return f"{v:.1f}"
    return f"{v:.2f}"


def _finite_values(values) -> list[float]:
    out: list[float] = []
    for raw in values or ():
        if raw is None:
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            out.append(v)
    return out


def fitted_range(
    values,
    *,
    extra=None,
    margin_frac: float = FIT_MARGIN_FRAC,
    min_span: float = SCATTER_X_MIN_SPAN_MS,
) -> tuple[float, float]:
    """Deterministic visual range. Presentation-only; never mutates observations."""
    nums = _finite_values(list(values or []) + list(extra or []))
    span_floor = float(min_span) if math.isfinite(float(min_span)) and float(min_span) > 0 else 1.0
    if not nums:
        return 0.0, span_floor
    lo = min(nums)
    hi = max(nums)
    span = hi - lo
    pad = max(span * float(margin_frac), span_floor * 0.1)
    lo -= pad
    hi += pad
    if (not math.isfinite(lo)) or (not math.isfinite(hi)) or hi <= lo:
        mid = nums[0]
        return mid - span_floor / 2.0, mid + span_floor / 2.0
    if hi - lo < span_floor:
        mid = (lo + hi) / 2.0
        lo = mid - span_floor / 2.0
        hi = mid + span_floor / 2.0
    if hi <= lo:
        return lo, lo + span_floor
    return lo, hi


def _range_anchors(bounds: tuple[float, float] | None) -> list[float]:
    if not bounds:
        return []
    try:
        lo, hi = float(bounds[0]), float(bounds[1])
    except (TypeError, ValueError, IndexError):
        return []
    return [v for v in (lo, hi) if math.isfinite(v)]


def _guide_anchors(center: float | None, bounds: tuple[float, float] | None = None) -> list[float]:
    return _reference_anchors(center) + _range_anchors(bounds)


def _reference_anchors(center: float | None) -> list[float]:
    if center is None:
        return []
    try:
        ref = float(center)
    except (TypeError, ValueError):
        return []
    if not math.isfinite(ref):
        return []
    return [ref]


def _valid_axis(lo: float, hi: float) -> bool:
    return math.isfinite(lo) and math.isfinite(hi) and hi > lo


def axis_navigation_envelope(
    content_lo: float,
    content_hi: float,
    *,
    min_span: float,
    kind: str,
    duration_ms: float | None = None,
) -> tuple[float, float]:
    """Presentation-only axis envelope. Always contains the content range.

    ``NAV_CONTEXT_FACTOR`` is a UX/navigation constant, not an acceptance limit.
    """
    span_floor = float(min_span) if math.isfinite(float(min_span)) and float(min_span) > 0 else 1.0
    if not _valid_axis(content_lo, content_hi):
        return 0.0, span_floor
    lo, hi = float(content_lo), float(content_hi)
    if kind == AXIS_ELAPSED:
        if duration_ms is not None:
            try:
                dur = float(duration_ms)
            except (TypeError, ValueError):
                dur = None
            else:
                if math.isfinite(dur) and dur > 0:
                    pad = max((max(hi, dur) - lo) * FIT_MARGIN_FRAC, span_floor * 0.1)
                    hi = max(hi, dur + pad)
        if hi <= lo:
            hi = lo + span_floor
        return lo, hi
    span = hi - lo
    mid = (lo + hi) / 2.0
    env_span = max(span * NAV_CONTEXT_FACTOR, span_floor)
    env_lo = min(lo, mid - env_span / 2.0)
    env_hi = max(hi, mid + env_span / 2.0)
    floor = min(0.0, lo)
    env_lo = max(env_lo, floor)
    if env_lo > lo:
        env_lo = lo
    if env_hi <= env_lo:
        env_hi = env_lo + max(span, span_floor)
    return env_lo, env_hi


def elapsed_viewport(lo: float, hi: float) -> tuple[float, float]:
    """Elapsed-domain view never starts before t=0; padding shifts right, span is kept."""
    if not _valid_axis(lo, hi) or lo >= 0.0:
        return lo, hi
    return 0.0, hi - lo


def _clamp_axis(lo: float, hi: float, env_lo: float, env_hi: float, min_span: float) -> tuple[float, float]:
    if not _valid_axis(env_lo, env_hi):
        return lo, hi
    env_span = env_hi - env_lo
    span = hi - lo
    span_floor = float(min_span) if math.isfinite(float(min_span)) and float(min_span) > 0 else 1.0
    if not math.isfinite(span) or span <= 0:
        span = min(span_floor, env_span)
    span = min(max(span, min(span_floor, env_span)), env_span)
    if lo < env_lo:
        lo = env_lo
        hi = lo + span
    if hi > env_hi:
        hi = env_hi
        lo = hi - span
    if lo < env_lo:
        return env_lo, env_hi
    return lo, hi


class _ChartBase(QWidget):
    TITLE_H = 22
    LEGEND_H = 28
    TOP_PAD = 8
    LEFT = 58
    RIGHT = 16
    BOTTOM = 52
    SCROLL_H = 14
    SCROLL_STEPS = 10000
    SUBTITLE_H = 16

    def __init__(self, parent=None):
        super().__init__(parent)
        self.palette: ChartPalette = LIGHT_PALETTE
        self.labels: dict[str, str] = {}
        self.subtitle = ""
        self.data_aware_fit = False
        self.factual_guides = False
        self.measurement_only_presentation = False
        self.target_beat_ms: float | None = None
        self.configured_range: tuple[float, float] | None = None
        self.zoom_locked = False
        self._user_view: tuple[float, float, float, float] | None = None
        self._nav_home: tuple[float, float, float, float] | None = None
        self._wheel_accum = 0
        self._pan_enabled = False
        self._panning = False
        self._pan_last: QPointF | None = None
        self.capture_duration_ms: float | None = None
        self._syncing_x_scroll = False
        self._x_scroll = QScrollBar(Qt.Orientation.Horizontal, self)
        self._x_scroll.setVisible(False)
        self._x_scroll.setAutoFillBackground(True)
        self._x_scroll.valueChanged.connect(self._on_x_scroll)
        self.setMinimumHeight(200)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    @property
    def pan_enabled(self) -> bool:
        return self._pan_enabled

    def set_theme(self, palette: ChartPalette, labels: dict[str, str] | None = None):
        self.palette = palette
        if labels:
            self.labels = labels
        self.update()

    def set_data_aware_fit(self, enabled: bool) -> None:
        self.data_aware_fit = bool(enabled)
        self.factual_guides = bool(enabled)
        self.setMouseTracking(bool(enabled))
        self.update()

    def set_measurement_only_presentation(self, enabled: bool) -> None:
        """Results Measurement-only legend/colors. Does not enable Capture navigation."""
        self.measurement_only_presentation = bool(enabled)
        self.update()

    def _label(self, key: str, fallback: str = "") -> str:
        text = self.labels.get(key) if self.labels else ""
        if text:
            return text
        from ..i18n import t
        resolved = t("en", key)
        if resolved != key:
            return resolved
        return fallback or key

    def _screening_label(self, internal: str, fallback: str) -> str:
        def tr(key: str, **_kwargs: object) -> str:
            return self._label(key, fallback)

        return screening_presentation_label(internal, tr)

    def _title_block_h(self) -> float:
        return self.TITLE_H + (self.SUBTITLE_H if self.subtitle else 0)

    def _plot_top(self) -> float:
        return self.TOP_PAD + self._title_block_h() + self.LEGEND_H + 10

    def _legend_y(self) -> int:
        return int(self.TOP_PAD + self._title_block_h() + 4)

    def _plot_rect(self) -> QRectF:
        top = self._plot_top()
        return QRectF(
            self.LEFT,
            top,
            max(1, self.width() - self.LEFT - self.RIGHT),
            max(1, self.height() - top - self.BOTTOM - self.SCROLL_H),
        )

    def fit_data(self) -> None:
        self._panning = False
        self._pan_last = None
        self.zoom_locked = False
        self._user_view = None
        self._wheel_accum = 0
        home = self.autofit_bounds()
        self._nav_home = home if home is not None and _valid_axis(home[0], home[1]) and _valid_axis(home[2], home[3]) else None
        self.unsetCursor()
        self.update()
        self._sync_x_scroll()

    def reset_view(self) -> None:
        if self._nav_home is None:
            self.fit_data()
            return
        home = self._nav_home
        if not (_valid_axis(home[0], home[1]) and _valid_axis(home[2], home[3])):
            self.fit_data()
            return
        self._panning = False
        self._pan_last = None
        self._user_view = home
        self.zoom_locked = True
        self._wheel_accum = 0
        self.update()
        self._sync_x_scroll()

    def clear_navigation(self) -> None:
        self.zoom_locked = False
        self._user_view = None
        self._nav_home = None
        self._wheel_accum = 0
        self._panning = False
        self._pan_last = None
        self.set_pan_enabled(False)
        self.update()
        self._sync_x_scroll()

    def set_pan_enabled(self, enabled: bool) -> None:
        self._pan_enabled = bool(enabled)
        if not self._pan_enabled:
            self._panning = False
            self._pan_last = None
            self.unsetCursor()
        self.update()

    def zoom_in(self) -> None:
        self._zoom_by(ZOOM_IN_FACTOR)

    def zoom_out(self) -> None:
        self._zoom_by(ZOOM_OUT_FACTOR)

    def visible_bounds(self) -> tuple[float, float, float, float] | None:
        if self.zoom_locked and self._user_view is not None:
            xmin, xmax, ymin, ymax = self._user_view
            if xmax > xmin and ymax > ymin and all(math.isfinite(v) for v in self._user_view):
                return self._user_view
        return self.autofit_bounds()

    def autofit_bounds(self) -> tuple[float, float, float, float] | None:
        return None

    def _min_spans(self) -> tuple[float, float]:
        return SCATTER_X_MIN_SPAN_MS, SCATTER_Y_MIN_SPAN_MS

    def _axis_kinds(self) -> tuple[str, str]:
        return AXIS_CONTEXT, AXIS_CONTEXT

    def navigation_envelope(self) -> tuple[float, float, float, float] | None:
        content = self.autofit_bounds()
        if content is None:
            return None
        xmin, xmax, ymin, ymax = content
        min_x, min_y = self._min_spans()
        x_kind, y_kind = self._axis_kinds()
        x_lo, x_hi = axis_navigation_envelope(
            xmin, xmax, min_span=min_x, kind=x_kind, duration_ms=self.capture_duration_ms,
        )
        y_lo, y_hi = axis_navigation_envelope(
            ymin, ymax, min_span=min_y, kind=y_kind, duration_ms=None,
        )
        if not (_valid_axis(x_lo, x_hi) and _valid_axis(y_lo, y_hi)):
            return None
        return x_lo, x_hi, y_lo, y_hi

    def _clamp_view(self, view: tuple[float, float, float, float]) -> tuple[float, float, float, float] | None:
        xmin, xmax, ymin, ymax = view
        env = self.navigation_envelope()
        min_x, min_y = self._min_spans()
        if env is not None:
            xmin, xmax = _clamp_axis(xmin, xmax, env[0], env[1], min_x)
            ymin, ymax = _clamp_axis(ymin, ymax, env[2], env[3], min_y)
        clamped = (xmin, xmax, ymin, ymax)
        if not (_valid_axis(xmin, xmax) and _valid_axis(ymin, ymax)):
            return None
        if not all(math.isfinite(v) for v in clamped):
            return None
        return clamped

    def _commit_view(self, view: tuple[float, float, float, float]) -> None:
        clamped = self._clamp_view(view)
        if clamped is None:
            return
        self._ensure_nav_home()
        self._user_view = clamped
        self.zoom_locked = True
        self.update()
        self._sync_x_scroll()

    def _ensure_nav_home(self) -> None:
        if self._nav_home is not None:
            return
        home = self.autofit_bounds()
        if home is not None and _valid_axis(home[0], home[1]) and _valid_axis(home[2], home[3]):
            self._nav_home = home

    def _fitted_x_domain(self) -> tuple[float, float] | None:
        content = self.autofit_bounds()
        if content is None or not _valid_axis(content[0], content[1]):
            return None
        return content[0], content[1]

    def _layout_x_scroll(self) -> None:
        y = max(0, self.height() - self.SCROLL_H - 2)
        self._x_scroll.setGeometry(self.LEFT, y, max(1, self.width() - self.LEFT - self.RIGHT), self.SCROLL_H)

    def _sync_x_scroll(self) -> None:
        if self._syncing_x_scroll:
            return
        self._layout_x_scroll()
        domain = self._fitted_x_domain()
        visible = self.visible_bounds()
        if domain is None or visible is None:
            self._x_scroll.setVisible(False)
            return
        xlo, xhi = domain
        vlo, vis_hi = visible[0], visible[1]
        domain_span = xhi - xlo
        vis_span = vis_hi - vlo
        if domain_span <= 0 or vis_span <= 0 or vis_span >= domain_span * 0.999:
            self._x_scroll.setVisible(False)
            return
        usable = domain_span - vis_span
        page = max(1, int(round(vis_span / domain_span * self.SCROLL_STEPS)))
        maximum = max(1, self.SCROLL_STEPS - page)
        value = int(round((vlo - xlo) / usable * maximum)) if usable > 0 else 0
        self._syncing_x_scroll = True
        try:
            self._x_scroll.setVisible(True)
            self._x_scroll.setRange(0, maximum)
            self._x_scroll.setPageStep(page)
            self._x_scroll.setSingleStep(max(1, page // 16))
            self._x_scroll.setValue(max(0, min(maximum, value)))
        finally:
            self._syncing_x_scroll = False

    def _on_x_scroll(self, value: int) -> None:
        if self._syncing_x_scroll:
            return
        domain = self._fitted_x_domain()
        visible = self.visible_bounds()
        if domain is None or visible is None:
            return
        xlo, xhi = domain
        vis_span = visible[1] - visible[0]
        domain_span = xhi - xlo
        if vis_span <= 0 or vis_span >= domain_span:
            return
        usable = domain_span - vis_span
        maximum = max(1, self._x_scroll.maximum())
        new_lo = xlo + (value / maximum) * usable
        self._commit_view((new_lo, new_lo + vis_span, visible[2], visible[3]))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_x_scroll()

    def _event_local_pos(self, event) -> QPointF:
        if hasattr(event, "position"):
            return QPointF(event.position())
        return QPointF(event.pos())

    def data_at_pixel(self, pos) -> tuple[float, float] | None:
        """Map a widget pixel through the plot rect to current visible data coordinates."""
        bounds = self.visible_bounds()
        plot = self._plot_rect()
        pt = QPointF(pos)
        if bounds is None or plot.width() <= 0 or plot.height() <= 0:
            return None
        if not plot.contains(pt):
            return None
        xmin, xmax, ymin, ymax = bounds
        dx = xmax - xmin
        dy = ymax - ymin
        if dx <= 0 or dy <= 0 or not all(math.isfinite(v) for v in bounds):
            return None
        cx = xmin + (pt.x() - plot.left()) / plot.width() * dx
        cy = ymin + (plot.bottom() - pt.y()) / plot.height() * dy
        if not (math.isfinite(cx) and math.isfinite(cy)):
            return None
        return cx, cy

    def pixel_at_data(self, cx: float, cy: float) -> QPointF | None:
        """Inverse of data_at_pixel: visible data coordinate → widget pixel in the plot rect."""
        bounds = self.visible_bounds()
        plot = self._plot_rect()
        if bounds is None or plot.width() <= 0 or plot.height() <= 0:
            return None
        xmin, xmax, ymin, ymax = bounds
        dx = xmax - xmin
        dy = ymax - ymin
        if dx <= 0 or dy <= 0 or not all(math.isfinite(v) for v in bounds):
            return None
        if not (math.isfinite(cx) and math.isfinite(cy)):
            return None
        x = plot.left() + (cx - xmin) / dx * plot.width()
        y = plot.bottom() - (cy - ymin) / dy * plot.height()
        if not (math.isfinite(x) and math.isfinite(y)):
            return None
        return QPointF(x, y)

    def _zoom_by(self, factor: float, cx: float | None = None, cy: float | None = None) -> None:
        """Scale the visible range around an anchor in data coordinates.

        The anchor keeps its fractional position in the new range, so a wheel
        cursor stays under the pointer and a button zoom (range center) stays
        centered. Presentation-only; never mutates observations.
        """
        bounds = self.visible_bounds()
        if bounds is None:
            return
        xmin, xmax, ymin, ymax = bounds
        xspan0 = xmax - xmin
        yspan0 = ymax - ymin
        if not (math.isfinite(xspan0) and math.isfinite(yspan0) and xspan0 > 0 and yspan0 > 0):
            return
        if cx is None:
            cx = xmin + xspan0 / 2.0
        if cy is None:
            cy = ymin + yspan0 / 2.0
        if not (math.isfinite(cx) and math.isfinite(cy)):
            return
        try:
            scale = float(factor)
        except (TypeError, ValueError):
            return
        if not math.isfinite(scale) or scale <= 0:
            return
        min_x, min_y = self._min_spans()
        xspan = max(xspan0 * scale, min_x)
        yspan = max(yspan0 * scale, min_y)
        if not (math.isfinite(xspan) and math.isfinite(yspan) and xspan > 0 and yspan > 0):
            return
        frac_x = min(1.0, max(0.0, (cx - xmin) / xspan0))
        frac_y = min(1.0, max(0.0, (cy - ymin) / yspan0))
        xmin_n = cx - frac_x * xspan
        xmax_n = xmin_n + xspan
        ymin_n = cy - frac_y * yspan
        ymax_n = ymin_n + yspan
        view = (xmin_n, xmax_n, ymin_n, ymax_n)
        if xmax_n <= xmin_n or ymax_n <= ymin_n or not all(math.isfinite(v) for v in view):
            return
        self._commit_view(view)

    def _wheel_notch_steps(self, event) -> int:
        """Map a wheel event to deterministic ±120 notch steps. Remainder is kept."""
        angle = 0
        if hasattr(event, "angleDelta"):
            angle = int(event.angleDelta().y())
        if angle == 0 and hasattr(event, "pixelDelta"):
            pixels = int(event.pixelDelta().y())
            if pixels != 0:
                angle = int(round(pixels * (WHEEL_ANGLE_NOTCH / WHEEL_PIXELS_PER_NOTCH)))
        if angle == 0:
            return 0
        self._wheel_accum += angle
        steps = 0
        while self._wheel_accum >= WHEEL_ANGLE_NOTCH:
            self._wheel_accum -= WHEEL_ANGLE_NOTCH
            steps += 1
        while self._wheel_accum <= -WHEEL_ANGLE_NOTCH:
            self._wheel_accum += WHEEL_ANGLE_NOTCH
            steps -= 1
        if steps > WHEEL_MAX_STEPS_PER_EVENT:
            steps = WHEEL_MAX_STEPS_PER_EVENT
        elif steps < -WHEEL_MAX_STEPS_PER_EVENT:
            steps = -WHEEL_MAX_STEPS_PER_EVENT
        return steps

    def wheelEvent(self, event):
        if not self.data_aware_fit:
            super().wheelEvent(event)
            return
        pos = self._event_local_pos(event)
        plot = self._plot_rect()
        if not plot.contains(pos):
            self._wheel_accum = 0
            event.ignore()
            return
        steps = self._wheel_notch_steps(event)
        if steps != 0:
            for _ in range(abs(steps)):
                data = self.data_at_pixel(pos)
                if data is None:
                    break
                cx, cy = data
                factor = ZOOM_IN_FACTOR if steps > 0 else ZOOM_OUT_FACTOR
                self._zoom_by(factor, cx=cx, cy=cy)
        event.accept()

    def _begin_pan(self, event) -> bool:
        if not (self.data_aware_fit and self._pan_enabled):
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        pos = self._event_local_pos(event)
        if not self._plot_rect().contains(pos):
            return False
        if self.visible_bounds() is None:
            return False
        self._ensure_nav_home()
        self._panning = True
        self._pan_last = QPointF(pos)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.grabMouse()
        return True

    def _update_pan(self, event) -> bool:
        if not self._panning or self._pan_last is None:
            return False
        pos = self._event_local_pos(event)
        bounds = self.visible_bounds()
        plot = self._plot_rect()
        if bounds is None or plot.width() <= 0 or plot.height() <= 0:
            return True
        xmin, xmax, ymin, ymax = bounds
        xspan = xmax - xmin
        yspan = ymax - ymin
        dx_px = pos.x() - self._pan_last.x()
        dy_px = pos.y() - self._pan_last.y()
        xmin_n = xmin - dx_px / plot.width() * xspan
        xmax_n = xmin_n + xspan
        ymin_n = ymin + dy_px / plot.height() * yspan
        ymax_n = ymin_n + yspan
        self._commit_view((xmin_n, xmax_n, ymin_n, ymax_n))
        self._pan_last = QPointF(pos)
        return True

    def _end_pan(self, event) -> bool:
        if not self._panning:
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        self._panning = False
        self._pan_last = None
        self.releaseMouse()
        pos = self._event_local_pos(event)
        if self._pan_enabled and self._plot_rect().contains(pos):
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()
        return True

    def _sync_pan_cursor(self, event) -> None:
        if self._panning or not self._pan_enabled or not self.data_aware_fit:
            return
        pos = self._event_local_pos(event)
        if self._plot_rect().contains(pos):
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, event):
        if self._begin_pan(event):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._update_pan(event):
            event.accept()
            return
        self._sync_pan_cursor(event)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._end_pan(event):
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if not self._panning:
            self.unsetCursor()
        super().leaveEvent(event)

    def _comparison_contract(self) -> dict | None:
        if not self.configured_range:
            return None
        lo, hi = self.configured_range
        return {"enabled": True, "lower_bound_ms": lo, "upper_bound_ms": hi}

    def _range_position(self, interval_ms: float) -> str:
        return classify_interval(interval_ms, self._comparison_contract())

    def range_layers(self) -> list[tuple[str, float]]:
        """Semantic guide layers drawn for the configured range, in paint order."""
        layers: list[tuple[str, float]] = []
        if self.configured_range:
            lo, hi = self.configured_range
            layers += [("band_lower", lo), ("band_upper", hi), ("lower_bound", lo), ("upper_bound", hi)]
        for ref in _reference_anchors(self.target_beat_ms):
            layers.append(("reference", ref))
        return layers

    def _range_legend_items(self) -> list[tuple[str, str]]:
        if not self.configured_range:
            return []
        return [(self.palette.range_edge, self._label("legend_configured_range", "Configured interval range"))]

    def _comparison_legend_items(self) -> list[tuple[str, str]]:
        if not self.configured_range:
            return []
        pal = self.palette
        return self._range_legend_items() + [
            (pal.on_cadence, self._label("legend_within_configured_range", "Within configured interval range")),
            (pal.extra, self._label("legend_outside_configured_range", "Outside configured interval range")),
        ]

    def _guide_legend_items(self) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        pal = self.palette
        if not self.target_beat_ms and not self.configured_range:
            return items
        if self.factual_guides or self.measurement_only_presentation:
            if self.target_beat_ms:
                items.append((pal.target_line, self._label("legend_configured_reference", "Reference interval")))
        else:
            if self.target_beat_ms:
                items.append((pal.target_line, self._label("legend_target", "Target beat")))
        return items

    def _draw_range_band(
        self,
        p: QPainter,
        plot: QRectF,
        *,
        map_lo: float,
        map_hi: float,
        vertical: bool,
    ) -> None:
        if not self.configured_range:
            return
        pal = self.palette
        fill = QColor(pal.range_band)
        fill.setAlpha(RANGE_BAND_ALPHA)
        a, b = (map_lo, map_hi) if map_lo <= map_hi else (map_hi, map_lo)
        if vertical:
            x0 = max(plot.left(), a)
            x1 = min(plot.right(), b)
            if x1 > x0:
                p.fillRect(QRectF(x0, plot.top(), x1 - x0, plot.height()), fill)
        else:
            y0 = max(plot.top(), a)
            y1 = min(plot.bottom(), b)
            if y1 > y0:
                p.fillRect(QRectF(plot.left(), y0, plot.width(), y1 - y0), fill)
        p.setPen(QPen(QColor(pal.range_edge), 1, Qt.PenStyle.SolidLine))
        for edge in (map_lo, map_hi):
            if vertical and plot.left() <= edge <= plot.right():
                p.drawLine(QPointF(edge, plot.top()), QPointF(edge, plot.bottom()))
            elif not vertical and plot.top() <= edge <= plot.bottom():
                p.drawLine(QPointF(plot.left(), edge), QPointF(plot.right(), edge))

    def _draw_vertical_range(self, p: QPainter, plot: QRectF, map_x: Callable[[float], float]) -> None:
        if not self.configured_range:
            return
        lo, hi = self.configured_range
        self._draw_range_band(p, plot, map_lo=map_x(lo), map_hi=map_x(hi), vertical=True)

    def _draw_horizontal_range(self, p: QPainter, plot: QRectF, map_y: Callable[[float], float]) -> None:
        if not self.configured_range:
            return
        lo, hi = self.configured_range
        self._draw_range_band(p, plot, map_lo=map_y(lo), map_hi=map_y(hi), vertical=False)

    def _draw_comparison_marker(self, p: QPainter, pt: QPointF, position: str, *, radius: float = 3.4) -> None:
        pal = self.palette
        outside = position in (POSITION_BELOW, POSITION_ABOVE)
        color = QColor(pal.extra if outside else pal.on_cadence)
        p.setBrush(QBrush(color))
        p.setPen(QPen(color.darker(120), 1))
        if outside:
            diamond = QPolygonF([
                QPointF(pt.x(), pt.y() - radius - 0.6),
                QPointF(pt.x() + radius + 0.6, pt.y()),
                QPointF(pt.x(), pt.y() + radius + 0.6),
                QPointF(pt.x() - radius - 0.6, pt.y()),
            ])
            p.drawPolygon(diamond)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(pt, radius, radius)

    def _comparison_tooltip_lines(self, interval_ms: float) -> list[str]:
        contract = self._comparison_contract()
        if not contract:
            return []
        position = self._range_position(interval_ms)
        lo, hi = self.configured_range or (0.0, 0.0)
        pos_key = {
            POSITION_WITHIN: "legend_within_configured_range",
            POSITION_BELOW: "range_position_below",
            POSITION_ABOVE: "range_position_above",
        }.get(position)
        pos_label = {
            POSITION_WITHIN: "Within configured interval range",
            POSITION_BELOW: "Below configured interval range",
            POSITION_ABOVE: "Above configured interval range",
        }.get(position, "")
        lines = [
            self._label("hover_observed_interval", "Observed interval: {value} ms").replace(
                "{value}", f"{interval_ms:.2f}"
            ),
            self._label("hover_configured_range", "Configured interval range: {lo}–{hi} ms")
            .replace("{lo}", f"{lo:.2f}")
            .replace("{hi}", f"{hi:.2f}"),
        ]
        if pos_key:
            lines.append(
                self._label("hover_position", "Range position: {position}").replace(
                    "{position}", self._label(pos_key, pos_label)
                )
            )
        if position == POSITION_ABOVE:
            delta = interval_ms - hi
            lines.append(
                self._label("hover_distance_above", "Distance above upper bound: +{value} ms").replace(
                    "{value}", f"{delta:.2f}"
                )
            )
        elif position == POSITION_BELOW:
            delta = lo - interval_ms
            lines.append(
                self._label("hover_distance_below", "Distance below lower bound: {value} ms").replace(
                    "{value}", f"{delta:.2f}"
                )
            )
        return lines

    def _draw_title(self, p: QPainter) -> None:
        pal = self.palette
        p.setPen(QColor(pal.text))
        p.setFont(chart_font("title", bold=True))
        p.drawText(12, 16, self.title if hasattr(self, "title") else "")
        if self.subtitle:
            p.setPen(QColor(pal.muted))
            p.setFont(chart_font("subtitle"))
            p.drawText(12, 32, self.subtitle)

    # Interval-domain charts draw only the configured reference. The Schedule
    # Association Window applies to timestamps, so it has no interval-axis band.
    def _draw_vertical_guides(self, p: QPainter, plot: QRectF, map_x: Callable[[float], float]) -> None:
        self._draw_vertical_range(p, plot, map_x)
        if not self.target_beat_ms:
            return
        pal = self.palette
        tx = map_x(float(self.target_beat_ms))
        p.setPen(QPen(QColor(pal.target_line), 1.5, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(tx, plot.top()), QPointF(tx, plot.bottom()))

    def _draw_horizontal_guides(self, p: QPainter, plot: QRectF, map_y: Callable[[float], float]) -> None:
        self._draw_horizontal_range(p, plot, map_y)
        if not self.target_beat_ms:
            return
        pal = self.palette
        ty = map_y(float(self.target_beat_ms))
        p.setPen(QPen(QColor(pal.target_line), 1.2, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(plot.left(), ty), QPointF(plot.right(), ty))

    def _draw_axes(
        self,
        p: QPainter,
        plot: QRectF,
        *,
        x_ticks: list[float],
        y_ticks: list[float],
        x_label: str,
        y_label: str,
        map_x: Callable[[float], float],
        map_y: Callable[[float], float],
        format_x: Callable[[float], str] | None = None,
        format_y: Callable[[float], str] | None = None,
    ):
        pal = self.palette
        p.setPen(QPen(QColor(pal.border), 1))
        p.drawRoundedRect(plot, 8, 8)
        p.fillRect(plot, QColor(pal.plot_bg))

        p.setPen(QPen(QColor(pal.grid), 1, Qt.PenStyle.DotLine))
        for yt in y_ticks:
            y = map_y(yt)
            if plot.top() <= y <= plot.bottom():
                p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        for xt in x_ticks:
            x = map_x(xt)
            if plot.left() <= x <= plot.right():
                p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))

        tick_font = chart_font("tick")
        p.setFont(tick_font)
        p.setPen(QColor(pal.muted))
        fm = p.fontMetrics()
        fmt_x = format_x or _fmt_tick
        fmt_y = format_y or _fmt_tick
        for yt in y_ticks:
            y = map_y(yt)
            if y < plot.top() - 2 or y > plot.bottom() + 2:
                continue
            # Keep top tick label out of the legend band
            if y < plot.top() + 14:
                continue
            p.drawText(
                QRectF(2, y - 8, self.LEFT - 10, 16),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                fmt_y(yt),
            )
        for xt in x_ticks:
            x = map_x(xt)
            if x < plot.left() - 2 or x > plot.right() + 2:
                continue
            text = fmt_x(xt)
            tw = fm.horizontalAdvance(text)
            p.drawText(
                QRectF(x - tw / 2 - 2, plot.bottom() + 5, tw + 4, 14),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                text,
            )

        p.setPen(QColor(pal.muted))
        p.drawText(int(plot.center().x() - 50), int(self.height() - 8), x_label)
        p.save()
        p.translate(14, plot.center().y())
        p.rotate(-90)
        p.drawText(-50, 0, y_label)
        p.restore()

    def _draw_legend_box(self, p: QPainter, plot: QRectF, items: list[tuple[str, str]]):
        if not items:
            return
        pal = self.palette
        font = chart_font("tick")
        p.setFont(font)
        fm = p.fontMetrics()
        row_h = 16
        gap = 12
        max_w = int(plot.width())
        y = self._legend_y()

        rows: list[list[tuple[str, str, int]]] = [[]]
        cx = 0
        for color, text in items:
            tw = fm.horizontalAdvance(text) + 22
            if cx + tw > max_w and rows[-1]:
                rows.append([])
                cx = 0
            rows[-1].append((color, text, tw))
            cx += tw + gap

        total_h = len(rows) * row_h
        box_top = y - 3
        box = QRectF(plot.left(), box_top, plot.width(), total_h + 6)
        bg = QColor(pal.bg)
        bg.setAlpha(235)
        p.fillRect(box, bg)

        for row_i, row in enumerate(rows):
            row_w = sum(tw for _, _, tw in row) + gap * max(0, len(row) - 1)
            cx = int(plot.right()) - row_w
            cy = y + row_i * row_h
            for color, text, tw in row:
                p.setBrush(QBrush(QColor(color)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(cx + 6, cy + 8), 4, 4)
                p.setPen(QColor(pal.muted))
                p.drawText(cx + 16, cy + 12, text)
                cx += tw + gap


class ScatterChart(_ChartBase):
    """Hold vs Interval scatter (interval on X, hold on Y)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.points: list[tuple] = []
        self.overlay_points: list[tuple] = []
        self.title = "Click interval vs Hold duration"
        self.setMinimumHeight(260)

    def set_points(
        self,
        points: list[tuple],
        *,
        title: str = "",
        subtitle: str = "",
        overlay: list[tuple] | None = None,
        target_beat_ms: float | None = None,
        configured_range: tuple[float, float] | None = None,
    ):
        self.points = list(points or [])
        self.overlay_points = list(overlay or [])
        if title:
            self.title = title
        self.subtitle = subtitle or ""
        self.target_beat_ms = target_beat_ms
        self.configured_range = configured_range
        self.update()
        self._sync_x_scroll()

    def point_range_positions(self) -> list[str]:
        """Range positions for the base points only; overlay is never classified."""
        if not self.configured_range:
            return []
        return [self._range_position(pt[0]) for pt in self.points]

    def _class_color(self, cls: str) -> str:
        pal = self.palette
        mapping = {
            "ON_CADENCE": pal.on_cadence,
            "TRUE_EXTRA_CLICK": pal.extra,
            "CHATTER_BOUNCE": pal.chatter,
            "CHATTER_HARD": pal.extra,
            "MISS_OR_SLOW": pal.miss,
            "INCOMPLETE_REBOUND": pal.rebound,
        }
        return mapping.get(cls, pal.on_cadence)

    def _point_color(self, cls: str) -> str:
        if self.measurement_only_presentation:
            return self.palette.on_cadence
        return self._class_color(cls)

    def legend_entries(self) -> list[tuple[str, str]]:
        pal = self.palette
        comparison_items = self._comparison_legend_items()
        if comparison_items:
            items = list(comparison_items)
        elif self.measurement_only_presentation:
            items = [
                (pal.on_cadence, self._label("legend_host_observation", "Host observation")),
            ]
        else:
            items = [
                (pal.on_cadence, self._screening_label("ON_CADENCE", "Observation")),
                (pal.extra, self._screening_label("TRUE_EXTRA_CLICK", "Short interval")),
                (pal.chatter, self._screening_label("CHATTER_BOUNCE", "Very short interval")),
                (pal.miss, self._screening_label("MISS_OR_SLOW", "Long interval")),
            ]
        if self.overlay_points:
            items.append((pal.overlay, self._label("legend_overlay", "Overlay (A)")))
        items.extend(self._guide_legend_items())
        return items

    def _xy_values(self) -> tuple[list[float], list[float]]:
        xs = _finite_values([row[0] for row in self.points] + [row[0] for row in self.overlay_points])
        ys = _finite_values([row[1] for row in self.points] + [row[1] for row in self.overlay_points])
        return xs, ys

    def autofit_bounds(self) -> tuple[float, float, float, float] | None:
        xs, ys = self._xy_values()
        extras = _guide_anchors(self.target_beat_ms, self.configured_range)
        if not xs and not extras:
            return fitted_range([], min_span=SCATTER_X_MIN_SPAN_MS) + fitted_range([], min_span=SCATTER_Y_MIN_SPAN_MS)
        if self.data_aware_fit:
            xmin, xmax = fitted_range(xs, extra=extras, min_span=SCATTER_X_MIN_SPAN_MS)
            ymin, ymax = fitted_range(ys, min_span=SCATTER_Y_MIN_SPAN_MS)
            xmin, xmax = domain_axis_bounds(xmin, xmax, domain=DOMAIN_INTERVAL, values=xs)
            ymin, ymax = domain_axis_bounds(ymin, ymax, domain=DOMAIN_HOLD, values=ys)
            return xmin, xmax, ymin, ymax
        if not xs:
            return None
        xmax = max(50.0, max(xs) * 1.08)
        ymax = max(15.0, max(ys) * 1.15 if ys else 15.0)
        if self.target_beat_ms:
            xmax = max(xmax, float(self.target_beat_ms) * 1.35)
        return 0.0, xmax, 0.0, ymax

    def _maps(self):
        bounds = self.visible_bounds()
        plot = self._plot_rect()
        if bounds is None:
            return None
        xmin, xmax, ymin, ymax = bounds
        dx = xmax - xmin
        dy = ymax - ymin
        if dx <= 0 or dy <= 0 or not all(math.isfinite(v) for v in bounds):
            return None
        if plot.width() <= 0 or plot.height() <= 0:
            return None

        def map_x(v: float) -> float:
            return plot.left() + (v - xmin) / dx * plot.width()

        def map_y(v: float) -> float:
            return plot.bottom() - (v - ymin) / dy * plot.height()

        return plot, bounds, map_x, map_y

    def nearest_observation(self, pos: QPoint, max_px: float = HOVER_HIT_PX) -> dict | None:
        mapped = self._maps()
        if mapped is None or not self.points:
            return None
        plot, _bounds, map_x, map_y = mapped
        px, py = float(pos.x()), float(pos.y())
        if not plot.contains(QPointF(px, py)):
            return None
        best = None
        best_d = float(max_px)
        for row in self.points[-2500:]:
            x, y = float(row[0]), float(row[1])
            dx = map_x(x) - px
            dy = map_y(y) - py
            dist = math.hypot(dx, dy)
            if dist <= best_d:
                best_d = dist
                index = row[3] if len(row) > 3 else None
                best = {
                    "interval_ms": x,
                    "hold_ms": y,
                    "click_class": str(row[2]) if len(row) > 2 else "",
                    "index": index,
                }
        return best

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if not self.data_aware_fit or self._panning:
            return
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        info = self.nearest_observation(pos)
        if info is None:
            QToolTip.hideText()
            return
        lines = []
        index = info.get("index")
        if index not in (None, ""):
            lines.append(self._label("hover_click", "Click #{n}").replace("{n}", str(index)))
        lines.append(
            self._label("hover_interval", "Interval {value} ms").replace("{value}", f"{info['interval_ms']:.2f}")
        )
        lines.append(
            self._label("hover_hold", "Hold {value} ms").replace("{value}", f"{info['hold_ms']:.2f}")
        )
        if self.configured_range:
            lines.extend(self._comparison_tooltip_lines(info["interval_ms"]))
        elif self.factual_guides and self.target_beat_ms is not None:
            delta = info["interval_ms"] - float(self.target_beat_ms)
            lines.append(
                self._label("hover_interval_delta", "Interval Δ vs reference {value} ms").replace(
                    "{value}", f"{delta:+.2f}"
                )
            )
        QToolTip.showText(event.globalPosition().toPoint() if hasattr(event, "globalPosition") else self.mapToGlobal(pos), "\n".join(lines), self)

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette
        p.fillRect(self.rect(), QColor(pal.bg))
        plot = self._plot_rect()
        self._draw_title(p)

        legend = self.legend_entries()
        self._draw_legend_box(p, plot, legend)

        if not self.points and not self.overlay_points:
            p.setPen(QColor(pal.muted))
            p.setFont(chart_font("placeholder"))
            p.drawText(plot, int(Qt.AlignmentFlag.AlignCenter), self._label("waiting_data", "Waiting for click data"))
            return

        mapped = self._maps()
        if mapped is None:
            return
        plot, bounds, map_x, map_y = mapped
        xmin, xmax, ymin, ymax = bounds

        self._draw_axes(
            p,
            plot,
            x_ticks=nice_ticks(xmin, xmax),
            y_ticks=nice_ticks(ymin, ymax),
            x_label=self._label("axis_interval_ms", "Click interval (ms)"),
            y_label=self._label("axis_hold_ms", "Hold duration (ms)"),
            map_x=map_x,
            map_y=map_y,
        )
        self._draw_vertical_guides(p, plot, map_x)

        p.save()
        p.setClipRect(plot)
        for row in self.overlay_points[-2500:]:
            x, y = float(row[0]), float(row[1])
            c = QColor(pal.overlay)
            c.setAlpha(90)
            p.setBrush(QBrush(c))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(map_x(x), map_y(y)), 2.8, 2.8)

        for row in self.points[-2500:]:
            x, y = float(row[0]), float(row[1])
            pt = QPointF(map_x(x), map_y(y))
            if self.configured_range:
                self._draw_comparison_marker(p, pt, self._range_position(x))
            else:
                cls = str(row[2]) if len(row) > 2 else "ON_CADENCE"
                p.setBrush(QBrush(QColor(self._point_color(cls))))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(pt, 3.4, 3.4)
        p.restore()


class IntervalChart(_ChartBase):
    """Interval over elapsed time."""

    y_domain = DOMAIN_INTERVAL
    y_label_key = "axis_interval_ms"
    y_label_default = "Click interval (ms)"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series: list[tuple[float, float]] = []
        self.overlay_series: list[tuple[float, float]] = []
        self.title = "Elapsed time vs Click interval"
        self.setMinimumHeight(220)

    def set_series(
        self,
        series: list[tuple[float, float]],
        *,
        title: str = "",
        overlay: list[tuple[float, float]] | None = None,
        target_beat_ms: float | None = None,
        capture_duration_ms: float | None = None,
        configured_range: tuple[float, float] | None = None,
    ):
        self.series = list(series or [])
        self.overlay_series = list(overlay or [])
        if title:
            self.title = title
        self.target_beat_ms = target_beat_ms
        self.capture_duration_ms = capture_duration_ms
        self.configured_range = configured_range
        self.update()
        self._sync_x_scroll()

    def _min_spans(self) -> tuple[float, float]:
        return INTERVAL_X_MIN_SPAN_MS, INTERVAL_Y_MIN_SPAN_MS

    def _axis_kinds(self) -> tuple[str, str]:
        return AXIS_ELAPSED, AXIS_CONTEXT

    def autofit_bounds(self) -> tuple[float, float, float, float] | None:
        all_pts = list(self.series) + list(self.overlay_series)
        xs = _finite_values([a[0] for a in all_pts])
        ys = _finite_values([a[1] for a in all_pts])
        extras = _guide_anchors(self.target_beat_ms, self.configured_range)
        if self.data_aware_fit:
            xmin, xmax = elapsed_viewport(*fitted_range(xs, min_span=INTERVAL_X_MIN_SPAN_MS))
            ymin, ymax = fitted_range(ys, extra=extras, min_span=INTERVAL_Y_MIN_SPAN_MS)
            ymin, ymax = domain_axis_bounds(ymin, ymax, domain=self.y_domain, values=ys)
            return xmin, xmax, ymin, ymax
        if len(self.series) < 2 and len(self.overlay_series) < 2:
            return None
        xmin_ms, xmax_ms = min(xs), max(xs)
        if xmax_ms <= xmin_ms:
            xmax_ms = xmin_ms + 1
        xmin_ms, xmax_ms = elapsed_viewport(xmin_ms, xmax_ms)
        ymin, ymax = 0.0, max(40.0, max(ys) * 1.12)
        if self.target_beat_ms:
            ymax = max(ymax, float(self.target_beat_ms) * 1.25)
        return xmin_ms, xmax_ms, ymin, ymax

    def _maps(self):
        bounds = self.visible_bounds()
        plot = self._plot_rect()
        if bounds is None:
            return None
        xmin, xmax, ymin, ymax = bounds
        dx = xmax - xmin
        dy = ymax - ymin
        if dx <= 0 or dy <= 0 or not all(math.isfinite(v) for v in bounds):
            return None
        if plot.width() <= 0 or plot.height() <= 0:
            return None

        def map_x_ms(v_ms: float) -> float:
            return plot.left() + (v_ms - xmin) / dx * plot.width()

        def map_x_s(v_s: float) -> float:
            return map_x_ms(v_s * 1000.0)

        def map_y(v: float) -> float:
            return plot.bottom() - (v - ymin) / dy * plot.height()

        return plot, bounds, map_x_ms, map_x_s, map_y

    def _interval_legend_label(self) -> str:
        return self._label("legend_click_interval", "Click interval")

    def legend_entries(self) -> list[tuple[str, str]]:
        pal = self.palette
        items = [(pal.interval_line, self._interval_legend_label())]
        items.extend(self._comparison_legend_items())
        if self.overlay_series:
            items.append((pal.overlay, self._label("legend_overlay", "Overlay (A)")))
        items.extend(self._guide_legend_items())
        return items

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette
        p.fillRect(self.rect(), QColor(pal.bg))
        plot = self._plot_rect()
        self._draw_title(p)

        legend = self.legend_entries()
        self._draw_legend_box(p, plot, legend)

        empty = not self.series and not self.overlay_series
        legacy_waiting = (not self.data_aware_fit) and len(self.series) < 2 and len(self.overlay_series) < 2
        if empty or legacy_waiting:
            p.setPen(QColor(pal.muted))
            p.setFont(chart_font("placeholder"))
            wait = self._label("waiting_data", "Waiting for click data") if self.data_aware_fit else self._interval_legend_label()
            p.drawText(plot, int(Qt.AlignmentFlag.AlignCenter), wait)
            return

        mapped = self._maps()
        if mapped is None:
            return
        plot, bounds, map_x_ms, map_x_s, map_y = mapped
        xmin_ms, xmax_ms, ymin, ymax = bounds
        span_ms = max(xmax_ms - xmin_ms, abs(xmax_ms), abs(xmin_ms))
        x_label = (
            self._label("axis_elapsed_s", "Elapsed time (s)")
            if elapsed_axis_uses_seconds(span_ms)
            else self._label("axis_elapsed", "Elapsed time")
        )

        self._draw_axes(
            p,
            plot,
            x_ticks=nice_ticks(xmin_ms, xmax_ms),
            y_ticks=nice_ticks(ymin, ymax),
            x_label=x_label,
            y_label=self._label(self.y_label_key, self.y_label_default),
            map_x=map_x_ms,
            map_y=map_y,
            format_x=lambda v, span=span_ms: format_elapsed_axis_tick(v, span_ms=span),
        )
        self._draw_horizontal_guides(p, plot, map_y)

        p.save()
        p.setClipRect(plot)
        if len(self.overlay_series) >= 2:
            p.setPen(QPen(QColor(pal.overlay), 1.5, Qt.PenStyle.DashLine))
            prev = None
            for x, y in self.overlay_series[-2500:]:
                pt = QPointF(map_x_ms(x), map_y(y))
                if prev is not None:
                    p.drawLine(prev, pt)
                prev = pt
        elif len(self.overlay_series) == 1:
            x, y = self.overlay_series[0]
            c = QColor(pal.overlay)
            c.setAlpha(90)
            p.setBrush(QBrush(c))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(map_x_ms(x), map_y(y)), 2.8, 2.8)

        if len(self.series) >= 2:
            path = QPainterPath()
            points = []
            first = True
            for x, y in self.series[-2500:]:
                pt = QPointF(map_x_ms(x), map_y(y))
                points.append(pt)
                if first:
                    path.moveTo(pt)
                    first = False
                else:
                    path.lineTo(pt)
            p.setPen(QPen(QColor(pal.interval_line), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            samples = list(self.series[-2500:])
            if self.configured_range:
                for (x, y), pt in zip(samples, points):
                    self._draw_comparison_marker(p, pt, self._range_position(y), radius=2.8)
            elif len(points) <= 80:
                p.setBrush(QBrush(QColor(pal.interval_line)))
                p.setPen(Qt.PenStyle.NoPen)
                for pt in points:
                    p.drawEllipse(pt, 2.4, 2.4)
        elif len(self.series) == 1:
            x, y = self.series[0]
            pt = QPointF(map_x_ms(x), map_y(y))
            if self.configured_range:
                self._draw_comparison_marker(p, pt, self._range_position(y))
            else:
                p.setBrush(QBrush(QColor(pal.interval_line)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(pt, 3.4, 3.4)
        p.restore()

    def nearest_observation(self, pos, *, max_px: float = HOVER_HIT_PX):
        mapped = self._maps()
        if mapped is None:
            return None
        _plot, _bounds, map_x_ms, _map_x_s, map_y = mapped
        px, py = pos.x(), pos.y()
        best = None
        best_d = float(max_px)
        for x, y in self.series[-2500:]:
            dx = map_x_ms(x) - px
            dy = map_y(y) - py
            dist = math.hypot(dx, dy)
            if dist <= best_d:
                best_d = dist
                best = {"elapsed_ms": x, "interval_ms": y}
        return best

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if not self.data_aware_fit or self._panning or not self.configured_range:
            return
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        info = self.nearest_observation(pos)
        if info is None:
            QToolTip.hideText()
            return
        lines = self._comparison_tooltip_lines(info["interval_ms"])
        QToolTip.showText(
            event.globalPosition().toPoint() if hasattr(event, "globalPosition") else self.mapToGlobal(pos),
            "\n".join(lines),
            self,
        )

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)

    def point_range_positions(self) -> list[str]:
        """Range positions for the base series only; overlay is never classified."""
        if not self.configured_range:
            return []
        return [self._range_position(y) for _x, y in self.series[-2500:]]


class HoldChart(IntervalChart):
    """Hold over elapsed press time. Neutral factual view: no range, no reference."""

    y_domain = DOMAIN_HOLD
    y_label_key = "axis_hold_ms"
    y_label_default = "Hold duration (ms)"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.title = "Elapsed time vs Hold duration"

    def set_series(
        self,
        series: list[tuple[float, float]],
        *,
        title: str = "",
        overlay: list[tuple[float, float]] | None = None,
        target_beat_ms: float | None = None,
        capture_duration_ms: float | None = None,
        configured_range: tuple[float, float] | None = None,
    ):
        super().set_series(
            series,
            title=title,
            overlay=overlay,
            target_beat_ms=None,
            capture_duration_ms=capture_duration_ms,
            configured_range=None,
        )

    def _interval_legend_label(self) -> str:
        return self._label("legend_hold_duration", "Hold duration")


HIST_X_MIN_SPAN_MS = 8.0
HIST_Y_MIN_SPAN = 1.0


class HistogramChart(_ChartBase):
    """Interval distribution histogram. Navigation inspects bins; binning is unchanged."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bins: list[dict] = []
        self.overlay_bins: list[dict] = []
        self.title = "Click interval distribution"
        self.target_beat_ms: float | None = None
        self.setMinimumHeight(220)

    def set_bins(
        self,
        bins: list[dict],
        *,
        title: str = "",
        overlay: list[dict] | None = None,
        target_beat_ms: float | None = None,
        configured_range: tuple[float, float] | None = None,
    ):
        self.bins = list(bins or [])
        self.overlay_bins = list(overlay or [])
        if title:
            self.title = title
        self.target_beat_ms = target_beat_ms
        self.configured_range = configured_range
        self.update()
        self._sync_x_scroll()

    def _min_spans(self) -> tuple[float, float]:
        return HIST_X_MIN_SPAN_MS, HIST_Y_MIN_SPAN

    def _bin_extents(self) -> tuple[list[float], list[float]]:
        xs: list[float] = []
        ys: list[float] = []
        for item in list(self.bins) + list(self.overlay_bins):
            lo = _finite_values([item.get("lo")])
            hi = _finite_values([item.get("hi")])
            count = _finite_values([item.get("count")])
            xs.extend(lo)
            xs.extend(hi)
            ys.extend(count)
        return xs, ys

    def autofit_bounds(self) -> tuple[float, float, float, float] | None:
        xs, ys = self._bin_extents()
        extras = _guide_anchors(self.target_beat_ms, self.configured_range)
        if not xs:
            return None
        ymax = max(ys) if ys else 1.0
        if self.data_aware_fit:
            xmin, xmax = fitted_range(xs, extra=extras, min_span=HIST_X_MIN_SPAN_MS)
            xmin, xmax = domain_axis_bounds(xmin, xmax, domain=DOMAIN_INTERVAL, values=xs)
            ymin, yhi = fitted_range([0.0, ymax], min_span=HIST_Y_MIN_SPAN)
            ymin, yhi = domain_axis_bounds(ymin, yhi, domain=DOMAIN_COUNT, values=ys)
            return xmin, xmax, ymin, yhi
        xmin = min(xs)
        xmax = max(xs)
        if xmax <= xmin:
            xmax = xmin + 1.0
        return xmin, xmax, 0.0, max(1.0, ymax * 1.15)

    def _classified(self) -> bool:
        return any(item.get("position") in (POSITION_BELOW, POSITION_WITHIN, POSITION_ABOVE) for item in self.bins)

    def bar_category(self, item: dict) -> str | None:
        """Configured-range category of a bin, or None when no comparison is configured."""
        if not self._classified():
            return None
        position = item.get("position")
        if position in (POSITION_BELOW, POSITION_ABOVE):
            return position
        return POSITION_WITHIN

    def bar_palette_key(self, item: dict) -> str:
        category = self.bar_category(item)
        if category is None:
            return "interval_fill"
        return HIST_CATEGORY_PALETTE_KEYS[category]

    def _bar_color(self, item: dict) -> str:
        return getattr(self.palette, self.bar_palette_key(item))

    def _bar_edge(self, item: dict) -> str:
        pal = self.palette
        if not self._classified():
            return pal.interval_line
        position = item.get("position")
        if position == POSITION_BELOW:
            return pal.chatter
        if position == POSITION_ABOVE:
            return pal.extra
        return pal.interval_line

    def legend_entries(self) -> list[tuple[str, str]]:
        pal = self.palette
        if self._classified():
            items = [
                (
                    getattr(pal, HIST_CATEGORY_PALETTE_KEYS[POSITION_BELOW]),
                    self._label("legend_below_configured_range", "Below configured interval range"),
                ),
                (
                    getattr(pal, HIST_CATEGORY_PALETTE_KEYS[POSITION_WITHIN]),
                    self._label("legend_within_configured_range", "Within configured interval range"),
                ),
                (
                    getattr(pal, HIST_CATEGORY_PALETTE_KEYS[POSITION_ABOVE]),
                    self._label("legend_above_configured_range", "Above configured interval range"),
                ),
            ]
            items.extend(self._range_legend_items())
        else:
            items = [(pal.interval_line, self._label("interval_distribution", "Click interval distribution"))]
            items.extend(self._range_legend_items())
        if self.overlay_bins:
            items.append((pal.overlay, self._label("legend_overlay", "Overlay (A)")))
        if self.target_beat_ms:
            items.append((pal.target_line, self._label("legend_configured_reference", "Reference interval")))
        return items

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette
        p.fillRect(self.rect(), QColor(pal.bg))
        plot = self._plot_rect()
        p.setPen(QColor(pal.text))
        p.setFont(chart_font("title", bold=True))
        p.drawText(12, 16, self.title)
        legend = self.legend_entries()
        self._draw_legend_box(p, plot, legend)
        if not self.bins:
            p.setPen(QColor(pal.muted))
            p.setFont(chart_font("placeholder"))
            p.drawText(plot, int(Qt.AlignmentFlag.AlignCenter), self._label("waiting_data", "Waiting for click data"))
            return
        bounds = self.visible_bounds()
        if bounds is None:
            return
        xmin, xmax, ymin, ymax = bounds
        dx = xmax - xmin
        dy = ymax - ymin
        if dx <= 0 or dy <= 0:
            return

        def map_x(v: float) -> float:
            return plot.left() + (v - xmin) / dx * plot.width()

        def map_y(v: float) -> float:
            return plot.bottom() - (v - ymin) / dy * plot.height()

        self._draw_axes(
            p,
            plot,
            x_ticks=nice_ticks(xmin, xmax),
            y_ticks=nice_ticks(ymin, ymax),
            x_label=self._label("axis_interval_ms", "Click interval (ms)"),
            y_label=self._label("axis_count", "Observation count"),
            map_x=map_x,
            map_y=map_y,
        )
        self._draw_vertical_range(p, plot, map_x)
        p.save()
        p.setClipRect(plot)
        bar_w = max(2.0, plot.width() / max(1, len(self.bins)) - 2)
        # drawRect fills with the current brush; the legend leaves its last swatch brush set.
        p.setBrush(Qt.BrushStyle.NoBrush)
        for item in self.bins:
            lo, hi = float(item["lo"]), float(item["hi"])
            count = int(item.get("count") or 0)
            x = map_x(lo)
            w = max(2.0, map_x(hi) - x - 1)
            y = map_y(count)
            p.fillRect(QRectF(x, y, min(w, bar_w), plot.bottom() - y), QColor(self._bar_color(item)))
            p.setPen(QPen(QColor(self._bar_edge(item)), 1))
            p.drawRect(QRectF(x, y, min(w, bar_w), plot.bottom() - y))
        if self.overlay_bins:
            color = QColor(pal.overlay)
            color.setAlpha(90)
            for item in self.overlay_bins:
                lo, hi = float(item["lo"]), float(item["hi"])
                count = int(item.get("count") or 0)
                x = map_x(lo) + 2
                w = max(2.0, map_x(hi) - map_x(lo) - 4)
                y = map_y(count)
                p.fillRect(QRectF(x, y, w, plot.bottom() - y), color)
        p.restore()
        if self.target_beat_ms:
            tx = map_x(self.target_beat_ms)
            p.setPen(QPen(QColor(pal.target_line), 1.5, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(tx, plot.top()), QPointF(tx, plot.bottom()))


class OccupancyBar(QWidget):
    """Aggregate occupancy strip from Host Evidence counts. No per-slot invention."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.empty = 0
        self.single = 0
        self.multi = 0
        self.setMinimumHeight(18)
        self.setMaximumHeight(22)
        self._apply_palette(LIGHT_PALETTE)

    def _apply_palette(self, pal: ChartPalette):
        self._empty = QColor(pal.grid)
        self._single = QColor(pal.on_cadence)
        self._multi = QColor(pal.extra)
        self._vacant = QColor(pal.grid)

    def set_theme(self, palette: ChartPalette, labels: dict[str, str] | None = None):
        self._apply_palette(palette)
        self.update()

    def set_counts(self, empty: int, single: int, multi: int):
        self.empty = max(0, int(empty))
        self.single = max(0, int(single))
        self.multi = max(0, int(multi))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 4, 0, -4)
        total = self.empty + self.single + self.multi
        if total <= 0:
            p.fillRect(rect, self._vacant)
            return
        x = float(rect.left())
        parts = (
            (self.empty, self._empty),
            (self.single, self._single),
            (self.multi, self._multi),
        )
        for count, color in parts:
            w = rect.width() * count / total
            p.fillRect(QRectF(x, rect.top(), max(0.0, w), rect.height()), color)
            x += w
