"""QPainter charts with axes, legends, and overlay support."""
from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPainterPath
from PySide6.QtWidgets import QWidget

from .styles import ChartPalette, LIGHT_PALETTE


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


class _ChartBase(QWidget):
    TITLE_H = 22
    LEGEND_H = 28
    TOP_PAD = 8
    LEFT = 58
    RIGHT = 16
    BOTTOM = 52

    def __init__(self, parent=None):
        super().__init__(parent)
        self.palette: ChartPalette = LIGHT_PALETTE
        self.labels: dict[str, str] = {}
        self.setMinimumHeight(200)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    def set_theme(self, palette: ChartPalette, labels: dict[str, str] | None = None):
        self.palette = palette
        if labels:
            self.labels = labels
        self.update()

    def _label(self, key: str, fallback: str) -> str:
        return self.labels.get(key) or fallback

    def _plot_top(self) -> float:
        return self.TOP_PAD + self.TITLE_H + self.LEGEND_H + 10

    def _legend_y(self) -> int:
        return int(self.TOP_PAD + self.TITLE_H + 4)

    def _plot_rect(self) -> QRectF:
        top = self._plot_top()
        return QRectF(
            self.LEFT,
            top,
            max(1, self.width() - self.LEFT - self.RIGHT),
            max(1, self.height() - top - self.BOTTOM),
        )

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

        tick_font = QFont("Segoe UI", 8)
        p.setFont(tick_font)
        p.setPen(QColor(pal.muted))
        fm = p.fontMetrics()
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
                _fmt_tick(yt),
            )
        for xt in x_ticks:
            x = map_x(xt)
            if x < plot.left() - 2 or x > plot.right() + 2:
                continue
            text = _fmt_tick(xt)
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
        font = QFont("Segoe UI", 8)
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
        self.points: list[tuple[float, float, str]] = []
        self.overlay_points: list[tuple[float, float, str]] = []
        self.title = "Hold vs Interval"
        self.target_beat_ms: float | None = None
        self.setMinimumHeight(260)

    def set_points(
        self,
        points: list[tuple[float, float, str]],
        *,
        title: str = "",
        overlay: list[tuple[float, float, str]] | None = None,
        target_beat_ms: float | None = None,
    ):
        self.points = list(points or [])
        self.overlay_points = list(overlay or [])
        if title:
            self.title = title
        self.target_beat_ms = target_beat_ms
        self.update()

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

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette
        p.fillRect(self.rect(), QColor(pal.bg))
        plot = self._plot_rect()

        p.setPen(QColor(pal.text))
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        p.drawText(12, 16, self.title)

        legend = [
            (pal.on_cadence, self._label("legend_on_cadence", "On cadence")),
            (pal.extra, self._label("legend_extra", "Extra / double")),
            (pal.chatter, self._label("legend_chatter", "Chatter")),
            (pal.miss, self._label("legend_miss", "Miss / slow")),
        ]
        if self.overlay_points:
            legend.append((pal.overlay, self._label("legend_overlay", "Overlay (A)")))
        if self.target_beat_ms:
            legend.append((pal.target_line, self._label("legend_target", "Target beat")))
        self._draw_legend_box(p, plot, legend)

        if not self.points and not self.overlay_points:
            p.setPen(QColor(pal.muted))
            p.setFont(QFont("Segoe UI", 11))
            p.drawText(plot, int(Qt.AlignmentFlag.AlignCenter), self._label("waiting_data", "Waiting for click data"))
            return

        all_x = [a[0] for a in self.points] + [a[0] for a in self.overlay_points]
        all_y = [a[1] for a in self.points] + [a[1] for a in self.overlay_points]
        xmin, xmax = 0.0, max(50.0, max(all_x) * 1.08)
        ymin, ymax = 0.0, max(15.0, max(all_y) * 1.15)
        if self.target_beat_ms:
            xmax = max(xmax, self.target_beat_ms * 1.35)

        def map_x(v: float) -> float:
            return plot.left() + (v - xmin) / (xmax - xmin) * plot.width()

        def map_y(v: float) -> float:
            return plot.bottom() - (v - ymin) / (ymax - ymin) * plot.height()

        self._draw_axes(
            p,
            plot,
            x_ticks=nice_ticks(xmin, xmax),
            y_ticks=nice_ticks(ymin, ymax),
            x_label=self._label("axis_interval_ms", "Interval (ms)"),
            y_label=self._label("axis_hold_ms", "Hold (ms)"),
            map_x=map_x,
            map_y=map_y,
        )

        if self.target_beat_ms:
            tx = map_x(self.target_beat_ms)
            p.setPen(QPen(QColor(pal.target_line), 1.5, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(tx, plot.top()), QPointF(tx, plot.bottom()))

        for x, y, _cls in self.overlay_points[-2500:]:
            c = QColor(pal.overlay)
            c.setAlpha(90)
            p.setBrush(QBrush(c))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(map_x(x), map_y(y)), 2.8, 2.8)

        for x, y, cls in self.points[-2500:]:
            p.setBrush(QBrush(QColor(self._class_color(cls))))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(map_x(x), map_y(y)), 3.4, 3.4)


