# Interview notes — Incident Investigator

Personal reference for talking about this project in interviews.
Living document — append as new decisions and discussions come up.

---

## Testing strategy in production

When asked "how would you validate this in production?":

Three layers.

1. **Offline benchmarking against historical labeled incidents** — what I did on BGL and HDFS. Objective precision/recall, retrieval accuracy, root-cause match. Reproducible, comparable to published numbers.

2. **Shadow mode** — run the system alongside the existing on-call workflow. Its hypotheses are logged but never shown to engineers. Periodically compare what it suggested against what humans actually fixed. No real-world impact, real-world data.

3. **Gradual rollout with confidence thresholds** — only surface hypotheses when both LLM confidence and retrieval similarity clear a bar. Human override always available. Expand exposure as accuracy holds.

**Why this answer works:** it signals understanding that offline metrics aren't sufficient — observability tools need shadow validation and conservative rollout before being trusted on real incidents.

---

## Why BGL specifically (and what it means about generalization)

BGL = Blue Gene/L supercomputer logs. Hardware-specific vocabulary (`R02-M1-N0-C:J12-U11` components, HPC failure modes). Unusual relative to typical production logs.

**Why we use it anyway:**

- It has human-annotated anomaly labels — the foundation of our eval harness.
- Most real production logs are unlabeled.
- It's the academic standard, so our numbers are comparable to literature.

**What's BGL-specific in the code:** only the parser (`app/ingestion/bgl_parser.py`).

**What's general:** everything downstream — Drain, clustering, LSTM, embeddings, RAG, LangGraph, eval. The same pipeline runs on any log source with a new parser.

**Interview phrasing:** "I built a domain-general log investigation pipeline. I benchmarked on BGL because labels enable rigorous evaluation. The same pipeline works on any log source — you swap the parser and retrain, the architecture and eval methodology are dataset-independent."

---

## Limitations of prior work and how we improve on them

The original BGL paper (Oliner & Stearley, 2007) identified two key weaknesses in their alert-filtering approach. These are worth being explicit about because they map directly to what we improve and where we still fall short.

### Weakness 1: cross-source / cross-time alert correlation

**Their problem:** no reliable way to determine whether two differently-worded messages described the same underlying event. Pattern matching and statistical filtering, no notion of *meaning*.

**How we improve:**

- Semantic embeddings (`sentence-transformers/all-MiniLM-L6-v2`) place "connection timeout on node 42" and "node 42 failed to respond within deadline" near each other in 384-d space — even with different wording. Fundamentally different capability than 2007.
- The LangGraph agent reasons about whether a past incident relates to current symptoms, not just whether they share keywords.

**Where we still fall short:**

- Embedding similarity ≠ causal relatedness. Two semantically similar messages might describe unrelated problems; two causally linked failures might be textually very different ("disk full" vs. "service crashed").
- We match on log content only — not system topology or temporal causality. Real cross-source correlation in production needs to model service dependencies.
- Multi-modal correlation (CPU metric + log line + network signal) is out of scope; we're text-only.

### Weakness 2: one-size-fits-all static thresholds

**Their problem:** a single global filtering threshold across all alert categories. Different categories need different sensitivities; thresholds also drift over time.

**How we improve:**

- **DBSCAN** doesn't impose a global anomaly threshold — it finds dense regions in feature space, so different alert categories form differently-sized clusters that are implicitly tuned by the data.
- **LSTM** outputs continuous anomaly *scores*, not binary decisions. Cutoffs can be applied per cluster or per category.
- **The agentic layer** is the biggest gain. It can apply category-specific reasoning ("a single kernel parity error matters" vs. "transient network timeout needs N occurrences before mattering") because it has semantic understanding of category context.

**Where we still fall short:**

- "Thresholds change over time" is the genuinely hard part and we don't solve it. Our LSTM is trained once on labeled data, not continuously retrained.
- True adaptive thresholding requires online learning, human-in-the-loop feedback, or explicit concept drift detection — all out of scope for v1.

### Interview-ready synthesis

> "Our system addresses both limitations meaningfully but not completely. Semantic embeddings give us a real shot at cross-source correlation that wasn't possible in 2007 — but they capture semantic similarity, not causal relatedness. The agentic layer applies different reasoning to different alert categories instead of one global threshold — but we don't adapt thresholds over time, which would require online learning or feedback loops. We're a step forward, not a solution. The remaining gap is well-defined and would be the natural next phase of work."

The closing sentence matters — acknowledging the limits of your own work clearly signals calibration, which interviewers value more than overclaiming.

---
## Architectural decisions and why

### Stack

- **Python 3.12** — newest stable version with full ML/LLM ecosystem support. Not 3.14 (PyTorch/sentence-transformers lag). Not 3.10 (older async semantics).
- **WSL2 + Docker** — tooling consistency. CI runs on Ubuntu; dev on WSL Ubuntu means no "works on my machine" debugging.
- **PostgreSQL + pgvector** instead of Chroma/Pinecone/Weaviate — consolidates structured incident storage and vector similarity in one database. Real SQL skills on the resume. pgvector's IVFFlat index is fast enough at our scale (thousands of incidents).
- **Redis** for streaming queue + cache — right-sized; Kafka would be overkill.
- **CPU PyTorch** — no GPU available, dataset small enough that GPU overhead isn't worth it. Saves 5 GB on the image.
- **Groq LLM (free)** — Llama 3.3 70B, OpenAI-compatible API, fast inference. Swappable to paid provider with one URL change.
- **sentence-transformers/all-MiniLM-L6-v2** for embeddings — 384-dim, local, free. Cost/quality tradeoff favors local at our scale.

### Folder structure: layered pipeline

```
app/ingestion → processing → rag → llm
```

Folders mirror data flow. Each layer has a clear input/output contract. Easy to test in isolation, easy to swap components.

### Pinned dependencies

Every package pinned to exact version. LangChain's API still changes between minor releases. Cost is manual upgrades, which Dependabot would automate in production.

### CI from Day 1

Lint (ruff) + tests (pytest) on every push. Habit compounds — by the time the eval harness exists, it runs on every push too.

---

## Why drain3 for log parsing (not regex, not LLM)

- **Regex:** brittle, breaks when log formats evolve.
- **LLM-based parsing:** slow and expensive at scale (hundreds of thousands of log lines × LLM call = unworkable).
- **Drain:** fixed-depth parse tree, O(log n) per line, learns templates online with no training. Industry-standard.

**Interview phrasing:** "Using an LLM for parsing would be both slower and more expensive than the actual investigation step. Drain handles the boring high-volume work so the LLM does what only an LLM can."

---

## The differentiator: objective evaluation harness

The point of this project isn't "I built an incident investigation tool." Plenty of those exist (Datadog, PagerDuty, incident.io).

The point is **measurement**: I built one *and* benchmarked it on labeled data with precision/recall on anomaly detection, retrieval accuracy on incident matching, and root-cause quality scoring.

Almost no student-tier project does the eval. It's the resume bullet that matters most.

---

## Things to add as we build

*(append below as project evolves — eval numbers, design changes, gotchas)*
