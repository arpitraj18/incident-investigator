"""DBSCAN clustering of BGL logs into recurring incident patterns.

Day 4-5 of the pipeline. The Drain step (template_extractor) turned ~2000 raw
lines into ~150 templates. This module groups *time windows* of activity into
clusters, where each cluster is a recurring "shape" of system behaviour: a
window with a particular mix of templates, components, and error volume.
Windows that don't resemble any cluster come back as noise (label -1), which is
exactly where one-off incidents tend to live.

Design notes
------------
* We cluster WINDOWS, not individual rows. A window is described by a feature
  vector (volume, error rate, burst rate, component mix, template mix). DBSCAN
  then finds groups of similar windows.
* DBSCAN (not KMeans): we don't know the number of incident patterns up front,
  the clusters aren't spherical, and we want a first-class "noise" label for
  outliers. Those three properties are the whole reason to prefer it here.
* The ground-truth ``is_anomaly`` label is deliberately kept OUT of the feature
  matrix (see ``include_anomaly_feature``). If you cluster on the label you
  can't then claim the clusters "discovered" the anomalies, since that is
  circular. Instead we record each cluster's anomaly ratio afterwards, as an
  honest measure of whether unsupervised structure lines up with the labels.
* ``raw_logs`` has no ``template_id`` column, so we re-derive templates here by
  replaying messages through Drain in chronological order. Drain is order-
  sensitive, but a fixed read order makes this reproducible within a run.

This module is dataset-agnostic: it reads whatever is in ``raw_logs``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.decomposition import PCA
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from sqlalchemy import create_engine, delete, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import config
from app.db.models import LogWindow

log = logging.getLogger(__name__)

# Log levels we treat as "errors" for the error-rate feature. BGL emits these
# in upper case; we normalise before comparing.
_ERROR_LEVELS = frozenset({"ERROR", "FATAL", "SEVERE", "FAILURE"})

# Default 5-minute tumbling windows (see build_windows for the stride trade-off).
DEFAULT_WINDOW = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class WindowFeatures:
    """Aggregated features and descriptors for one time window."""

    window_start: datetime
    window_end: datetime
    log_count: int
    error_rate: float
    burst_rate: float  # logs per second
    anomaly_ratio: float  # descriptor only; not a clustering feature by default
    distinct_templates: int
    distinct_components: int
    vector: np.ndarray = field(repr=False)  # the actual clustering features


def fetch_logs(engine: Engine, source_dataset: str | None = None) -> pd.DataFrame:
    """Read ``raw_logs`` into a DataFrame, ordered by time then id.

    Ordering by ``(log_timestamp, id)`` gives a stable chronological stream and
    keeps the downstream Drain replay reproducible.
    """
    where = ""
    params: dict[str, object] = {}
    if source_dataset is not None:
        where = "WHERE source_dataset = :ds"
        params["ds"] = source_dataset
    query = text(
        f"""
        SELECT id, log_timestamp, component, level, message, is_anomaly
        FROM raw_logs
        {where}
        ORDER BY log_timestamp NULLS LAST, id
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params=params)
    df["log_timestamp"] = pd.to_datetime(df["log_timestamp"])
    return df


def assign_templates(df: pd.DataFrame) -> pd.DataFrame:
    """Attach a ``template_id`` to each row by replaying Drain in row order.

    ``raw_logs`` doesn't persist the per-row template, so we reconstruct it. We
    feed messages in the DataFrame's existing (chronological) order so template
    ids are deterministic for a given run. Imported lazily so the rest of this
    module, and its unit tests, don't depend on drain3.
    """
    from app.processing.template_extractor import TemplateExtractor

    extractor = TemplateExtractor()
    ids = [extractor.add_log(msg).template_id for msg in df["message"]]
    out = df.copy()
    out["template_id"] = ids
    return out


