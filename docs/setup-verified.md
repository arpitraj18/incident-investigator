# Day 1 — setup verification

Date: 2026-06-07
Environment: WSL2 Ubuntu, Python 3.12.13, Docker Desktop

All 6 checks passed:
- PostgreSQL 16 + pgvector extension
- Redis 7
- sentence-transformers/all-MiniLM-L6-v2 (384-dim embeddings)
- Groq API (llama-3.3-70b-versatile)
- BGL 2k sample data (2000 lines, 309.7 KB)
- Python 3.12.13

Next: Day 2 — BGL parser, Drain template extraction, database loader.