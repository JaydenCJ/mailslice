"""Run reports: per-label/per-year counters rendered as a table or JSON.

Both ``scan`` and ``split`` end with the same question — "what is in this
mbox and where did it go?" — so both build the same report structure. The
text renderer prints an aligned table for humans; ``to_json`` emits the full
numbers for scripts (sorted keys, stable field names).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

__all__ = ["SplitReport", "human_size"]

_UNITS = ("B", "KiB", "MiB", "GiB", "TiB")


def human_size(size: int) -> str:
    """Render a byte count the way ``ls -lh`` would (binary units)."""
    value = float(size)
    for unit in _UNITS:
        if value < 1024 or unit == _UNITS[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{int(size)} B"  # unreachable; keeps type checkers content


class SplitReport:
    """Counters for one run: buckets, totals, skips, malformed messages."""

    def __init__(self) -> None:
        # (label, year_display) -> [message count, byte count]
        self.buckets: Dict[Tuple[str, str], List[int]] = {}
        self.skipped: Dict[str, int] = {}
        self.messages = 0
        self.total_bytes = 0
        self.malformed = 0
        self.min_year: Optional[int] = None
        self.max_year: Optional[int] = None

    def add(self, label: str, year_display: str, size: int) -> None:
        bucket = self.buckets.setdefault((label, year_display), [0, 0])
        bucket[0] += 1
        bucket[1] += size

    def note_message(self, size: int, year: Optional[int], malformed: bool) -> None:
        self.messages += 1
        self.total_bytes += size
        if malformed:
            self.malformed += 1
        if year is not None:
            self.min_year = year if self.min_year is None else min(self.min_year, year)
            self.max_year = year if self.max_year is None else max(self.max_year, year)

    def note_skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    @property
    def skipped_total(self) -> int:
        return sum(self.skipped.values())

    @property
    def year_span(self) -> str:
        if self.min_year is None:
            return "-"
        if self.min_year == self.max_year:
            return str(self.min_year)
        return f"{self.min_year}-{self.max_year}"

    def render(self, bucket_header: str = "label/year") -> str:
        """Aligned three-column table plus a totals line."""
        rows = [
            (f"{label}/{year}", count, size)
            for (label, year), (count, size) in sorted(self.buckets.items())
        ]
        name_width = max([len(bucket_header)] + [len(r[0]) for r in rows])
        count_width = max([8] + [len(str(r[1])) for r in rows])
        lines = [f"{bucket_header:<{name_width}}  {'messages':>{count_width}}  size"]
        for name, count, size in rows:
            lines.append(
                f"{name:<{name_width}}  {count:>{count_width}}  {human_size(size)}"
            )
        noun = "message" if self.messages == 1 else "messages"
        summary = (
            f"total: {self.messages} {noun}, {human_size(self.total_bytes)}, "
            f"{self.malformed} malformed, {self.skipped_total} skipped"
        )
        lines.append(summary)
        return "\n".join(lines)

    def to_json(self) -> dict:
        """Machine-readable form of the whole report (stable field names)."""
        return {
            "messages": self.messages,
            "total_bytes": self.total_bytes,
            "malformed": self.malformed,
            "skipped": dict(sorted(self.skipped.items())),
            "skipped_total": self.skipped_total,
            "year_span": self.year_span,
            "buckets": [
                {
                    "label": label,
                    "year": year,
                    "messages": count,
                    "bytes": size,
                }
                for (label, year), (count, size) in sorted(self.buckets.items())
            ],
        }