def build_windows(
    df: pd.DataFrame,
    window: timedelta = DEFAULT_WINDOW,
    stride: timedelta | None = None,
    include_anomaly_feature: bool = False,
) -> tuple[np.ndarray, list[WindowFeatures], list[str]]:
    """Slice logs into time windows and build a feature vector per window.

    ``stride`` defaults to ``window`` (tumbling, non-overlapping windows). Use a
    smaller stride for overlapping windows when you need more samples, at the
    cost of adjacent windows being correlated.

    Empty windows are skipped. Requires a ``template_id`` column (run
    ``assign_templates`` first). Returns ``(X, metas, feature_names)`` where
    ``X`` is the ``[n_windows, n_features]`` matrix fed to DBSCAN.
    """
    if df.empty:
        return np.empty((0, 0)), [], []
    if "template_id" not in df.columns:
        raise ValueError("df needs a 'template_id' column; run assign_templates")
    if stride is None:
        stride = window

    df = df.dropna(subset=["log_timestamp"]).sort_values("log_timestamp")
    if df.empty:
        return np.empty((0, 0)), [], []

    # Fixed, sorted vocabularies so every window's vector lines up column-wise.
    components = sorted(df["component"].dropna().unique().tolist())
    templates = sorted(df["template_id"].unique().tolist())
    comp_index = {c: i for i, c in enumerate(components)}
    tmpl_index = {t: i for i, t in enumerate(templates)}

    ts = df["log_timestamp"].to_numpy()
    comp = df["component"].fillna("").to_numpy()
    lvl = df["level"].fillna("").str.upper().to_numpy()
    anom = df["is_anomaly"].astype(bool).to_numpy()
    tid = df["template_id"].to_numpy()

    t0 = df["log_timestamp"].min().to_pydatetime()
    t_end = df["log_timestamp"].max().to_pydatetime()
    win_secs = window.total_seconds()

    metas: list[WindowFeatures] = []
    vectors: list[np.ndarray] = []

    start = t0
    while start <= t_end:
        end = start + window
        mask = (ts >= np.datetime64(start)) & (ts < np.datetime64(end))
        n = int(mask.sum())
        if n == 0:
            start += stride
            continue

        w_comp = comp[mask]
        w_lvl = lvl[mask]
        w_tid = tid[mask]
        w_anom = anom[mask]

        comp_freq = np.zeros(len(components))
        for c in w_comp:
            j = comp_index.get(c)
            if j is not None:
                comp_freq[j] += 1
        comp_freq /= n

        tmpl_freq = np.zeros(len(templates))
        for t in w_tid:
            tmpl_freq[tmpl_index[t]] += 1
        tmpl_freq /= n

        error_rate = float(np.isin(w_lvl, list(_ERROR_LEVELS)).mean())
        burst_rate = n / win_secs if win_secs else 0.0
        anomaly_ratio = float(w_anom.mean())
        distinct_templates = int(len(set(w_tid.tolist())))
        distinct_components = int(len({c for c in w_comp.tolist() if c}))

        scalars = [
            float(n),
            error_rate,
            burst_rate,
            float(distinct_templates),
            float(distinct_components),
        ]
        if include_anomaly_feature:
            scalars.append(anomaly_ratio)
        vector = np.concatenate([np.array(scalars), comp_freq, tmpl_freq])

        metas.append(
            WindowFeatures(
                window_start=start,
                window_end=end,
                log_count=n,
                error_rate=error_rate,
                burst_rate=burst_rate,
                anomaly_ratio=anomaly_ratio,
                distinct_templates=distinct_templates,
                distinct_components=distinct_components,
                vector=vector,
            )
        )
        vectors.append(vector)
        start += stride

    names = ["log_count", "error_rate", "burst_rate",
             "distinct_templates", "distinct_components"]
    if include_anomaly_feature:
        names.append("anomaly_ratio")
    names += [f"comp::{c}" for c in components]
    names += [f"tmpl::{t}" for t in templates]

    X = np.vstack(vectors) if vectors else np.empty((0, len(names)))
    return X, metas, names


