"""Tests for DBSCAN clustering.

The feature-engineering and clustering tests run on synthetic in-memory
DataFrames, so they need no database and execute in CI. The integration test at
the bottom is skipped automatically when PostgreSQL isn't reachable.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from app.core.config import config
from app.processing.clustering import (
    build_windows,
    cluster,
    kdistance_curve,
    summarise_clusters,
)


def _synthetic_logs() -> pd.DataFrame:
    """Two dense bursts (one normal, one error-heavy) plus a quiet gap.

    Designed so windowing and clustering have something real to separate.
    """
    base = datetime(2005, 6, 3, 15, 0, 0)
    rows = []
    # Burst A: 0-2 min, INFO/KERNEL, no anomalies.
    for i in range(40):
        rows.append({
            "id": i,
            "log_timestamp": base + timedelta(seconds=i * 3),
            "component": "KERNEL",
            "level": "INFO",
            "message": "instruction cache parity error corrected",
            "is_anomaly": False,
            "template_id": 1,
        })
    # Burst B: 20-22 min, FATAL/APP, all anomalies, different template.
    b = base + timedelta(minutes=20)
    for i in range(30):
        rows.append({
            "id": 100 + i,
            "log_timestamp": b + timedelta(seconds=i * 4),
            "component": "APP",
            "level": "FATAL",
            "message": "rts panic stopping execution",
            "is_anomaly": True,
            "template_id": 2,
        })
    return pd.DataFrame(rows)


def test_build_windows_skips_empty_and_aligns_vectors() -> None:
    df = _synthetic_logs()
    X, metas, names = build_windows(df, window=timedelta(minutes=5))
    # Two populated 5-min windows; the empty gap windows are dropped.
    assert len(metas) == 2
    assert X.shape == (2, len(names))
    # Every window vector has the same length (aligned vocabularies).
    assert len({len(m.vector) for m in metas}) == 1


def test_window_features_are_computed_correctly() -> None:
    df = _synthetic_logs()
    _, metas, _ = build_windows(df, window=timedelta(minutes=5))
    first, second = metas[0], metas[1]
    # Burst A: no errors, no anomalies.
    assert first.error_rate == pytest.approx(0.0)
    assert first.anomaly_ratio == pytest.approx(0.0)
    assert first.log_count == 40
    # Burst B: all FATAL, all anomalies.
    assert second.error_rate == pytest.approx(1.0)
    assert second.anomaly_ratio == pytest.approx(1.0)
    assert second.log_count == 30


def test_anomaly_label_excluded_from_features_by_default() -> None:
    df = _synthetic_logs()
    _, _, names = build_windows(df, window=timedelta(minutes=5))
    assert "anomaly_ratio" not in names
    _, _, names_incl = build_windows(
        df, window=timedelta(minutes=5), include_anomaly_feature=True
    )
    assert "anomaly_ratio" in names_incl


def test_overlapping_stride_yields_more_windows() -> None:
    df = _synthetic_logs()
    tumbling, _, _ = build_windows(df, window=timedelta(minutes=5))
    overlapping, _, _ = build_windows(
        df, window=timedelta(minutes=5), stride=timedelta(minutes=1)
    )
    assert overlapping.shape[0] >= tumbling.shape[0]


def test_cluster_returns_label_per_row() -> None:
    # Two tight blobs far apart -> DBSCAN should find structure, not all noise.
    rng = np.random.default_rng(0)
    a = rng.normal(0.0, 0.05, size=(10, 4))
    b = rng.normal(5.0, 0.05, size=(10, 4))
    X = np.vstack([a, b])
    labels, x_used = cluster(X, eps=0.5, min_samples=3)
    assert labels.shape[0] == X.shape[0]
    assert x_used.shape[0] == X.shape[0]
    assert set(labels.tolist()) - {-1}  # at least one real cluster formed


def test_cluster_handles_empty_input() -> None:
    labels, x_used = cluster(np.empty((0, 0)))
    assert labels.shape[0] == 0
    assert x_used.shape[0] == 0


def test_kdistance_curve_is_sorted() -> None:
    rng = np.random.default_rng(1)
    X = rng.normal(size=(20, 4))
    curve = kdistance_curve(X, k=4)
    assert curve.shape[0] == 20
    assert np.all(np.diff(curve) >= 0)  # ascending, for the elbow plot


def test_summarise_clusters_reports_per_label_anomaly_ratio() -> None:
    df = _synthetic_logs()
    _, metas, _ = build_windows(df, window=timedelta(minutes=5))
    # Pretend each window landed in its own cluster.
    labels = np.array([0, 1])
    summary = summarise_clusters(metas, labels)
    assert set(summary.index.tolist()) == {0, 1}
    assert "mean_anomaly_ratio" in summary.columns


def _db_available() -> bool:
    try:
        engine = create_engine(config.postgres_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_available(), reason="PostgreSQL not reachable")
def test_log_windows_table_roundtrips() -> None:
    from app.processing.clustering import store_windows

    df = _synthetic_logs()
    _, metas, _ = build_windows(df, window=timedelta(minutes=5))
    labels = np.array([0, 1])
    engine = create_engine(config.postgres_url)
    stored = store_windows(engine, metas, labels, source_dataset="TEST")
    assert stored == len(metas)
    with engine.connect() as conn:
        n = conn.execute(
            text(
                "SELECT COUNT(*) FROM log_windows WHERE source_dataset = 'TEST'"
            )
        ).scalar()
    assert n == len(metas)
    # Clean up so the test is repeatable.
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM log_windows WHERE source_dataset = 'TEST'")
        )
