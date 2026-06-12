"""Log template extraction using the Drain algorithm.

Drain (He et al., 2017) parses free-text log messages into templates by
clustering them in a fixed-depth tree. Each message maps to a template like
"connection timeout on node <*>" plus the extracted parameters.

We wrap drain3 so the rest of the system depends on our interface, not the
library directly — makes it swappable and testable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TemplateMatch:
    """Result of matching a log message against learned templates."""

    template_id: int
    template: str
    parameters: list[str]


class TemplateExtractor:
    """Learns and matches log templates.

    Stateful by design: it improves its templates as it sees more logs.
    Call `add_log` during ingestion; the same instance accumulates knowledge.
    """

    def __init__(self, sim_threshold: float = 0.4) -> None:
        # sim_threshold: how similar two logs must be to share a template.
        # 0.4 is the drain3 default and works well on system logs. Higher =
        # stricter (more templates), lower = looser (fewer, broader templates).
        config = TemplateMinerConfig()
        config.drain_sim_th = sim_threshold
        # TODO: for persistence across runs, pass a RedisPersistence here.
        self._miner = TemplateMiner(config=config)

    def add_log(self, message: str) -> TemplateMatch:
        """Feed one log message. Updates templates and returns the match.

        Use during ingestion when the extractor should learn from the data.
        """
        result = self._miner.add_log_message(message)
        return TemplateMatch(
            template_id=result["cluster_id"],
            template=result["template_mined"],
            parameters=self._miner.extract_parameters(
                result["template_mined"], message
            )
            or [],
        )

    def match_only(self, message: str) -> TemplateMatch | None:
        """Match a message against existing templates WITHOUT learning.

        Use at inference time when templates are frozen. Returns None if the
        message doesn't match any known template.
        """
        cluster = self._miner.match(message)
        if cluster is None:
            return None
        return TemplateMatch(
            template_id=cluster.cluster_id,
            template=cluster.get_template(),
            parameters=self._miner.extract_parameters(
                cluster.get_template(), message
            )
            or [],
        )

    @property
    def template_count(self) -> int:
        """How many distinct templates have been learned so far."""
        return len(self._miner.drain.clusters)