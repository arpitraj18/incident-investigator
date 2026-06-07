# Incident Investigator

An AI-powered system that ingests production logs, clusters log events, detects anomalies, retrieves similar past incidents via RAG, and generates ranked root-cause hypotheses with causal timelines.

> **Status:** In active development. Day 1 of 21.

## Architecture

```
┌─────────────┐   ┌──────────────┐   ┌──────────────┐   ┌────────────────┐
│  Log files  │──▶│   Ingestion  │──▶│  Processing  │──▶│  Storage       │
│  (BGL/HDFS) │   │  (batch +    │   │  (Drain +    │   │  (PostgreSQL + │
│             │   │   streaming) │   │   DBSCAN +   │   │   pgvector +   │
└─────────────┘   └──────────────┘   │   LSTM)      │   │   Redis)       │
                                     └──────────────┘   └────────┬───────┘
                                                                 │
                                     ┌───────────────────────────▼───────┐
                                     │  AI/RAG Layer (LangGraph agent)   │
                                     │  retrieve → correlate → generate  │
                                     └───────────────┬───────────────────┘
                                                     │
                                     ┌───────────────▼────────┐
                                     │  Dashboard (Streamlit) │
                                     └────────────────────────┘
```

## Stack

| Layer            | Tech                                    |
|------------------|-----------------------------------------|
| Language         | Python 3.12                             |
| Web framework    | FastAPI (async)                         |
| Orchestration    | LangChain + LangGraph                   |
| LLM              | Groq (Llama 3.3 70B)                    |
| Embeddings       | sentence-transformers (all-MiniLM-L6-v2)|
| Vector DB        | pgvector (PostgreSQL extension)         |
| Queue/Cache      | Redis                                   |
| Log parsing      | drain3                                  |
| ML               | scikit-learn (DBSCAN), PyTorch (LSTM)   |
| Dashboard        | Streamlit + Plotly                      |
| Infra            | Docker + docker-compose                 |
| CI/CD            | GitHub Actions                          |

## Quick start

```bash
# 1. Clone and enter
git clone <repo-url> && cd incident-investigator

# 2. Configure
cp .env.example .env
# Edit .env and set GROQ_API_KEY (get one free at https://console.groq.com/keys)

# 3. Start infrastructure (PostgreSQL + Redis)
docker compose up -d

# 4. Python environment
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 5. Download sample data
python scripts/download_data.py

# 6. Verify everything works
python scripts/verify_setup.py
```

## Project structure

```
incident-investigator/
├── app/
│   ├── api/          # FastAPI endpoints
│   ├── core/         # Config, logging
│   ├── ingestion/    # Log ingestion + streaming
│   ├── processing/   # Drain, DBSCAN, LSTM
│   ├── rag/          # Embedding + retrieval
│   ├── llm/          # LLM clients + prompts
│   ├── db/           # SQLAlchemy models, queries
│   └── eval/         # Evaluation harness
├── data/
│   ├── raw/          # Downloaded full datasets
│   ├── processed/    # Parsed/cleaned data
│   └── samples/      # Small samples for dev
├── scripts/          # One-off scripts
├── tests/            # pytest suite
├── notebooks/        # Exploration notebooks
├── docker-compose.yml
└── requirements.txt
```

## Roadmap

- [x] **Day 1:** Project skeleton, docker-compose, CI
- [ ] **Days 2-3:** Drain log parsing, ingestion
- [ ] **Days 4-5:** DBSCAN clustering
- [ ] **Days 6-7:** LSTM anomaly detection + eval v1
- [ ] **Days 8-9:** Embeddings + pgvector retrieval
- [ ] **Days 10-11:** LangGraph agentic workflow
- [ ] **Days 12-13:** Eval harness v2
- [ ] **Day 14:** FastAPI endpoints
- [ ] **Days 15-16:** Streaming ingestion (Redis)
- [ ] **Days 17-18:** Streamlit dashboard
- [ ] **Days 19-20:** Deploy
- [ ] **Day 21:** Final README, results table, polish
