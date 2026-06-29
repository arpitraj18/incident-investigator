"""Run DBSCAN clustering over the logs already loaded in PostgreSQL.

Usage:
    python scripts/run_clustering.py
    python scripts/run_clustering.py --window-min 2 --eps 1.2 --min-samples 4
    python scripts/run_clustering.py --kdist          # just print the eps hint

The --kdist flag prints the k-distance curve so you can pick eps from the elbow
before committing to a clustering run.
"""
import argparse
import logging
from datetime import timedelta

from app.core.config import config
from app.processing.clustering import (
    assign_templates,
    build_windows,
    fetch_logs,
    kdistance_curve,
    run_clustering,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DBSCAN clustering of log windows")
    p.add_argument("--dataset", default="BGL", help="source_dataset to cluster")
    p.add_argument("--window-min", type=float, default=5.0,
                   help="window size in minutes (default 5)")
    p.add_argument("--stride-min", type=float, default=None,
                   help="stride in minutes; default = window (tumbling)")
    p.add_argument("--eps", type=float, default=1.5, help="DBSCAN eps")
    p.add_argument("--min-samples", type=int, default=3, help="DBSCAN min_samples")
    p.add_argument("--pca", type=int, default=None,
                   help="reduce to N PCA components before clustering")
    p.add_argument("--no-plot", action="store_true", help="skip the HTML scatter")
    p.add_argument("--kdist", action="store_true",
                   help="print the k-distance curve (to choose eps) and exit")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    window = timedelta(minutes=args.window_min)
    stride = timedelta(minutes=args.stride_min) if args.stride_min else None

    if args.kdist:
        from sqlalchemy import create_engine

        engine = create_engine(config.postgres_url)
        df = assign_templates(fetch_logs(engine, args.dataset))
        X, metas, _ = build_windows(df, window=window, stride=stride)
        curve = kdistance_curve(X, k=args.min_samples)
        if curve.size == 0:
            raise SystemExit("Not enough windows for a k-distance curve.")
        print(f"\nk-distance curve ({len(curve)} windows, k={args.min_samples}):")
        print("Look for the elbow; that distance is a good eps.\n")
        for i, d in enumerate(curve):
            bar = "#" * int(d / max(curve.max(), 1e-9) * 50)
            print(f"  {i:3d}  {d:7.3f}  {bar}")
        return

    summary = run_clustering(
        source_dataset=args.dataset,
        window=window,
        stride=stride,
        eps=args.eps,
        min_samples=args.min_samples,
        pca_components=args.pca,
        make_plot=not args.no_plot,
    )

    print(f"\nWindows:  {summary['windows']}")
    print(f"Clusters: {summary['clusters']} (excludes noise)")
    print(f"Noise:    {summary['noise']} windows labelled -1")
    print(f"Stored:   {summary['stored']} rows in log_windows")
    if summary.get("plot"):
        print(f"Plot:     {summary['plot']}")
    if summary.get("cluster_summary"):
        print("\nPer-cluster (sorted by anomaly ratio):")
        for label, stats in summary["cluster_summary"].items():
            print(
                f"  cluster {label:>3}: {stats['windows']:>2} windows, "
                f"anomaly_ratio={stats['mean_anomaly_ratio']:.2f}, "
                f"error_rate={stats['mean_error_rate']:.2f}"
            )


if __name__ == "__main__":
    main()
