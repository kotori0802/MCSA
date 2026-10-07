"""Presentation-only Click Data sort keys. Does not mutate canonical events."""
from __future__ import annotations

from typing import Any

# Canonical column ids. Visible labels are i18n; never use labels as machine keys.
CLICK_TABLE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("index", "col_index"),
    ("elapsed_ms", "col_elapsed"),
    ("button", "col_button"),
    ("interval_ms", "col_interval"),
    ("hold_ms", "col_hold"),
    ("state", "col_state"),
    ("tags", "col_tags"),
    ("reference_delta_ms", "col_ref_delta"),
)
CLICK_TABLE_COLUMN_IDS: tuple[str, ...] = tuple(column_id for column_id, _key in CLICK_TABLE_COLUMNS)
CLICK_TABLE_LABEL_KEYS: dict[str, str] = {column_id: key for column_id, key in CLICK_TABLE_COLUMNS}
CLICK_TABLE_ID_TO_INDEX: dict[str, int] = {column_id: index for index, column_id in enumerate(CLICK_TABLE_COLUMN_IDS)}
CLICK_TABLE_INDEX_TO_ID: dict[int, str] = {index: column_id for column_id, index in CLICK_TABLE_ID_TO_INDEX.items()}
CLICK_TABLE_NUMERIC_IDS = frozenset({"index", "elapsed_ms", "interval_ms", "hold_ms", "reference_delta_ms"})
CLICK_TABLE_NUMERIC_COLUMNS = frozenset(CLICK_TABLE_ID_TO_INDEX[column_id] for column_id in CLICK_TABLE_NUMERIC_IDS)
CLICK_TABLE_MEASUREMENT_VISIBLE_IDS: tuple[str, ...] = (
    "index",
    "elapsed_ms",
    "button",
    "interval_ms",
    "hold_ms",
    "reference_delta_ms",
)
SORT_VALUE_ROLE = 32  # Qt.ItemDataRole.UserRole
CANONICAL_ROW_ROLE = 33  # Qt.ItemDataRole.UserRole + 1


def is_blank_sort_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def sort_permutation(
    values: list[Any],
    *,
    descending: bool = False,
    numeric: bool = False,
    tie_breakers: list[int] | None = None,
) -> list[int]:
    """Return indices that sort `values` with blanks last in both directions.

    `descending` applies only to the primary value. Equal values always keep
    ascending `tie_breakers` (canonical) order, in both directions.
    """
    n = len(values)
    ties = list(tie_breakers) if tie_breakers is not None else list(range(n))
    if len(ties) != n:
        raise ValueError("tie_breakers length must match values")
    filled = sorted(
        (i for i in range(n) if not is_blank_sort_value(values[i])),
        key=lambda i: ties[i],
    )
    blanks = sorted(
        (i for i in range(n) if is_blank_sort_value(values[i])),
        key=lambda i: ties[i],
    )
    if numeric:
        filled.sort(key=lambda i: float(values[i]), reverse=descending)
    else:
        filled.sort(key=lambda i: str(values[i]).casefold(), reverse=descending)
    return filled + blanks