class IntervalChart(_ChartBase):
    """Interval over elapsed time."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series: list[tuple[float, float]] = []
        self.overlay_series: list[tuple[float, float]] = []
        self.title = "Interval over time"
        self.target_beat_ms: float | None = None
        self.setMinimumHeight(220)

    def set_series(
        self,
        series: list[tuple[float, float]],
        *,
        title: str = "",
        overlay: list[tuple[float, float]] | None = None,
        target_beat_ms: float | None = None,
    ):
        self.series = list(series or [])
        self.overlay_series = list(overlay or [])
        if title:
            self.title = title
        self.target_beat_ms = target_beat_ms
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette
        p.fillRect(self.rect(), QColor(pal.bg))
        plot = self._plot_rect()

        p.setPen(QColor(pal.text))
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        p.drawText(12, 16, self.title)

        legend = [(pal.interval_line, self._label("chart_interval", "Interval over time"))]
        if self.overlay_series:
            legend.append((pal.overlay, self._label("legend_overlay", "Overlay (A)")))
        if self.target_beat_ms:
            legend.append((pal.target_line, self._label("legend_target", "Target beat")))
        self._draw_legend_box(p, plot, legend)

        if len(self.series) < 2 and len(self.overlay_series) < 2:
            p.setPen(QColor(pal.muted))
            p.setFont(QFont("Segoe UI", 11))
            p.drawText(plot, int(Qt.AlignmentFlag.AlignCenter), self._label("chart_interval", "Interval over time"))
            return

        all_pts = list(self.series) + list(self.overlay_series)
        xs = [a[0] for a in all_pts]
        ys = [a[1] for a in all_pts]
        xmin_ms, xmax_ms = min(xs), max(xs)
        if xmax_ms <= xmin_ms:
            xmax_ms = xmin_ms + 1
        xmin_s, xmax_s = xmin_ms / 1000.0, xmax_ms / 1000.0
        ymin, ymax = 0.0, max(40.0, max(ys) * 1.12)
        if self.target_beat_ms:
            ymax = max(ymax, self.target_beat_ms * 1.25)

        def map_x_ms(v_ms: float) -> float:
            return plot.left() + (v_ms - xmin_ms) / (xmax_ms - xmin_ms) * plot.width()

        def map_x_s(v_s: float) -> float:
            return map_x_ms(v_s * 1000.0)

        def map_y(v: float) -> float:
            return plot.bottom() - (v - ymin) / (ymax - ymin) * plot.height()

        self._draw_axes(
            p,
            plot,
            x_ticks=nice_ticks(xmin_s, xmax_s),
            y_ticks=nice_ticks(ymin, ymax),
            x_label=self._label("axis_elapsed_s", "Elapsed (s)"),
            y_label=self._label("axis_interval_ms", "Interval (ms)"),
            map_x=map_x_s,
            map_y=map_y,
        )

        if self.target_beat_ms:
            ty = map_y(self.target_beat_ms)
            p.setPen(QPen(QColor(pal.target_line), 1.2, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(plot.left(), ty), QPointF(plot.right(), ty))

        if len(self.overlay_series) >= 2:
            p.setPen(QPen(QColor(pal.overlay), 1.5, Qt.PenStyle.DashLine))
            prev = None
            for x, y in self.overlay_series[-2500:]:
                pt = QPointF(map_x_ms(x), map_y(y))
                if prev is not None:
                    p.drawLine(prev, pt)
                prev = pt

        if len(self.series) >= 2:
            path = QPainterPath()
            first = True
            for x, y in self.series[-2500:]:
                pt = QPointF(map_x_ms(x), map_y(y))
                if first:
                    path.moveTo(pt)
                    first = False
                else:
                    path.lineTo(pt)
            fill = QPainterPath(path)
            fill.lineTo(QPointF(map_x_ms(self.series[-1][0]), plot.bottom()))
            fill.lineTo(QPointF(map_x_ms(self.series[0][0]), plot.bottom()))
            fill.closeSubpath()
            p.fillPath(fill, QColor(pal.interval_fill))
            p.setPen(QPen(QColor(pal.interval_line), 2))
            p.drawPath(path)


class HistogramChart(_ChartBase):
    """Static interval distribution histogram."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bins: list[dict] = []
        self.overlay_bins: list[dict] = []
        self.title = "Interval distribution"
        self.target_beat_ms: float | None = None
        self.setMinimumHeight(220)

    def set_bins(
        self,
        bins: list[dict],
        *,
        title: str = "",
        overlay: list[dict] | None = None,
        target_beat_ms: float | None = None,
    ):
        self.bins = list(bins or [])
        self.overlay_bins = list(overlay or [])
        if title:
            self.title = title
        self.target_beat_ms = target_beat_ms
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette
        p.fillRect(self.rect(), QColor(pal.bg))
        plot = self._plot_rect()
        p.setPen(QColor(pal.text))
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        p.drawText(12, 16, self.title)
        legend = [(pal.interval_line, self._label("interval_distribution", "Interval distribution"))]
        if self.overlay_bins:
            legend.append((pal.overlay, self._label("legend_overlay", "Overlay (A)")))
        if self.target_beat_ms:
            legend.append((pal.target_line, self._label("legend_configured_reference", "Configured reference")))
        self._draw_legend_box(p, plot, legend)
        if not self.bins:
            p.setPen(QColor(pal.muted))
            p.setFont(QFont("Segoe UI", 11))
            p.drawText(plot, int(Qt.AlignmentFlag.AlignCenter), self._label("waiting_data", "Waiting for click data"))
            return
        xmin = float(self.bins[0]["lo"])
        xmax = float(self.bins[-1]["hi"])
        if xmax <= xmin:
            xmax = xmin + 1.0
        ymax = max(1.0, max(int(b.get("count") or 0) for b in self.bins) * 1.15)
        if self.overlay_bins:
            ymax = max(ymax, max(int(b.get("count") or 0) for b in self.overlay_bins) * 1.15)

        def map_x(v: float) -> float:
            return plot.left() + (v - xmin) / (xmax - xmin) * plot.width()

        def map_y(v: float) -> float:
            return plot.bottom() - (v / ymax) * plot.height()

        self._draw_axes(
            p,
            plot,
            x_ticks=nice_ticks(xmin, xmax),
            y_ticks=nice_ticks(0.0, ymax),
            x_label=self._label("axis_interval_ms", "Interval (ms)"),
            y_label=self._label("clicks", "Clicks"),
            map_x=map_x,
            map_y=map_y,
        )
        if self.target_beat_ms:
            tx = map_x(self.target_beat_ms)
            p.setPen(QPen(QColor(pal.target_line), 1.5, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(tx, plot.top()), QPointF(tx, plot.bottom()))
        bar_w = max(2.0, plot.width() / max(1, len(self.bins)) - 2)
        for item in self.bins:
            lo, hi = float(item["lo"]), float(item["hi"])
            count = int(item.get("count") or 0)
            x = map_x(lo)
            w = max(2.0, map_x(hi) - x - 1)
            y = map_y(count)
            p.fillRect(QRectF(x, y, min(w, bar_w), plot.bottom() - y), QColor(pal.interval_fill))
            p.setPen(QPen(QColor(pal.interval_line), 1))
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