def kdistance_curve(X: np.ndarray, k: int = 4) -> np.ndarray:
    """Sorted distance to the k-th nearest neighbour, for choosing DBSCAN eps.

    The standard heuristic: plot this curve and look for the "elbow", i.e. the
    eps at which distance starts climbing sharply; ``min_samples`` is then
    usually set to the same ``k``. Operates on standardised features, matching
    ``cluster``. Returns distances in ascending order (empty if too few rows).
    """
    if X.shape[0] <= k:
        return np.array([])
    x = StandardScaler().fit_transform(X)
    nn = NearestNeighbors(n_neighbors=k).fit(x)
    dists, _ = nn.kneighbors(x)
    return np.sort(dists[:, -1])


def cluster(
    X: np.ndarray,
    eps: float = 1.5,
    min_samples: int = 3,
    pca_components: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Standardise features and run DBSCAN. Returns ``(labels, X_used)``.

    Standardisation matters: raw counts (log_count) and rates (0-1) live on
    very different scales, and DBSCAN's eps is one distance threshold across all
    dimensions. Without scaling, log_count alone would dominate.

    Optional PCA reduces the sparse, high-dimensional template-frequency block
    before clustering. With ~150 template columns and only a few dozen windows,
    Euclidean distances get unreliable (curse of dimensionality); projecting to
    a handful of components often helps. Note that PCA changes the distance
    scale, so re-derive eps from ``kdistance_curve`` on the reduced space.

    Returns DBSCAN labels (-1 = noise) and the matrix actually clustered.
    """
    if X.shape[0] == 0:
        return np.empty(0, dtype=int), X
    x = StandardScaler().fit_transform(X)
    if pca_components is not None and pca_components < x.shape[1]:
        n = min(pca_components, x.shape[0])  # can't exceed n_samples
        x = PCA(n_components=n, random_state=0).fit_transform(x)
    labels = DBSCAN(eps=eps, min_samples=min_samples).fit_predict(x)
    return labels, x


def summarise_clusters(
    metas: list[WindowFeatures], labels: np.ndarray
) -> pd.DataFrame:
    """Per-cluster descriptors: size, mean anomaly ratio, error rate, span.

    This is the honesty check. If a cluster's ``anomaly_ratio`` is well above
    the global ~7% while another sits near zero, then the unsupervised structure
    is tracking something real, without the label ever entering the features.
    """
    if not metas:
        return pd.DataFrame()
    rows = []
    for m, lab in zip(metas, labels):
        rows.append(
            {
                "cluster_label": int(lab),
                "anomaly_ratio": m.anomaly_ratio,
                "error_rate": m.error_rate,
                "log_count": m.log_count,
                "window_start": m.window_start,
            }
        )
    df = pd.DataFrame(rows)
    out = (
        df.groupby("cluster_label")
        .agg(
            windows=("cluster_label", "size"),
            mean_anomaly_ratio=("anomaly_ratio", "mean"),
            mean_error_rate=("error_rate", "mean"),
            total_logs=("log_count", "sum"),
            first_window=("window_start", "min"),
            last_window=("window_start", "max"),
        )
        .sort_values("mean_anomaly_ratio", ascending=False)
    )
    return out


def store_windows(
    engine: Engine,
    metas: list[WindowFeatures],
    labels: np.ndarray,
    source_dataset: str = "BGL",
) -> int:
    """Persist window-level cluster assignments. Idempotent per dataset.

    Creates the ``log_windows`` table if needed, deletes any prior rows for this
    dataset, then bulk-inserts. Re-running refreshes rather than duplicating,
    unlike the initial loader which is intentionally one-shot.

    We store windows in their own table (not a column on ``raw_logs``) because
    clustering is at window granularity and overlapping windows would make a
    per-row label ambiguous. ``raw_logs`` stays an append-only ingestion record.
    """
    LogWindow.__table__.create(bind=engine, checkfirst=True)
    objs = [
        LogWindow(
            window_start=m.window_start,
            window_end=m.window_end,
            log_count=m.log_count,
            error_rate=m.error_rate,
            burst_rate=m.burst_rate,
            anomaly_ratio=m.anomaly_ratio,
            distinct_templates=m.distinct_templates,
            distinct_components=m.distinct_components,
            cluster_label=int(lab),
            source_dataset=source_dataset,
        )
        for m, lab in zip(metas, labels)
    ]
    with Session(engine) as session:
        session.execute(
            delete(LogWindow).where(LogWindow.source_dataset == source_dataset)
        )
        session.add_all(objs)
        session.commit()
    return len(objs)


def plot_clusters(
    X_used: np.ndarray,
    labels: np.ndarray,
    out_path: str = "data/processed/clusters.html",
) -> str | None:
    """2-D PCA scatter of the clustered windows, coloured by cluster.

    Uses plotly (already a project dependency) and writes a self-contained HTML
    file, so no kaleido/matplotlib needed. Returns the path, or None if there's
    nothing to plot. Purely diagnostic; not imported by tests.
    """
    if X_used.shape[0] < 2 or X_used.shape[1] < 1:
        return None
    import plotly.express as px

    if X_used.shape[1] >= 2:
        coords = PCA(n_components=2, random_state=0).fit_transform(X_used)
    else:
        coords = np.column_stack([X_used[:, 0], np.zeros(X_used.shape[0])])

    plot_df = pd.DataFrame(
        {
            "pc1": coords[:, 0],
            "pc2": coords[:, 1],
            "cluster": [str(int(v)) for v in labels],
        }
    )
    fig = px.scatter(
        plot_df,
        x="pc1",
        y="pc2",
        color="cluster",
        title="DBSCAN clusters of log windows (2-D PCA projection)",
        labels={"cluster": "cluster (-1 = noise)"},
    )
    fig.update_traces(marker={"size": 10, "line": {"width": 1}})
    fig.write_html(out_path)
    log.info("wrote cluster scatter to %s", out_path)
    return out_path


def run_clustering(
    source_dataset: str = "BGL",
    window: timedelta = DEFAULT_WINDOW,
    stride: timedelta | None = None,
    eps: float = 1.5,
    min_samples: int = 3,
    pca_components: int | None = None,
    make_plot: bool = True,
) -> dict:
    """End-to-end: read logs, build windows, cluster, store, and plot.

    Returns a summary dict. This is what scripts/run_clustering.py calls.
    """
    engine = create_engine(config.postgres_url)
    df = fetch_logs(engine, source_dataset)
    if df.empty:
        log.warning("no rows in raw_logs for dataset=%s", source_dataset)
        return {"windows": 0, "clusters": 0, "noise": 0, "stored": 0}

    span = df["log_timestamp"].max() - df["log_timestamp"].min()
    log.info("read %d rows spanning %s", len(df), span)

    df = assign_templates(df)
    X, metas, names = build_windows(df, window=window, stride=stride)
    n_feat = X.shape[1] if X.size else 0
    log.info("built %d non-empty windows, %d features each", len(metas), n_feat)
    if 0 < len(metas) < 8:
        log.warning(
            "only %d windows; DBSCAN needs more samples to be meaningful. Try a "
            "smaller --window or a stride < window.",
            len(metas),
        )

    labels, X_used = cluster(
        X, eps=eps, min_samples=min_samples, pca_components=pca_components
    )
    n_clusters = len(set(labels.tolist()) - {-1})
    n_noise = int((labels == -1).sum())

    stored = store_windows(engine, metas, labels, source_dataset)
    plot_path = plot_clusters(X_used, labels) if make_plot else None
    summary = summarise_clusters(metas, labels)

    log.info("clusters=%d noise=%d stored=%d", n_clusters, n_noise, stored)
    return {
        "windows": len(metas),
        "clusters": n_clusters,
        "noise": n_noise,
        "stored": stored,
        "plot": plot_path,
        "cluster_summary": summary.to_dict(orient="index"),
    }
