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

---

## Day 4 — DBSCAN clustering results (the first real numbers)

First stage that produced *measured* output rather than plumbing, so everything here is observed, not projected.

### What was run

DBSCAN over time-windowed log features. 2000 BGL rows → **830 non-empty 5-minute tumbling windows**, each a **115-dimensional** feature vector (volume, error rate, burst rate, distinct-template/component counts, plus per-component and per-template frequency columns). `eps = 2.5`, `min_samples = 3`, picked from the elbow of the k-distance curve (sort each point's distance to its k-th nearest neighbour; eps is where the curve kinks upward).

### The headline result

The ground-truth `is_anomaly` label was deliberately **held out of the feature matrix** — computed per window only as a post-hoc descriptor. Clustering still separated the data cleanly:

- **275-window cluster at 0% anomalies** (cluster 3) — the dominant "normal KERNEL chatter" pattern.
- **73 windows across 5 clusters at 100% anomalies** (clusters 6, 7, 23, 25, 31), all also 100% error-rate.
- Global anomaly rate is **7.15%**, so unsupervised structure *concentrated* the anomalies instead of smearing them at the background rate.
- **36 clusters total, 101 noise windows** (label −1).

Because the label never entered the features, the model didn't cheat — it found the structure from template/component/error shape alone. When an interviewer asks "did it actually work?", this is the answer.

**Resume bullet (fill in when updating the CV):**
> Performed DBSCAN clustering on 830 time-windowed log features; unsupervised clustering (anomaly labels held out) concentrated 100% of anomalies into 5 distinct clusters (73 windows) against a 0% baseline cluster (275 windows), versus a global 7.15% anomaly rate.

### Why DBSCAN, not KMeans

Three reasons, each of which an interviewer can probe:

- **No k up front.** We don't know the number of incident patterns. KMeans demands `k`; DBSCAN discovers it from density.
- **Non-spherical clusters.** Incident patterns aren't convex equal-radius blobs. DBSCAN finds arbitrary-shaped dense regions; KMeans assumes round clusters.
- **First-class outliers.** DBSCAN's noise label (−1) is an explicit "this window fits no pattern" signal. KMeans forces every point into a cluster, so there's nowhere for a genuine one-off to go.

### Two findings worth *understanding*, not just reporting

**Why anomalies landed in clusters, not in noise.** The naive intuition is "anomalies are rare → outliers → label −1." That happened on a synthetic test but *not* on real BGL. The reason: BGL's anomalous windows are **repetitive** — the same failure template recurs often enough to form its own dense region, so DBSCAN groups it. Anomalies only land in noise when they're one-off unique events. Ours clustering is the *more interesting* outcome: it means the incidents are detectable recurring patterns, not random noise.

**Why Drain reported ~104 templates here but 157 at ingestion.** Not a bug — Drain is order-sensitive (gotcha #6). Ingestion reads the file in file order; clustering reads in timestamp order. Different traversal = different template-merge boundaries, landing at opposite ends of the documented 105–157 range. If the two ever need to match, order `fetch_logs` by `id` instead of `log_timestamp`.

### The genuinely interesting anomaly: error_rate=1.00, anomaly_ratio=0.00

Several clusters (e.g. 11, 26, 4) are full of error-*severity* log lines that BGL's ground truth does **not** mark as anomalies. Honest interpretation: either recoverable errors the operators chose not to flag, or a labeling gap in the dataset. No firm conclusion claimed — but noting it signals the output was actually read, not just summarised.

### Design decisions locked in

- `is_anomaly` excluded from clustering features (descriptor only) — so cluster↔anomaly alignment is a discovered signal, not circular leakage.
- Results stored in a dedicated `log_windows` table, not a column on `raw_logs` — clustering is window-granularity and overlapping windows would make a per-row label ambiguous; `raw_logs` stays an append-only ingestion record.
- StandardScaler before DBSCAN — counts and rates live on very different scales, and eps is a single threshold across all dimensions.
- Clustering is idempotent (wipes prior rows for the dataset before insert), unlike the intentionally one-shot loader.
- Scatter plot uses plotly (already a dependency) → no new packages.

### Caveat to surface in the README

2000 lines span **213 days**, so windows are sparse (~2–3 lines each). This is a property of the BGL *sample* (a thin slice across ~7 months), not the pipeline — one sentence in the README stops anyone reading the window counts as a bug. The 36 clusters are also mildly over-segmented; left untuned on purpose until the Day 12–13 eval harness gives an objective metric to optimise `eps`/PCA against. Tuning against a number, not by eye.

**Interview phrasing:** "I held the anomaly labels out of the clustering features on purpose, so any alignment between clusters and anomalies is something the model discovered, not something I fed it. On BGL it concentrated the 7% anomalies into clusters that were either 0% or 100% anomalous — and they *clustered* rather than showing up as noise, which tells me the failures are recurring patterns, not random one-offs. I'm not tuning the cluster count by eye; the eval harness will give me a metric to optimise against."

### Verification

20 tests passing (11 prior + 8 new unit + 1 DB integration that runs against live Postgres), ruff clean. The `log_windows` round-trip is verified end-to-end.

*(append below as project evolves — eval numbers, design changes, gotchas)*
