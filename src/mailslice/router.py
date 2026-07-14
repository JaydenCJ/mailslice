"""Routing: decide where each message lands, or why it is skipped.

The router is a pure function of (labels, year) — no I/O — so every policy
decision (grouping scheme, include/exclude filters, year range, one-folder-
per-message vs. duplicate-into-every-label) is unit-testable without touching
an mbox or the filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Iterable, List, Optional, Tuple

from .labels import UNLABELED, folder_labels, label_to_path, primary_label

__all__ = ["GROUP_CHOICES", "NO_DATE", "RouteConfig", "RouteResult", "Router"]

GROUP_CHOICES = ("label/year", "label", "year", "none")

NO_DATE = "no-date"


@dataclass(frozen=True)
class RouteConfig:
    """Immutable routing policy, built once from the CLI flags."""

    group_by: str = "label/year"
    include: FrozenSet[str] = frozenset()
    exclude: FrozenSet[str] = frozenset()
    since: Optional[int] = None
    until: Optional[int] = None
    all_labels: bool = False

    def __post_init__(self) -> None:
        if self.group_by not in GROUP_CHOICES:
            raise ValueError(
                f"group_by must be one of {GROUP_CHOICES}, got {self.group_by!r}"
            )


@dataclass
class RouteResult:
    """Where one message goes: destination dirs, or a skip reason."""

    # (display_label, year_display, relative_dir) triples; empty when skipped.
    destinations: List[Tuple[str, str, str]] = field(default_factory=list)
    skip_reason: Optional[str] = None

    @property
    def skipped(self) -> bool:
        return self.skip_reason is not None


def _matches(label: str, patterns: FrozenSet[str]) -> bool:
    """Case-insensitive match, hierarchical: ``work`` matches ``Work/Q3``."""
    lower = label.lower()
    for pattern in patterns:
        if lower == pattern or lower.startswith(pattern + "/"):
            return True
    return False


class Router:
    """Apply a :class:`RouteConfig` to one message's labels and year."""

    def __init__(self, config: RouteConfig):
        self.config = config

    def route(self, labels: Iterable[str], year: Optional[int]) -> RouteResult:
        labels = list(labels)
        cfg = self.config

        if cfg.exclude and any(_matches(l, cfg.exclude) for l in labels):
            return RouteResult(skip_reason="excluded label")
        if cfg.include and not any(_matches(l, cfg.include) for l in labels):
            return RouteResult(skip_reason="not in included labels")
        if cfg.since is not None and (year is None or year < cfg.since):
            return RouteResult(skip_reason="before --since")
        if cfg.until is not None and (year is None or year > cfg.until):
            return RouteResult(skip_reason="after --until")

        year_display = str(year) if year is not None else NO_DATE

        if cfg.all_labels:
            chosen = folder_labels(labels) or [UNLABELED]
        else:
            chosen = [primary_label(labels)]

        destinations: List[Tuple[str, str, str]] = []
        seen_dirs = set()
        for label in chosen:
            path = label_to_path(label)
            rel_dir = self._rel_dir(path, year_display)
            if rel_dir in seen_dirs:
                continue  # two labels sanitizing to the same directory
            seen_dirs.add(rel_dir)
            destinations.append((label, year_display, rel_dir))
        return RouteResult(destinations=destinations)

    def _rel_dir(self, label_path: str, year_display: str) -> str:
        group_by = self.config.group_by
        if group_by == "label/year":
            return f"{label_path}/{year_display}"
        if group_by == "label":
            return label_path
        if group_by == "year":
            return year_display
        return ""  # "none": everything into the output root
