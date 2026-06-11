"""SQLAlchemy models mapping to the PostgreSQL schema.

These mirror the tables defined in scripts/init_db.sql. The schema is the
source of truth (created at container startup); these models are how Python
reads and writes those tables.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RawLog(Base):
    __tablename__ = "raw_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    log_timestamp: Mapped[datetime | None] = mapped_column(DateTime)
    component: Mapped[str | None] = mapped_column(String(255))
    level: Mapped[str | None] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    source_dataset: Mapped[str | None] = mapped_column(String(50))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class LogTemplate(Base):
    __tablename__ = "log_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    template: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime)