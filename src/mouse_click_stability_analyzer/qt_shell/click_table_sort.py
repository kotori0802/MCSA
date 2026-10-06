"""Presentation-only Click Data sort keys. Does not mutate canonical events."""
from __future__ import annotations

from typing import Any


CLICK_TABLE_NUMERIC_COLUMNS = frozenset({0, 1, 3, 4, 7})
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

    Equal values keep canonical order via `tie_breakers` (stable vs original rows).
    """
    n = len(values)
    ties = list(tie_breakers) if tie_breakers is not None else list(range(n))
    if len(ties) != n:
        raise ValueError("tie_breakers length must match values")
    filled = [i for i in range(n) if not is_blank_sort_value(values[i])]
    blanks = [i for i in range(n) if is_blank_sort_value(values[i])]
    if numeric:
        filled.sort(key=lambda i: (float(values[i]), ties[i]), reverse=descending)
    else:
        filled.sort(key=lambda i: (str(values[i]).casefold(), ties[i]), reverse=descending)
    blanks.sort(key=lambda i: ties[i])
    return filled + blanks
