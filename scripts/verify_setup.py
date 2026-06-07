"""End-to-end setup verifier. Run after `docker compose up -d` to confirm
the whole stack is wired up correctly.

Checks:
  1. PostgreSQL connection + pgvector extension installed
  2. Required tables exist
  3. Redis ping
  4. Embedding model loads and produces a 384-d vector
  5. Groq API key is set and the LLM responds
  6. BGL sample data is downloaded

Usage:
    python scripts/verify_setup.py
"""
import sys
from pathlib import Path

# Make sibling 'app' package importable when running this script directly
sys.path.insert(0, str(Path(__file__).parent.parent))

OK = "\033[92m[OK]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
WARN = "\033[93m[WARN]\033[0m"


def check_postgres() -> bool:
    print("\n[1/6] PostgreSQL + pgvector...")
    try:
        import psycopg
        from app.core.config import config

        with psycopg.connect(config.postgres_url) as conn:
            with conn.cursor() as cur:
                # pgvector installed?
                cur.execute(
                    "SELECT extname FROM pg_extension WHERE extname='vector';"
                )
                if cur.fetchone() is None:
                    print(f"{FAIL} pgvector extension not installed")
                    return False
                # Tables exist?
                cur.execute(
                    """SELECT tablename FROM pg_tables
                       WHERE schemaname='public'
                       ORDER BY tablename;"""
                )
                tables = [r[0] for r in cur.fetchall()]
                expected = {"raw_logs", "log_templates", "incidents"}
                missing = expected - set(tables)
                if missing:
                    print(f"{FAIL} Missing tables: {missing}")
                    return False
                print(f"{OK} pgvector + tables: {tables}")
                return True
    except Exception as e:
        print(f"{FAIL} {e}")
        return False


def check_redis() -> bool:
    print("\n[2/6] Redis...")
    try:
        import redis
        from app.core.config import config

        r = redis.Redis.from_url(config.redis_url)
        pong = r.ping()
        print(f"{OK} Redis ping: {pong}")
        return True
    except Exception as e:
        print(f"{FAIL} {e}")
        return False


def check_embeddings() -> bool:
    print("\n[3/6] Embedding model (first run downloads ~90MB)...")
    try:
        from sentence_transformers import SentenceTransformer
        from app.core.config import config

        model = SentenceTransformer(config.embedding_model)
        vec = model.encode("disk timeout on node compute-42")
        if len(vec) != config.embedding_dim:
            print(f"{FAIL} Expected dim {config.embedding_dim}, got {len(vec)}")
            return False
        print(f"{OK} Embedding model loaded, output dim: {len(vec)}")
        return True
    except Exception as e:
        print(f"{FAIL} {e}")
        return False


def check_groq() -> bool:
    print("\n[4/6] Groq LLM...")
    try:
        from app.core.config import config

        if not config.groq_api_key or "your_key" in config.groq_api_key:
            print(f"{WARN} GROQ_API_KEY not set in .env (skipping live call)")
            print("    Get a free key at https://console.groq.com/keys")
            return False

        from groq import Groq

        client = Groq(api_key=config.groq_api_key)
        resp = client.chat.completions.create(
            model=config.groq_model,
            messages=[{"role": "user", "content": "Say 'pong' and nothing else."}],
            max_tokens=10,
        )
        reply = resp.choices[0].message.content.strip()
        print(f"{OK} Groq responded with: {reply!r}")
        return True
    except Exception as e:
        print(f"{FAIL} {e}")
        return False


def check_sample_data() -> bool:
    print("\n[5/6] BGL sample data...")
    sample = Path(__file__).parent.parent / "data" / "samples" / "BGL_2k.log"
    if not sample.exists():
        print(f"{WARN} Not found at {sample}")
        print("    Run: python scripts/download_data.py")
        return False
    size_kb = sample.stat().st_size / 1024
    with open(sample) as f:
        line_count = sum(1 for _ in f)
    print(f"{OK} BGL sample: {line_count} lines, {size_kb:.1f} KB")
    return True


def check_python_version() -> bool:
    print("\n[6/6] Python version...")
    if sys.version_info < (3, 10):
        print(f"{FAIL} Need Python 3.10+, got {sys.version}")
        return False
    print(f"{OK} Python {sys.version.split()[0]}")
    return True


def main() -> int:
    print("=" * 60)
    print("  Incident Investigator - Setup Verification")
    print("=" * 60)

    results = [
        check_python_version(),
        check_postgres(),
        check_redis(),
        check_embeddings(),
        check_groq(),
        check_sample_data(),
    ]

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f"  All checks passed ({passed}/{total}) — ready for Day 2.")
        print("=" * 60)
        return 0
    print(f"  {passed}/{total} checks passed.")
    print("  Fix the FAIL/WARN items above before continuing.")
    print("=" * 60)
    return 1


if __name__ == "__main__":
    sys.exit(main())
