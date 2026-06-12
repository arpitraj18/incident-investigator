"""Tests for BGL parser."""
from datetime import datetime
from pathlib import Path

from app.ingestion.bgl_parser import BglLogLine, parse_file, parse_line


def test_parse_normal_line() -> None:
    raw = (
        "- 1117838570 2005.06.03 R02-M1-N0-C:J12-U11 "
        "2005-06-03-15.42.50.675872 R02-M1-N0-C:J12-U11 RAS KERNEL "
        "INFO instruction cache parity error corrected"
    )
    entry = parse_line(raw)
    assert entry is not None
    assert entry.is_anomaly is False
    assert entry.raw_label == "-"
    assert entry.component == "KERNEL"
    assert entry.level == "INFO"
    assert "instruction cache parity error" in entry.message
    assert entry.log_timestamp == datetime(2005, 6, 3, 15, 42, 50, 675872)


def test_parse_anomaly_line() -> None:
    # Anomaly lines start with a non-dash label like KERNDTLB
    raw = (
        "KERNDTLB 1117899444 2005.06.04 R23-M1-N4-C:J05-U01 "
        "2005-06-04-08.37.24.123456 R23-M1-N4-C:J05-U01 RAS KERNEL "
        "FATAL data TLB error interrupt"
    )
    entry = parse_line(raw)
    assert entry is not None
    assert entry.is_anomaly is True
    assert entry.raw_label == "KERNDTLB"
    assert entry.level == "FATAL"


def test_parse_malformed_returns_none() -> None:
    assert parse_line("") is None
    assert parse_line("not enough fields") is None
    assert parse_line("- bad timestamp here field field field field field msg") is None


def test_parse_file_on_real_sample() -> None:
    """End-to-end: parse the actual downloaded BGL sample."""
    sample = Path(__file__).parent.parent / "data" / "samples" / "BGL_2k.log"
    if not sample.exists():
        return  # Skip if data not downloaded yet

    entries = list(parse_file(sample))
    assert len(entries) > 1900, f"Expected ~2000 valid lines, got {len(entries)}"
    assert all(isinstance(e, BglLogLine) for e in entries)
    # The sample should have a mix of anomaly and normal lines.
    anomalies = sum(1 for e in entries if e.is_anomaly)
    assert 0 < anomalies < len(entries), "Sample should have both kinds"