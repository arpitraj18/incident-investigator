"""Sanity test - replaced with real tests as we build."""


def test_imports() -> None:
    """Config module loads without error."""
    from app.core.config import config

    assert config.embedding_dim == 384
    assert config.postgres_db == "incident_db"
