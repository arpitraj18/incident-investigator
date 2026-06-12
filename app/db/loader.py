"""Load parsed, templated BGL logs into PostgreSQL.

Runs the full ingestion pipeline:
    parse (bgl_parser) -> extract template (template_extractor) -> bulk insert

Bulk insert is used rather than row-by-row commits because inserting 2000+
rows one-at-a-time would mean 2000 round-trips to the database. Batching
makes this an order of magnitude faster.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import config
from app.db.models import LogTemplate, RawLog
from app.ingestion.bgl_parser import parse_file
from app.processing.template_extractor import TemplateExtractor

log = logging.getLogger(__name__)

# How many rows to accumulate before flushing to the DB in one batch.
_BATCH_SIZE = 500


def load_bgl_file(path: Path, source_dataset: str = "BGL") -> dict[str, int]:
    """Parse, template, and load a BGL log file into PostgreSQL.

    Returns a small summary dict: rows loaded and templates discovered.
    """
    engine = create_engine(config.postgres_url)
    extractor = TemplateExtractor()

    rows_loaded = 0
    batch: list[RawLog] = []
    # template string -> [count, first_seen, last_seen]
    template_stats: dict[str, list] = {}

    with Session(engine) as session:
        for entry in parse_file(path):
            match = extractor.add_log(entry.message)

            # Track template occurrence stats for the log_templates table.
            stats = template_stats.get(match.template)
            if stats is None:
                template_stats[match.template] = [
                    1, entry.log_timestamp, entry.log_timestamp
                ]
            else:
                stats[0] += 1
                stats[2] = entry.log_timestamp  # update last_seen

            batch.append(
                RawLog(
                    log_timestamp=entry.log_timestamp,
                    component=entry.component,
                    level=entry.level,
                    message=entry.message,
                    is_anomaly=entry.is_anomaly,
                    source_dataset=source_dataset,
                )
            )

            if len(batch) >= _BATCH_SIZE:
                session.add_all(batch)
                session.commit()
                rows_loaded += len(batch)
                batch = []

        # Flush any remaining rows.
        if batch:
            session.add_all(batch)
            session.commit()
            rows_loaded += len(batch)

        # Insert template stats.
        for template, (count, first_seen, last_seen) in template_stats.items():
            session.add(
                LogTemplate(
                    template=template,
                    occurrence_count=count,
                    first_seen=first_seen,
                    last_seen=last_seen,
                )
            )
        session.commit()

    summary = {
        "rows_loaded": rows_loaded,
        "templates_found": len(template_stats),
    }
    log.info("loaded %d rows, %d templates", rows_loaded, len(template_stats))
    return summary