"""BGL log parser.

Parses Blue Gene/L log lines from the Loghub dataset into structured records.
Reference: Oliner & Stearley 2007 ("What Supercomputers Say").

This module is the only BGL-specific code in the project; everything
downstream (Drain, clustering, LSTM, RAG) treats logs as generic.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BglLogLine:
    """One parsed BGL log entry."""

    log_timestamp: datetime
    component: str
    level: str
    message: str
    is_anomaly: bool
    raw_label: str  # kept for debugging / category-level analysis later


# Expected minimum number of whitespace-separated fields before the message.
# BGL format: label epoch date node datetime node_repeat type component level msg...
_MIN_FIELDS_BEFORE_MESSAGE = 9


def parse_line(raw: str) -> BglLogLine | None:
    """Parse one BGL log line. Returns None for malformed lines.

    Returning None rather than raising lets the caller decide how to handle
    bad data (skip vs. fail) without paying the cost of an exception per line.
    """
    raw = raw.rstrip("\n")
    if not raw:
        return None

    parts = raw.split(maxsplit=_MIN_FIELDS_BEFORE_MESSAGE - 1)
    if len(parts) < _MIN_FIELDS_BEFORE_MESSAGE:
        return None

    label, _epoch, _date, _node, dt_str, _node2, _type, component, rest = parts

    # The 'rest' field contains "LEVEL message text here"
    level, _, message = rest.partition(" ")
    if not message:
        # No message body — treat as malformed.
        return None

    try:
        # BGL datetime format: 2005-06-03-15.42.50.675872
        log_ts = datetime.strptime(dt_str, "%Y-%m-%d-%H.%M.%S.%f")
    except ValueError:
        return None

    return BglLogLine(
        log_timestamp=log_ts,
        component=component,
        level=level,
        message=message,
        is_anomaly=(label != "-"),
        raw_label=label,
    )


def parse_file(path: Path) -> Iterator[BglLogLine]:
    """Stream-parse a BGL log file, yielding one BglLogLine per valid row.

    Uses a generator so a 700MB full BGL file doesn't have to fit in memory.
    Malformed lines are counted and reported once at the end.
    """
    parsed = 0
    skipped = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            entry = parse_line(line)
            if entry is None:
                skipped += 1
                continue
            parsed += 1
            yield entry
    log.info("parsed %d lines, skipped %d malformed", parsed, skipped)